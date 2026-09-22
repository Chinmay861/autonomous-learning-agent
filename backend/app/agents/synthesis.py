import json
import uuid
from typing import Any, Protocol

class LLMProvider(Protocol):
    async def generate_json(self, prompt: str, system_prompt: str = "") -> dict | list:
        ...

# Assume get_prompt exists, providing a fallback implementation if it fails to import
try:
    from app.agents.prompts import get_prompt
except ImportError:
    def get_prompt(name: str, version: str) -> str:
        return f"Synthesize these learnings into maximum {num_target} units."

class LearningSynthesizer:
    def __init__(self, llm: LLMProvider, prompt_version: str = 'v1'):
        self.llm = llm
        self.prompt_version = prompt_version

    async def synthesize(self, raw_learnings: list[dict], task_description: str, task_type: str, num_target: int = 20) -> list[dict]:
        if not raw_learnings:
            return []

        # Group raw learnings by category
        grouped_learnings: dict[str, list[dict]] = {}
        for learning in raw_learnings:
            cat = learning.get('category', 'general')
            if cat not in grouped_learnings:
                grouped_learnings[cat] = []
            grouped_learnings[cat].append(learning)

        synthesized_results = []
        
        system_prompt = get_prompt('synthesis', self.prompt_version)
        if "{" in system_prompt: # basic check to not format if it doesn't need it
            pass

        for category, batch in grouped_learnings.items():
            # Process in batches of ~20
            batch_size = 20
            for i in range(0, len(batch), batch_size):
                current_batch = batch[i:i + batch_size]
                
                prompt = (
                    f"Task Description: {task_description}\n"
                    f"Task Type: {task_type}\n"
                    f"Category: {category}\n"
                    f"Target Number of Synthesis Units: {num_target}\n"
                    f"Raw Learnings:\n{json.dumps(current_batch, indent=2)}\n\n"
                    f"Synthesize the raw learnings into structured knowledge units. Return a JSON list of objects with the following keys: "
                    f"title, knowledge, category, conditions, exceptions, evidence_summary, source_iterations (int), confidence (float 0-1), "
                    f"generalizable (bool), task_type, applicability."
                )
                
                try:
                    response = await self.llm.generate_json(prompt, system_prompt=system_prompt)
                    units = None
                    if isinstance(response, list):
                        units = response
                    elif isinstance(response, dict):
                        # The synthesis system prompt asks for "synthesized_learnings";
                        # older prompt versions used "units". Accept both, plus any list value.
                        for key in ("units", "synthesized_learnings", "learnings", "results"):
                            if isinstance(response.get(key), list):
                                units = response[key]
                                break
                        if units is None:
                            units = next(
                                (v for v in response.values() if isinstance(v, list) and v and isinstance(v[0], dict)),
                                None,
                            )
                    if units:
                        synthesized_results.extend(units)
                except Exception as e:
                    print(f"Failed to synthesize batch: {e}")
                    
        # Handle deduplication within synthesis results
        unique_results = []
        seen_titles = set()
        
        for unit in synthesized_results:
            title = unit.get('title', '').strip().lower()
            if not title:
                continue
            if title not in seen_titles:
                # Some models return source_iterations as a list of iteration numbers;
                # the memory merge path requires an int.
                source_iterations = unit.get('source_iterations', 1)
                if isinstance(source_iterations, list):
                    numbers = [n for n in source_iterations if isinstance(n, (int, float))]
                    source_iterations = int(max(numbers)) if numbers else 1
                elif not isinstance(source_iterations, int):
                    source_iterations = 1

                # Ensure all required fields exist
                clean_unit = {
                    'title': unit.get('title', 'Unknown'),
                    'knowledge': unit.get('knowledge', ''),
                    'category': unit.get('category', category),
                    'conditions': unit.get('conditions', []),
                    'exceptions': unit.get('exceptions', []),
                    'evidence_summary': unit.get('evidence_summary', ''),
                    'source_iterations': source_iterations,
                    'confidence': float(unit.get('confidence', 0.5)),
                    'generalizable': bool(unit.get('generalizable', False)),
                    'task_type': unit.get('task_type', task_type),
                    'applicability': unit.get('applicability', '')
                }
                unique_results.append(clean_unit)
                seen_titles.add(title)
                
        return unique_results
