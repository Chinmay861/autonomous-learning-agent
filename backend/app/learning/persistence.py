"""
Learning Persistence - Raw learning logger, snapshot manager, and file storage.
Ensures learning is ALWAYS written, every iteration, regardless of memory retrieval settings.
"""
import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RawLearningLogger:
    """Writes human-readable learning records to learnings.txt after EVERY iteration.
    
    This logger is ALWAYS active. It does NOT check memory retrieval settings.
    Learning persistence is unconditional.
    """
    
    def __init__(self, storage_dir: str, task_id: str):
        self.task_dir = Path(storage_dir) / "tasks" / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.task_dir / "learnings.txt"
        self._initialized = False
    
    def _ensure_header(self, task_id: str, task_description: str = ""):
        """Write file header if this is a new file."""
        if not self._initialized:
            if not self.filepath.exists():
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.write("=" * 60 + "\n")
                    f.write("TASK LEARNING LOG\n")
                    f.write(f"Task ID: {task_id}\n")
                    if task_description:
                        f.write(f"Task: {task_description}\n")
                    f.write(f"Started: {datetime.utcnow().isoformat()}\n")
                    f.write("=" * 60 + "\n\n")
            self._initialized = True
    
    def append_iteration(
        self,
        task_id: str,
        iteration: int,
        observation: str = "",
        hypothesis: str = "",
        action: str = "",
        expected_result: str = "",
        actual_result: str = "",
        evaluation: str = "",
        mistake: str = "",
        discovery: str = "",
        learning: str = "",
        rule_changes: str = "",
        strategy_change: str = "",
        score: float | None = None,
        task_description: str = "",
    ):
        """Append one iteration's learning to the raw text file.
        
        Called EVERY iteration. NEVER conditional on memory retrieval settings.
        """
        self._ensure_header(task_id, task_description)
        
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(f"[Iteration {iteration}]\n")
            f.write(f"Timestamp: {datetime.utcnow().isoformat()}\n\n")
            
            if observation:
                f.write(f"Observation:\n{observation}\n\n")
            if hypothesis:
                f.write(f"Hypothesis:\n{hypothesis}\n\n")
            if action:
                f.write(f"Action:\n{action}\n\n")
            if expected_result:
                f.write(f"Expected Result:\n{expected_result}\n\n")
            if actual_result:
                f.write(f"Actual Result:\n{actual_result}\n\n")
            if evaluation:
                f.write(f"Evaluation:\n{evaluation}\n\n")
            if mistake:
                f.write(f"Mistake:\n{mistake}\n\n")
            if discovery:
                f.write(f"New Discovery:\n{discovery}\n\n")
            if learning:
                f.write(f"Learning:\n{learning}\n\n")
            if rule_changes:
                f.write(f"Rule Changes:\n{rule_changes}\n\n")
            if strategy_change:
                f.write(f"Strategy Change:\n{strategy_change}\n\n")
            if score is not None:
                f.write(f"Score: {score}\n\n")
            
            f.write("-" * 60 + "\n\n")
    
    def get_content(self) -> str:
        """Read the full learning file content."""
        if self.filepath.exists():
            return self.filepath.read_text(encoding="utf-8")
        return ""
    
    def get_iteration_count(self) -> int:
        """Count how many iterations are logged."""
        content = self.get_content()
        return content.count("[Iteration ")


class SnapshotManager:
    """Creates periodic snapshots of agent state at configured intervals."""
    
    def __init__(self, storage_dir: str, task_id: str, interval: int = 50):
        self.task_dir = Path(storage_dir) / "tasks" / task_id
        self.snapshot_dir = self.task_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
    
    def should_snapshot(self, iteration: int) -> bool:
        """Check if a snapshot should be created at this iteration."""
        return iteration > 0 and iteration % self.interval == 0
    
    def create_snapshot(
        self,
        iteration: int,
        known_rules: list[dict],
        important_discoveries: list[str],
        successful_strategies: list[str],
        failed_strategies: list[str],
        remaining_unknowns: list[str],
        strategy_summary: str,
        confidence_changes: list[dict],
        score: float | None = None,
        additional_data: dict | None = None,
    ) -> str:
        """Create a snapshot file and return the filepath."""
        snapshot = {
            "iteration": iteration,
            "timestamp": datetime.utcnow().isoformat(),
            "known_rules": known_rules,
            "important_discoveries": important_discoveries,
            "successful_strategies": successful_strategies,
            "failed_strategies": failed_strategies,
            "remaining_unknowns": remaining_unknowns,
            "strategy_summary": strategy_summary,
            "confidence_changes": confidence_changes,
            "score": score,
        }
        if additional_data:
            snapshot["additional"] = additional_data
        
        filepath = self.snapshot_dir / f"snapshot_{iteration}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, default=str)
        
        logger.info(f"Created snapshot at iteration {iteration}: {filepath}")
        return str(filepath)
    
    def list_snapshots(self) -> list[dict]:
        """List all available snapshots with basic info."""
        snapshots = []
        for filepath in sorted(self.snapshot_dir.glob("snapshot_*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                snapshots.append({
                    "iteration": data["iteration"],
                    "timestamp": data.get("timestamp", ""),
                    "filepath": str(filepath),
                    "rules_count": len(data.get("known_rules", [])),
                    "discoveries_count": len(data.get("important_discoveries", [])),
                    "score": data.get("score"),
                })
            except Exception as e:
                logger.error(f"Error reading snapshot {filepath}: {e}")
        return snapshots
    
    def get_snapshot(self, iteration: int) -> dict | None:
        """Get a specific snapshot by iteration number."""
        filepath = self.snapshot_dir / f"snapshot_{iteration}.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def compare_snapshots(self, iter_a: int, iter_b: int) -> dict:
        """Compare two snapshots and return the differences."""
        snap_a = self.get_snapshot(iter_a)
        snap_b = self.get_snapshot(iter_b)
        
        if not snap_a or not snap_b:
            return {"error": f"Missing snapshot(s): {iter_a}={'found' if snap_a else 'missing'}, {iter_b}={'found' if snap_b else 'missing'}"}
        
        rules_a = {r.get("rule", ""): r for r in snap_a.get("known_rules", [])}
        rules_b = {r.get("rule", ""): r for r in snap_b.get("known_rules", [])}
        
        new_rules = [r for name, r in rules_b.items() if name not in rules_a]
        removed_rules = [r for name, r in rules_a.items() if name not in rules_b]
        
        confidence_changes = []
        for name in set(rules_a.keys()) & set(rules_b.keys()):
            conf_a = rules_a[name].get("confidence", 0)
            conf_b = rules_b[name].get("confidence", 0)
            if abs(conf_a - conf_b) > 0.05:
                confidence_changes.append({
                    "rule": name,
                    "confidence_before": conf_a,
                    "confidence_after": conf_b,
                    "change": conf_b - conf_a,
                })
        
        strats_a = set(snap_a.get("successful_strategies", []))
        strats_b = set(snap_b.get("successful_strategies", []))
        
        return {
            "iteration_a": iter_a,
            "iteration_b": iter_b,
            "new_rules": new_rules,
            "removed_rules": removed_rules,
            "confidence_changes": confidence_changes,
            "new_strategies": list(strats_b - strats_a),
            "abandoned_strategies": list(strats_a - strats_b),
            "new_unknowns": [
                u for u in snap_b.get("remaining_unknowns", [])
                if u not in snap_a.get("remaining_unknowns", [])
            ],
            "resolved_unknowns": [
                u for u in snap_a.get("remaining_unknowns", [])
                if u not in snap_b.get("remaining_unknowns", [])
            ],
            "score_change": {
                "before": snap_a.get("score"),
                "after": snap_b.get("score"),
            },
        }


class FileStorageManager:
    """Manages the file storage structure for tasks."""
    
    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def get_task_dir(self, task_id: str) -> Path:
        task_dir = self.storage_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir
    
    def save_state(self, task_id: str, state: dict):
        """Save agent state for checkpoint/resume."""
        filepath = self.get_task_dir(task_id) / "state.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
    
    def load_state(self, task_id: str) -> dict | None:
        """Load agent state for resume."""
        filepath = self.get_task_dir(task_id) / "state.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def save_rules(self, task_id: str, rules: dict):
        """Save rule model."""
        filepath = self.get_task_dir(task_id) / "rules.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, default=str)
    
    def load_rules(self, task_id: str) -> dict | None:
        filepath = self.get_task_dir(task_id) / "rules.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def save_history(self, task_id: str, history: list[dict]):
        """Save action history."""
        filepath = self.get_task_dir(task_id) / "history.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)
    
    def load_history(self, task_id: str) -> list[dict]:
        filepath = self.get_task_dir(task_id) / "history.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def get_learnings_path(self, task_id: str) -> str:
        return str(self.get_task_dir(task_id) / "learnings.txt")
    
    def list_tasks(self) -> list[str]:
        """List all task IDs with storage."""
        tasks_dir = self.storage_dir / "tasks"
        if tasks_dir.exists():
            return [d.name for d in tasks_dir.iterdir() if d.is_dir()]
        return []
