import json
import logging
from typing import Any, Dict, List, Optional
from app.models.llm_provider import LLMProvider
from app.agents.prompts import get_prompt

logger = logging.getLogger(__name__)

class ResultEvaluator:
    def __init__(self, llm: LLMProvider, prompt_version: str = 'v1'):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt('evaluator', prompt_version)

    async def evaluate(self, action: dict, result: str, hypothesis: str, expected_result: str, environment_state: str, history_summary: str, iteration: int) -> dict:
        prompt = (
            f"Please evaluate the following action and its outcome.\n"
            f"Iteration: {iteration}\n"
            f"Action: {json.dumps(action, indent=2)}\n"
            f"Result: {result}\n"
            f"Hypothesis: {hypothesis}\n"
            f"Expected Result: {expected_result}\n"
            f"Environment State: {environment_state}\n"
            f"History Summary: {history_summary}\n"
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
                            "hypothesis_correct": {"type": "boolean"},
                            "action_useful": {"type": "boolean"},
                            "learned_something": {"type": "boolean"},
                            "should_repeat": {"type": "boolean"},
                            "should_abandon": {"type": "boolean"},
                            "mistake": {"type": "boolean"},
                            "discovery": {"type": "boolean"},
                            "surprise": {"type": "boolean"},
                            "counterfactual": {"type": "string"},
                            "confidence_in_evaluation": {"type": "number"},
                            "success_progress": {"type": "boolean"},
                            "score_change": {"type": "number"}
                        },
                        "required": ["hypothesis_correct", "action_useful", "learned_something", "should_repeat", "should_abandon", "mistake", "discovery", "surprise", "counterfactual", "confidence_in_evaluation", "success_progress", "score_change"]
                    }
                }
            )
            try:
                return json.loads(response)
            except Exception:
                from app.models.llm_provider import _repair_and_parse_json
                repaired = _repair_and_parse_json(response)
                if isinstance(repaired, dict) and repaired:
                    return repaired
                raise
        except Exception as e:
            logger.error(f"Error evaluating result: {e}")
            return {
                "hypothesis_correct": False,
                "action_useful": False,
                "learned_something": False,
                "should_repeat": False,
                "should_abandon": False,
                "mistake": False,
                "discovery": False,
                "surprise": False,
                "counterfactual": "Error in evaluation.",
                "confidence_in_evaluation": 0.0,
                "success_progress": False,
                "score_change": 0.0
            }


class SuccessEvaluator:
    def __init__(self, llm: LLMProvider, prompt_version: str = 'v1'):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt('success_evaluator', prompt_version)

    async def evaluate_success(self, task_description: str, success_criteria: List[str], environment_state: str, current_score: Optional[float], rules_discovered: List[dict], iteration: int, max_iterations: int) -> dict:
        prompt = (
            f"Please evaluate the task completion success.\n"
            f"Task Description: {task_description}\n"
            f"Success Criteria: {json.dumps(success_criteria, indent=2)}\n"
            f"Environment State: {environment_state}\n"
            f"Current Score: {current_score}\n"
            f"Rules Discovered: {json.dumps(rules_discovered, indent=2)}\n"
            f"Iteration: {iteration}/{max_iterations}\n"
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
                            "task_complete": {"type": "boolean"},
                            "confidence": {"type": "number"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "missing_verification": {"type": "array", "items": {"type": "string"}},
                            "partial_progress": {"type": "string"},
                            "completion_percentage": {"type": "integer"}
                        },
                        "required": ["task_complete", "confidence", "evidence", "missing_verification", "partial_progress", "completion_percentage"]
                    }
                }
            )
            try:
                return json.loads(response)
            except Exception:
                from app.models.llm_provider import _repair_and_parse_json
                repaired = _repair_and_parse_json(response)
                if isinstance(repaired, dict) and repaired:
                    return repaired
                raise
        except Exception as e:
            logger.error(f"Error evaluating success: {e}")
            return {
                "task_complete": False,
                "confidence": 0.0,
                "evidence": [],
                "missing_verification": [],
                "partial_progress": "Error evaluating progress.",
                "completion_percentage": 0
            }
