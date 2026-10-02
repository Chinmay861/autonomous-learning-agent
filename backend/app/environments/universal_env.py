from .base import Environment, EnvironmentState, ActionResult
from typing import Any

class UniversalSimulationEnvironment(Environment):
    name = "universal_simulation"
    description = "Adaptive task discovery and simulation environment"

    def __init__(self, task_description: str = "", llm: Any = None):
        self.task_description = task_description
        self.llm = llm
        self.step_count = 0
        self.score = 0.0
        self.completed = False
        self.progress = 0.0
        self.known_facts: list[str] = []
        self.unknowns: list[str] = ["What actions are available and which one advances the goal"]
        self.next_steps: list[str] = ["Inspect the task and perform a low-risk information-gathering action"]
        self.blockers: list[str] = []
        self.state_desc = ""
        self.history = []
        self._refresh_state_description()

    def _refresh_state_description(self) -> None:
        """Expose structured discovery state to the planner as readable text."""
        self.state_desc = (
            f"Task objective: {self.task_description[:500]}\n"
            f"Progress: {self.progress:.0%}\n"
            f"Known facts: {self.known_facts or ['No verified facts yet']}\n"
            f"Unknowns to resolve: {self.unknowns or ['No major unknowns recorded']}\n"
            f"Recommended next steps: {self.next_steps or ['Choose the next evidence-producing action']}\n"
            f"Blockers: {self.blockers or ['None recorded']}\n"
            f"Actions observed: {len(self.history)}"
        )

    async def _initialize_discovery_model(self) -> None:
        if not self.llm:
            return
        prompt = f"""You are the discovery analyst for an unknown task environment.
Task: {self.task_description}

Before acting, build a cautious initial model. Separate verified facts from
assumptions, identify the most important unknowns, and propose low-risk probes
that produce evidence. Do not claim the task is complete.

Return JSON:
{{
  "known_facts": ["verified fact"],
  "unknowns": ["important question"],
  "next_steps": ["next evidence-producing action"],
  "blockers": ["blocker, if any"],
  "progress": 0.0
}}"""
        try:
            model = await self.llm.generate_json(prompt)
            if isinstance(model, dict):
                self.known_facts = [str(item) for item in model.get("known_facts", [])][:10]
                self.unknowns = [str(item) for item in model.get("unknowns", [])][:10]
                self.next_steps = [str(item) for item in model.get("next_steps", [])][:10]
                self.blockers = [str(item) for item in model.get("blockers", [])][:10]
                self.progress = max(0.0, min(1.0, float(model.get("progress", 0.0))))
                self._refresh_state_description()
        except Exception:
            pass

    async def observe(self) -> EnvironmentState:
        return EnvironmentState(
            score=self.score,
            description=self.state_desc,
            is_terminal=self.completed,
            metadata={
                "step": self.step_count,
                "completed": self.completed,
                "history_length": len(self.history),
                "progress": self.progress,
                "known_facts": self.known_facts,
                "unknowns": self.unknowns,
                "next_steps": self.next_steps,
                "blockers": self.blockers,
            }
        )

    async def act(self, action: dict | str) -> ActionResult:
        self.step_count += 1
        action_text = ""
        if isinstance(action, str):
            action_text = action
        elif isinstance(action, dict):
            for k in ["action", "command", "step", "input", "direction", "code"]:
                if k in action and action[k]:
                    action_text = str(action[k])
                    break
            if not action_text and "parameters" in action and isinstance(action["parameters"], dict):
                for k in ["action", "command", "step", "input", "direction", "code"]:
                    if k in action["parameters"] and action["parameters"][k]:
                        action_text = str(action["parameters"][k])
                        break
            if not action_text:
                action_text = str(action)

        if not action_text or action_text.strip() in ["{}", "None", ""]:
            return ActionResult(
                success=False,
                error="No action specified. Please provide an action or command to execute.",
                reward=-1.0
            )

        # Evaluate through LLM simulation if available
        if self.llm:
            try:
                prompt = f"""You are the Environment Simulator and discovery coach for this unknown task:
Task: {self.task_description}

Current State: {self.state_desc}
Action Attempted: {action_text}

Simulate the result conservatively. Treat an action as useful only when it
produces evidence or measurable progress. Update the task model after the
action. Never claim completion without concrete evidence. Return JSON:
{{
  "success": true,
  "output": "Description of what happened after this action",
  "known_facts": ["facts supported by this action"],
  "unknowns": ["important unresolved questions"],
  "next_steps": ["specific next evidence-producing actions"],
  "blockers": ["current blockers"],
  "progress": 0.0,
  "goal_achieved": false,
  "reward": 5.0
}}"""
                sim_res = await self.llm.generate_json(prompt)
                if isinstance(sim_res, dict):
                    output = str(sim_res.get("output", f"Executed: {action_text}"))
                    if "known_facts" in sim_res:
                        self.known_facts = [str(item) for item in sim_res.get("known_facts", [])][:10]
                    if "unknowns" in sim_res:
                        self.unknowns = [str(item) for item in sim_res.get("unknowns", [])][:10]
                    if "next_steps" in sim_res:
                        self.next_steps = [str(item) for item in sim_res.get("next_steps", [])][:10]
                    if "blockers" in sim_res:
                        self.blockers = [str(item) for item in sim_res.get("blockers", [])][:10]
                    if "progress" in sim_res:
                        self.progress = max(0.0, min(1.0, float(sim_res.get("progress", self.progress))))
                    self._refresh_state_description()
                    is_goal = bool(sim_res.get("goal_achieved", False))
                    reward = float(sim_res.get("reward", 1.0))
                    if is_goal:
                        self.completed = True
                        reward += 50.0
                    self.score += reward
                    self.history.append({"action": action_text, "result": output})
                    return ActionResult(
                        success=bool(sim_res.get("success", True)),
                        output=output,
                        reward=reward,
                        state_change=self.state_desc,
                        metadata={
                            "progress": self.progress,
                            "next_steps": self.next_steps,
                            "unknowns": self.unknowns,
                            "blockers": self.blockers,
                        },
                    )
            except Exception:
                pass

        # Deterministic fallback
        output = "The simulator is unavailable, so this action cannot be verified."
        self.blockers = ["No language model is available to simulate or verify the unknown environment"]
        self._refresh_state_description()
        self.history.append({"action": action_text, "result": output})
        return ActionResult(
            success=False,
            output=output,
            reward=0.0,
            state_change=self.state_desc
        )

    async def reset(self) -> EnvironmentState:
        self.step_count = 0
        self.score = 0.0
        self.completed = False
        self.progress = 0.0
        self.known_facts = []
        self.unknowns = ["What actions are available and which one advances the goal"]
        self.next_steps = ["Inspect the task and perform a low-risk information-gathering action"]
        self.blockers = []
        self.history = []
        self._refresh_state_description()
        await self._initialize_discovery_model()
        return await self.observe()

    async def is_finished(self) -> bool:
        return self.completed

    def get_available_actions(self) -> list[dict]:
        return [
            {
                "name": "interact",
                "description": "Perform an action or command towards completing the task",
                "parameters": {
                    "action": "string (the specific action, move, or command to take)"
                }
            }
        ]
