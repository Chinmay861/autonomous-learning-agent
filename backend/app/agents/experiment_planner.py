"""
Experiment Planner - Decides what action the agent should take next,
balancing exploration, exploitation, verification, optimization, and recovery.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.prompts import get_prompt
from app.models.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class StagnationMetrics:
    """Metrics for detecting when the agent is stuck."""
    recent_actions: list[str] = field(default_factory=list)
    recent_results: list[str] = field(default_factory=list)
    repeated_action_count: int = 0
    iterations_since_discovery: int = 0
    iterations_since_improvement: int = 0
    unique_actions_tried: int = 0
    total_iterations: int = 0
    success_rate: float = 0.0
    learning_rate: float = 0.0
    
    def record_action(self, action: str, result: str, was_successful: bool, new_learning: bool):
        self.recent_actions.append(action)
        self.recent_results.append(result)
        self.total_iterations += 1
        
        # Check for repeats
        if len(self.recent_actions) >= 2 and self.recent_actions[-1] == self.recent_actions[-2]:
            self.repeated_action_count += 1
        else:
            self.repeated_action_count = 0
        
        # Track improvement
        if was_successful:
            self.iterations_since_improvement = 0
        else:
            self.iterations_since_improvement += 1
        
        if new_learning:
            self.iterations_since_discovery = 0
        else:
            self.iterations_since_discovery += 1
        
        # Keep only recent history
        if len(self.recent_actions) > 50:
            self.recent_actions = self.recent_actions[-50:]
            self.recent_results = self.recent_results[-50:]
    
    @property
    def is_stagnant(self) -> bool:
        return (
            self.repeated_action_count >= 3
            or self.iterations_since_discovery >= 20
            or self.iterations_since_improvement >= 15
        )
    
    def summary(self) -> str:
        return (
            f"Iterations: {self.total_iterations} | "
            f"Repeats: {self.repeated_action_count} | "
            f"Since discovery: {self.iterations_since_discovery} | "
            f"Since improvement: {self.iterations_since_improvement}"
        )


class ExperimentPlanner:
    """Decides what experiment/action to perform next."""
    
    def __init__(self, llm: LLMProvider, prompt_version: str = "v1"):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt("experiment_planner", prompt_version)
        self.experiment_history: list[dict] = []
    
    async def plan_next_experiment(
        self,
        task_description: str,
        environment_state: str,
        known_rules: list[dict],
        hypothesized_rules: list[dict],
        recent_history: list[dict],
        current_strategy: str,
        failed_actions: list[str],
        retrieved_memories: list[dict] | None,
        stagnation: StagnationMetrics,
        available_tools: list[dict],
        iteration: int,
    ) -> dict:
        """Plan the next experiment/action."""
        # Build context
        history_text = ""
        for h in recent_history[-10:]:
            history_text += f"  Iter {h.get('iteration', '?')}: {h.get('action', '?')} -> {h.get('result_summary', '?')}\n"
        
        failed_text = "\n".join(f"  - {f}" for f in failed_actions[-10:]) if failed_actions else "  None"
        
        memory_text = "None (retrieval disabled or no relevant memories)"
        if retrieved_memories:
            lines = []
            for m in retrieved_memories[:5]:
                payload = m.get("payload") or {}
                score = m.get("score", m.get("similarity", 0)) or 0
                # Store payloads use "knowledge" (or "learning_text"); the planner
                # previously read keys that the retriever never returned.
                content = (
                    payload.get("knowledge")
                    or payload.get("learning_text")
                    or payload.get("title")
                    or m.get("learning")
                    or "?"
                )
                title = payload.get("title")
                label = f"{title}: " if title and title not in content else ""
                lines.append(f"  - [{score:.2f}] {label}{content}")
            memory_text = "\n".join(lines)
        
        tools_text = "\n".join(
            f"  - {t['name']}: {t.get('description', 'No description')} | Parameters: {json.dumps(t.get('parameters', t.get('schema', {})))}"
            for t in available_tools
        )
        
        user_prompt = f"""Iteration: {iteration}

Task: {task_description}

Current Environment State:
{environment_state}

Known Rules:
{json.dumps(known_rules[:10], indent=2)}

Hypothesized Rules:
{json.dumps(hypothesized_rules[:10], indent=2)}

Recent Action History:
{history_text}

Failed Actions:
{failed_text}

Retrieved Memories:
{memory_text}

Current Strategy: {current_strategy}

Stagnation Metrics: {stagnation.summary()}
Is Stagnant: {stagnation.is_stagnant}

Available Tools:
{tools_text}

Plan the next experiment. If stagnation is detected, prioritize changing approach."""
        
        try:
            schema = {
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "action": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                        "required": ["tool", "parameters"],
                    },
                    "expected_result": {"type": "string"},
                    "alternative_result": {"type": "string"},
                    "information_gain": {"type": "string"},
                    "risk": {"type": "string"},
                },
                "required": ["mode", "reasoning", "hypothesis", "action", "expected_result"],
            }
            
            result = await self.llm.structured_generate(
                prompt=user_prompt,
                schema=schema,
                system=self.system_prompt,
            )
            
            # Record in experiment history
            self.experiment_history.append({
                "iteration": iteration,
                "mode": result.get("mode", "explore"),
                "action": result.get("action", {}),
                "hypothesis": result.get("hypothesis", ""),
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Experiment planning failed: {e}")
            # Fallback: try a random available tool
            if available_tools:
                tool = available_tools[0]
                t_name = tool.get("name", "")
                params = {}
                if t_name == "move":
                    params = {"direction": "Right"}
                elif t_name == "act":
                    params = {"action": "increase"}
                return {
                    "mode": "explore",
                    "reasoning": f"Planning fallback, trying {t_name}",
                    "hypothesis": f"Testing {t_name}",
                    "action": {"tool": t_name, "parameters": params},
                    "expected_result": "Response from the environment",
                    "information_gain": "medium",
                    "risk": "low",
                }
            return {
                "mode": "explore",
                "reasoning": "Planning failed, no tools available",
                "hypothesis": "N/A",
                "action": {"tool": "observe", "parameters": {}},
                "expected_result": "Observation of current state",
                "information_gain": "low",
                "risk": "low",
            }
    
    def has_tried_action(self, action: dict) -> bool:
        """Check if this exact action has been tried before."""
        action_str = json.dumps(action, sort_keys=True)
        for exp in self.experiment_history:
            if json.dumps(exp.get("action", {}), sort_keys=True) == action_str:
                return True
        return False
