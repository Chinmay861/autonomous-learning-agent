import json
import logging
from typing import Dict, List, Any
from app.models.llm_provider import LLMProvider
from app.agents.prompts import get_prompt

logger = logging.getLogger(__name__)

class StrategyManager:
    def __init__(self, llm: LLMProvider, prompt_version: str = 'v1'):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt('strategy_manager', prompt_version)
        self.current_strategy = "Initial broad exploration."
        self.current_phase = "broad_exploration"
        self.strategy_history: List[dict] = []

    async def evaluate_strategy(self, evaluation_results: List[dict], stagnation_metrics_summary: str, known_rules: List[dict], discoveries: List[str], iteration: int) -> dict:
        prompt = (
            f"Evaluate the current strategy and recommend adjustments.\n"
            f"Iteration: {iteration}\n"
            f"Current Strategy: {self.current_strategy}\n"
            f"Current Phase: {self.current_phase}\n"
            f"Evaluation Results: {json.dumps(evaluation_results, indent=2)}\n"
            f"Stagnation Metrics: {stagnation_metrics_summary}\n"
            f"Known Rules: {json.dumps(known_rules, indent=2)}\n"
            f"Discoveries: {json.dumps(discoveries, indent=2)}\n"
        )
        
        try:
            response = await self.llm.generate(
                prompt=prompt,
                system_prompt=self.system_prompt,
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "strategy_assessment": {"type": "string"},
                            "change_needed": {"type": "boolean"},
                            "reason": {"type": "string"},
                            "new_strategy": {"type": "string"},
                            "phase": {"type": "string"},
                            "priorities": {"type": "array", "items": {"type": "string"}},
                            "avoid": {"type": "array", "items": {"type": "string"}},
                            "evidence": {"type": "string"}
                        },
                        "required": ["strategy_assessment", "change_needed", "reason", "new_strategy", "phase", "priorities", "avoid", "evidence"]
                    }
                }
            )
            result = json.loads(response)
            
            if result.get("change_needed", False):
                history_entry = {
                    "strategy": self.current_strategy,
                    "phase": self.current_phase,
                    "start_iteration": self.strategy_history[-1]["end_iteration"] if self.strategy_history else 0,
                    "end_iteration": iteration,
                    "reason_for_change": result.get("reason", ""),
                    "evidence": result.get("evidence", "")
                }
                self.strategy_history.append(history_entry)
                self.current_strategy = result.get("new_strategy", self.current_strategy)
                self.current_phase = result.get("phase", self.current_phase)
                
            return result
        except Exception as e:
            logger.error(f"Error evaluating strategy: {e}")
            return {
                "strategy_assessment": "Error in strategy evaluation.",
                "change_needed": False,
                "reason": str(e),
                "new_strategy": self.current_strategy,
                "phase": self.current_phase,
                "priorities": [],
                "avoid": [],
                "evidence": ""
            }

    def get_current_strategy(self) -> str:
        return self.current_strategy

    def get_strategy_history(self) -> List[dict]:
        return self.strategy_history

    def to_dict(self) -> dict:
        return {
            "current_strategy": self.current_strategy,
            "current_phase": self.current_phase,
            "strategy_history": self.strategy_history
        }

    @classmethod
    def from_dict(cls, data: dict, llm: LLMProvider, prompt_version: str = 'v1') -> "StrategyManager":
        manager = cls(llm=llm, prompt_version=prompt_version)
        manager.current_strategy = data.get("current_strategy", "Initial broad exploration.")
        manager.current_phase = data.get("current_phase", "broad_exploration")
        manager.strategy_history = data.get("strategy_history", [])
        return manager
