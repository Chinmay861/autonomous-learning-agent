"""
Task Analyzer Agent Module - Analyzes user tasks to determine requirements, 
success criteria, known/unknown information, and constraints.
"""
import json
import logging
from typing import Any

from app.agents.prompts import get_prompt
from app.models.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class TaskAnalysis:
    """Structured result of task analysis."""
    
    def __init__(self, data: dict):
        self.requirements: list[str] = data.get("requirements", [])
        self.success_criteria: list[str] = data.get("success_criteria", [])
        self.known_info: list[str] = data.get("known_info", [])
        self.unknown_info: list[str] = data.get("unknown_info", [])
        self.constraints: list[str] = data.get("constraints", [])
        self.available_actions: list[str] = data.get("available_actions", [])
        self.expected_challenges: list[str] = data.get("expected_challenges", [])
        self.task_type: str = data.get("task_type", "general")
        self.estimated_complexity: str = data.get("estimated_complexity", "medium")
    
    def to_dict(self) -> dict:
        return {
            "requirements": self.requirements,
            "success_criteria": self.success_criteria,
            "known_info": self.known_info,
            "unknown_info": self.unknown_info,
            "constraints": self.constraints,
            "available_actions": self.available_actions,
            "expected_challenges": self.expected_challenges,
            "task_type": self.task_type,
            "estimated_complexity": self.estimated_complexity,
        }
    
    def summary(self) -> str:
        return (
            f"Task Type: {self.task_type} | Complexity: {self.estimated_complexity}\n"
            f"Requirements: {len(self.requirements)} | Unknowns: {len(self.unknown_info)}\n"
            f"Constraints: {len(self.constraints)} | Available Actions: {len(self.available_actions)}"
        )


class TaskAnalyzer:
    """Analyzes a user task to produce structured understanding."""
    
    def __init__(self, llm: LLMProvider, prompt_version: str = "v1"):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt("task_analyzer", prompt_version)
    
    async def analyze(
        self,
        task_description: str,
        available_tools: list[dict] | None = None,
        environment_info: str | None = None,
    ) -> TaskAnalysis:
        """Analyze a task and return structured understanding."""
        user_prompt = f"Task Description:\n{task_description}\n"
        
        if available_tools:
            tool_desc = "\n".join(
                f"- {t['name']}: {t.get('description', 'No description')}"
                for t in available_tools
            )
            user_prompt += f"\nAvailable Tools:\n{tool_desc}\n"
        
        if environment_info:
            user_prompt += f"\nEnvironment Information:\n{environment_info}\n"
        
        user_prompt += "\nAnalyze this task and provide the structured analysis."
        
        try:
            schema = {
                "type": "object",
                "properties": {
                    "requirements": {"type": "array", "items": {"type": "string"}},
                    "success_criteria": {"type": "array", "items": {"type": "string"}},
                    "known_info": {"type": "array", "items": {"type": "string"}},
                    "unknown_info": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                    "available_actions": {"type": "array", "items": {"type": "string"}},
                    "expected_challenges": {"type": "array", "items": {"type": "string"}},
                    "task_type": {"type": "string"},
                    "estimated_complexity": {"type": "string"},
                },
                "required": ["requirements", "success_criteria", "task_type"],
            }
            
            result = await self.llm.structured_generate(
                prompt=user_prompt,
                schema=schema,
                system=self.system_prompt,
            )
            return TaskAnalysis(result)
            
        except Exception as e:
            logger.error(f"Task analysis failed: {e}")
            # Fallback: return minimal analysis
            return TaskAnalysis({
                "requirements": [task_description],
                "success_criteria": ["Task completed successfully"],
                "known_info": [],
                "unknown_info": ["Most aspects of the task"],
                "constraints": [],
                "available_actions": [],
                "expected_challenges": ["Understanding the task requirements"],
                "task_type": "general",
                "estimated_complexity": "medium",
            })
