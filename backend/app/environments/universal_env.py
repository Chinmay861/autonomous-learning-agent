from .base import Environment, EnvironmentState, ActionResult
from typing import Any

class UniversalSimulationEnvironment(Environment):
    name = "universal_simulation"
    description = "Universal task simulation environment"

    def __init__(self, task_description: str = "", llm: Any = None):
        self.task_description = task_description
        self.llm = llm
        self.step_count = 0
        self.score = 0.0
        self.completed = False
        self.state_desc = f"Initial state for task: {task_description[:300]}"
        self.history = []

    async def observe(self) -> EnvironmentState:
        return EnvironmentState(
            score=self.score,
            description=self.state_desc,
            is_terminal=self.completed,
            metadata={
                "step": self.step_count,
                "completed": self.completed,
                "history_length": len(self.history)
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
                prompt = f"""You are the Environment Simulator for this task:
Task: {self.task_description}

Current State: {self.state_desc}
Action Attempted: {action_text}

Simulate the result of this action in JSON:
{{
  "success": true,
  "output": "Description of what happened after this action",
  "new_state": "Updated state description of the environment",
  "goal_achieved": false,
  "reward": 5.0
}}"""
                sim_res = await self.llm.generate_json(prompt)
                if isinstance(sim_res, dict):
                    output = str(sim_res.get("output", f"Executed: {action_text}"))
                    self.state_desc = str(sim_res.get("new_state", output))
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
                        state_change=self.state_desc
                    )
            except Exception:
                pass

        # Deterministic fallback
        output = f"Action '{action_text}' executed in environment."
        self.state_desc = f"State after step {self.step_count}: {output}"
        self.score += 1.0
        self.history.append({"action": action_text, "result": output})
        return ActionResult(
            success=True,
            output=output,
            reward=1.0,
            state_change=self.state_desc
        )

    async def reset(self) -> EnvironmentState:
        self.step_count = 0
        self.score = 0.0
        self.completed = False
        self.state_desc = f"Initial state for task: {self.task_description[:300]}"
        self.history = []
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
