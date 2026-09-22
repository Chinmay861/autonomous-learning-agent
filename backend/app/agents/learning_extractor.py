import json
import logging
from typing import Dict, List, Any
from app.models.llm_provider import LLMProvider
from app.agents.prompts import get_prompt

logger = logging.getLogger(__name__)

class LearningExtractor:
    def __init__(self, llm: LLMProvider, prompt_version: str = 'v1'):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt('learning_extractor', prompt_version)

    async def extract_learning(self, task_description: str, state: str, action: dict, result: str, evaluation: dict, previous_learnings: List[str], iteration: int) -> List[dict]:
        prompt = (
            f"Extract learnings from the following episode.\n"
            f"Iteration: {iteration}\n"
            f"Task Description: {task_description}\n"
            f"State: {state}\n"
            f"Action: {json.dumps(action, indent=2)}\n"
            f"Result: {result}\n"
            f"Evaluation: {json.dumps(evaluation, indent=2)}\n"
            f"Previous Learnings: {json.dumps(previous_learnings, indent=2)}\n"
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
                            "learnings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "category": {"type": "string"},
                                        "learning": {"type": "string"},
                                        "evidence": {"type": "string"},
                                        "confidence": {"type": "number"},
                                        "conditions": {"type": "string"},
                                        "quality_score": {"type": "number"}
                                    },
                                    "required": ["category", "learning", "evidence", "confidence", "conditions", "quality_score"]
                                }
                            }
                        },
                        "required": ["learnings"]
                    }
                }
            )
            try:
                data = json.loads(response)
            except Exception:
                from app.models.llm_provider import _repair_and_parse_json
                data = _repair_and_parse_json(response)
                if not isinstance(data, dict):
                    data = {"learnings": data if isinstance(data, list) else []}
            return data.get("learnings", [])
        except Exception as e:
            logger.error(f"Error extracting learnings: {e}")
            return []


class LearningQualityFilter:
    def __init__(self):
        self.seen_learnings = set()

    def filter(self, learnings: List[dict]) -> List[dict]:
        filtered_learnings = []
        for learning in learnings:
            quality = learning.get("quality_score", 0.0)
            text = learning.get("learning", "").lower().strip()
            
            # Basic threshold filtering
            if quality < 0.4:
                continue
                
            # Naive duplicate detection
            if text in self.seen_learnings:
                continue
                
            self.seen_learnings.add(text)
            filtered_learnings.append(learning)
            
        return filtered_learnings
