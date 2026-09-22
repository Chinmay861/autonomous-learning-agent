import random
from .base import Environment, EnvironmentState, ActionResult

class BenchmarkEnvironment(Environment):
    name = "benchmark_env"
    description = "Number optimization game with hidden mechanics"

    def __init__(self):
        self.do_reset()

    def do_reset(self):
        self.score = 0.0
        self.energy = 100
        self.stability = 50
        self.multiplier = 1
        self.phase = 'calm'
        self.action_count = 0

    def _update_phase(self):
        if self.stability < 20:
            self.phase = 'critical'
        elif 20 <= self.stability <= 40:
            if random.random() < 0.3:
                self.phase = 'volatile'
            else:
                self.phase = 'calm'
        else:
            self.phase = 'calm'

    def _get_energy_hint(self):
        if self.energy > 70:
            return 'high'
        elif self.energy > 30:
            return 'medium'
        else:
            return 'low'

    async def observe(self) -> EnvironmentState:
        return EnvironmentState(
            score=self.score,
            description=f"Phase: {self.phase}, Energy: {self._get_energy_hint()}",
            metadata={
                "score": self.score,
                "energy_hint": self._get_energy_hint(),
                "phase": self.phase,
                "action_count": self.action_count
            }
        )

    async def act(self, action: dict | str) -> ActionResult:
        act_type = None
        valid_actions = ['increase', 'decrease', 'reset', 'boost', 'stabilize']

        if isinstance(action, str):
            act_type = action.strip().lower()
        elif isinstance(action, dict):
            # Check direct keys
            for k in ["action", "command", "tool", "act", "type"]:
                v = action.get(k)
                if isinstance(v, str) and v.strip().lower() in valid_actions:
                    act_type = v.strip().lower()
                    break
            # Check nested parameters
            if not act_type and "parameters" in action and isinstance(action["parameters"], dict):
                params = action["parameters"]
                for k in ["action", "command", "tool", "act", "name", "direction"]:
                    v = params.get(k)
                    if isinstance(v, str) and v.strip().lower() in valid_actions:
                        act_type = v.strip().lower()
                        break
                if not act_type:
                    for v in params.values():
                        if isinstance(v, str) and v.strip().lower() in valid_actions:
                            act_type = v.strip().lower()
                            break

        if not act_type or act_type not in valid_actions:
            return ActionResult(
                success=False,
                error=f"Invalid action: '{act_type}'. Valid actions are: {', '.join(valid_actions)}. Example: {{'tool': 'act', 'parameters': {{'action': 'increase'}}}}"
            )

        self.action_count += 1
        if self.action_count % 10 == 0:
            self.energy = max(0, self.energy - 10)

        effect_multiplier = 0.5 if self.energy == 0 else 1.0
        volatile_mod = 1.0
        if self.phase == 'volatile':
            volatile_mod = 1.0 + random.uniform(-0.3, 0.3)

        base_reward = 0.0

        if act_type == 'increase':
            if self.phase == 'critical':
                base_reward = -5 * self.multiplier
            elif self.stability > 30:
                base_reward = 5 * self.multiplier
        elif act_type == 'decrease':
            base_reward = -3
            self.stability = min(100, self.stability + 15)
        elif act_type == 'reset':
            self.stability = 50
            self.multiplier = 1
        elif act_type == 'boost':
            self.multiplier *= 2
            self.stability -= 25
        elif act_type == 'stabilize':
            self.stability = min(100, self.stability + 20)
            base_reward = -2

        final_reward = base_reward * effect_multiplier * volatile_mod
        self.score += final_reward
        self._update_phase()

        return ActionResult(
            success=True,
            output=f"Performed {act_type}",
            reward=final_reward
        )

    async def reset(self) -> EnvironmentState:
        self.do_reset()
        return await self.observe()

    async def is_finished(self) -> bool:
        return self.score >= 100

    def get_available_actions(self) -> list[dict]:
        return [{
            "name": "act",
            "description": "Perform an action in the number game",
            "parameters": {
                "action": "string (increase, decrease, reset, boost, or stabilize)"
            }
        }]
