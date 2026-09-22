"""
Agent Orchestrator - The main agent loop that coordinates all modules.

Implements the core iteration cycle:
Observe -> Hypothesize -> Act -> Evaluate -> Learn -> Update Strategy -> Repeat

CRITICAL INVARIANT: Learning is ALWAYS written. Memory retrieval is user-controlled.
"""
import json
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable
from uuid import uuid4

from app.agents.task_analyzer import TaskAnalyzer, TaskAnalysis
from app.agents.rule_discovery import RuleDiscoveryEngine, RuleModel
from app.agents.experiment_planner import ExperimentPlanner, StagnationMetrics
from app.agents.prompts import get_prompt
from app.environments.base import Environment, EnvironmentState, ActionResult
from app.learning.persistence import RawLearningLogger, SnapshotManager, FileStorageManager
from app.models.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Complete agent state for checkpoint/resume."""
    task_id: str
    task_description: str
    iteration: int = 0
    environment_state: str = ""
    current_strategy: str = "Broad exploration - test available actions to understand the environment"
    current_phase: str = "broad_exploration"
    task_score: float | None = None
    completion_status: str = "running"  # running, paused, completed, failed, stopped
    known_rules: list[dict] = field(default_factory=list)
    hypotheses: list[dict] = field(default_factory=list)
    recent_observations: list[dict] = field(default_factory=list)
    action_history: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    successes: list[str] = field(default_factory=list)
    retrieved_memories: list[dict] = field(default_factory=list)
    prompt_versions: dict = field(default_factory=lambda: {
        "task_analyzer": "v1", "rule_discovery": "v1",
        "experiment_planner": "v1", "evaluator": "v1",
        "learning_extractor": "v1", "strategy_manager": "v1",
        "synthesis": "v1", "success_evaluator": "v1",
    })
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "iteration": self.iteration,
            "environment_state": self.environment_state,
            "current_strategy": self.current_strategy,
            "current_phase": self.current_phase,
            "task_score": self.task_score,
            "completion_status": self.completion_status,
            "known_rules": self.known_rules,
            "hypotheses": self.hypotheses,
            "recent_observations": self.recent_observations[-50:],
            "action_history": self.action_history[-100:],
            "failures": self.failures[-50:],
            "successes": self.successes[-50:],
            "prompt_versions": self.prompt_versions,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Type alias for event callbacks
EventCallback = Callable[[str, dict], Awaitable[None]]


class AgentOrchestrator:
    """
    The main agent loop coordinator.
    
    Manages the complete iteration lifecycle and coordinates all sub-modules.
    Emits events for real-time UI updates.
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        environment: Environment,
        task_id: str,
        task_description: str,
        max_iterations: int = 100,
        use_persistent_learning: bool = False,
        snapshot_interval: int = 50,
        synthesis_interval: int = 100,
        storage_dir: str = "./storage",
        top_k: int = 5,
        min_similarity: float = 0.65,
        memory_manager: Any = None,
        event_callback: EventCallback | None = None,
    ):
        self.llm = llm
        self.environment = environment
        self.task_id = task_id
        self.task_description = task_description
        self.max_iterations = max_iterations
        self.snapshot_interval = snapshot_interval
        self.synthesis_interval = synthesis_interval
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.memory_manager = memory_manager
        self.event_callback = event_callback
        
        # CRITICAL: These are INDEPENDENT settings
        self.retrieval_enabled = use_persistent_learning  # User controlled
        self.save_learning = True  # ALWAYS TRUE. NEVER CHANGES.
        
        # Initialize sub-modules
        self.task_analyzer = TaskAnalyzer(llm)
        self.rule_discovery = RuleDiscoveryEngine(llm)
        self.experiment_planner = ExperimentPlanner(llm)
        
        # These will be imported lazily to avoid circular imports
        self._evaluator = None
        self._learning_extractor = None
        self._strategy_manager = None
        self._synthesizer = None
        self._success_evaluator = None
        
        # State
        self.state = AgentState(task_id=task_id, task_description=task_description)
        self.rule_model = RuleModel()
        self.stagnation = StagnationMetrics()
        self.task_analysis: TaskAnalysis | None = None
        
        # Persistence - ALWAYS active
        self.raw_logger = RawLearningLogger(storage_dir, task_id)
        self.snapshot_manager = SnapshotManager(storage_dir, task_id, snapshot_interval)
        self.file_storage = FileStorageManager(storage_dir)
        
        # Collected learnings for synthesis
        self._accumulated_learnings: list[dict] = []
        
        # Control flags
        self._paused = False
        self._stopped = False
    
    async def _get_evaluator(self):
        if self._evaluator is None:
            from app.agents.evaluator import ResultEvaluator
            self._evaluator = ResultEvaluator(self.llm)
        return self._evaluator
    
    async def _get_success_evaluator(self):
        if self._success_evaluator is None:
            from app.agents.evaluator import SuccessEvaluator
            self._success_evaluator = SuccessEvaluator(self.llm)
        return self._success_evaluator
    
    async def _get_learning_extractor(self):
        if self._learning_extractor is None:
            from app.agents.learning_extractor import LearningExtractor
            self._learning_extractor = LearningExtractor(self.llm)
        return self._learning_extractor
    
    async def _get_strategy_manager(self):
        if self._strategy_manager is None:
            from app.agents.strategy_manager import StrategyManager
            self._strategy_manager = StrategyManager(self.llm)
        return self._strategy_manager
    
    async def _get_synthesizer(self):
        if self._synthesizer is None:
            from app.agents.synthesis import LearningSynthesizer
            self._synthesizer = LearningSynthesizer(self.llm)
        return self._synthesizer
    
    async def emit_event(self, event_type: str, data: dict):
        """Emit an event for real-time UI updates."""
        if self.event_callback:
            try:
                await self.event_callback(event_type, {
                    "task_id": self.task_id,
                    "iteration": self.state.iteration,
                    "timestamp": datetime.utcnow().isoformat(),
                    **data,
                })
            except Exception as e:
                logger.error(f"Error emitting event {event_type}: {e}")
    
    async def run(self) -> AgentState:
        """Execute the main agent loop."""
        logger.info(f"Starting agent run for task {self.task_id}")
        await self.emit_event("task_started", {"max_iterations": self.max_iterations})
        
        try:
            # Phase 1: Analyze the task
            self.task_analysis = await self.task_analyzer.analyze(
                self.task_description,
                available_tools=[{"name": a.get("name", ""), "description": a.get("description", "")}
                                 for a in self.environment.get_available_actions()],
                environment_info=self.environment.description if hasattr(self.environment, 'description') else None,
            )
            await self.emit_event("task_analyzed", {"analysis": self.task_analysis.to_dict()})
            
            # Initialize environment
            initial_state = await self.environment.reset()
            self.state.environment_state = initial_state.description
            
            # Main iteration loop
            task_complete = False
            while not task_complete and self.state.iteration < self.max_iterations:
                # Check control flags
                if self._stopped:
                    self.state.completion_status = "stopped"
                    break
                
                while self._paused:
                    await asyncio.sleep(0.5)
                    if self._stopped:
                        break
                
                if self._stopped:
                    self.state.completion_status = "stopped"
                    break
                
                self.state.iteration += 1
                await self.emit_event("iteration_started", {"iteration": self.state.iteration})
                
                # Execute one iteration
                task_complete = await self._execute_iteration()
                
                # Checkpoint every 10 iterations
                if self.state.iteration % 10 == 0:
                    await self._save_checkpoint()
                
                # Snapshot at configured intervals
                if self.snapshot_manager.should_snapshot(self.state.iteration):
                    await self._create_snapshot()
                
                # Intermediate synthesis at configured intervals
                if self.synthesis_interval > 0 and self.state.iteration % self.synthesis_interval == 0:
                    await self._run_synthesis()
            
            # Final synthesis
            if self._accumulated_learnings:
                await self._run_synthesis()
            
            if task_complete:
                self.state.completion_status = "completed"
                await self.emit_event("task_completed", {
                    "iterations": self.state.iteration,
                    "score": self.state.task_score,
                })
            elif self.state.completion_status == "running":
                self.state.completion_status = "completed"  # Max iterations reached
                await self.emit_event("task_completed", {
                    "iterations": self.state.iteration,
                    "reason": "max_iterations_reached",
                    "score": self.state.task_score,
                })
            
        except Exception as e:
            logger.error(f"Agent run failed: {e}", exc_info=True)
            self.state.completion_status = "failed"
            await self.emit_event("task_failed", {"error": str(e)})
        
        # Final save
        await self._save_checkpoint()
        return self.state
    
    async def _execute_iteration(self) -> bool:
        """Execute a single iteration of the agent loop. Returns True if task is complete."""
        iteration = self.state.iteration
        
        # ================================================================
        # STEP 1: OBSERVE
        # ================================================================
        env_state = await self.environment.observe()
        self.state.environment_state = env_state.description
        if env_state.score is not None:
            self.state.task_score = env_state.score
        
        await self.emit_event("observation", {
            "state": env_state.description,
            "score": env_state.score,
        })
        
        # ================================================================
        # STEP 2: RETRIEVE MEMORIES (if enabled)
        # ================================================================
        retrieved = None
        if self.retrieval_enabled and self.memory_manager:
            retrieved = await self.memory_manager.retrieve_relevant_memories(
                task=self.task_description,
                state=env_state.description,
                top_k=self.top_k,
                min_similarity=self.min_similarity,
            )
            if retrieved:
                self.state.retrieved_memories = retrieved
                await self.emit_event("memories_retrieved", {
                    "count": len(retrieved),
                    "memories": retrieved,
                })
        
        # ================================================================
        # STEP 3: PLAN EXPERIMENT (Hypothesize + Select Action)
        # ================================================================
        experiment = await self.experiment_planner.plan_next_experiment(
            task_description=self.task_description,
            environment_state=env_state.description,
            known_rules=[r.to_dict() for r in self.rule_model.known_rules],
            hypothesized_rules=[r.to_dict() for r in self.rule_model.hypothesized_rules],
            recent_history=self.state.action_history[-15:],
            current_strategy=self.state.current_strategy,
            failed_actions=self.state.failures[-10:],
            retrieved_memories=retrieved,
            stagnation=self.stagnation,
            available_tools=[a for a in self.environment.get_available_actions()],
            iteration=iteration,
        )
        
        await self.emit_event("hypothesis", {
            "mode": experiment.get("mode", "explore"),
            "hypothesis": experiment.get("hypothesis", ""),
            "reasoning": experiment.get("reasoning", ""),
        })
        
        # ================================================================
        # STEP 4: EXECUTE ACTION
        # ================================================================
        action = experiment.get("action", {})
        await self.emit_event("action", {"action": action})
        
        try:
            result = await self.environment.act(action)
        except Exception as e:
            result = ActionResult(
                success=False,
                output="",
                error=str(e),
                state_change="Action execution failed",
                reward=0.0,
            )
        
        await self.emit_event("result", {
            "success": result.success,
            "output": result.output[:500],
            "error": result.error,
            "reward": result.reward,
        })
        
        # ================================================================
        # STEP 5: EVALUATE
        # ================================================================
        evaluator = await self._get_evaluator()
        evaluation = await evaluator.evaluate(
            action=action,
            result=result.output or result.error or "",
            hypothesis=experiment.get("hypothesis", ""),
            expected_result=experiment.get("expected_result", ""),
            environment_state=env_state.description,
            history_summary=self._get_history_summary(),
            iteration=iteration,
        )
        
        await self.emit_event("evaluation", evaluation)
        
        # ================================================================
        # STEP 6: EXTRACT LEARNING (ALWAYS happens)
        # ================================================================
        learning_extractor = await self._get_learning_extractor()
        learnings = await learning_extractor.extract_learning(
            task_description=self.task_description,
            state=env_state.description,
            action=action,
            result=result.output or result.error or "",
            evaluation=evaluation,
            previous_learnings=[l.get("learning", "") for l in self._accumulated_learnings[-20:]],
            iteration=iteration,
        )
        
        for learning in learnings:
            learning["iteration"] = iteration
            learning["task_id"] = self.task_id
            self._accumulated_learnings.append(learning)
            await self.emit_event("learning_created", learning)
        
        # ================================================================
        # STEP 7: WRITE RAW LEARNING (ALWAYS happens - UNCONDITIONAL)
        # ================================================================
        # This is the critical invariant: learning is ALWAYS persisted
        mistake = evaluation.get("mistake", "")
        discovery = evaluation.get("discovery", "")
        learning_text = "; ".join(l.get("learning", "") for l in learnings) if learnings else ""
        
        self.raw_logger.append_iteration(
            task_id=self.task_id,
            iteration=iteration,
            observation=env_state.description,
            hypothesis=experiment.get("hypothesis", ""),
            action=json.dumps(action),
            expected_result=experiment.get("expected_result", ""),
            actual_result=result.output or result.error or "",
            evaluation=json.dumps(evaluation),
            mistake=mistake if mistake else "",
            discovery=discovery if discovery else "",
            learning=learning_text,
            rule_changes="",
            strategy_change="",
            score=env_state.score,
            task_description=self.task_description,
        )
        
        # ================================================================
        # STEP 8: UPDATE RULES (smart conditional execution)
        # ================================================================
        rule_changes = {"new_rules": [], "updated_rules": [], "rejected_rules": []}
        should_check_rules = bool(learnings) or bool(mistake) or bool(discovery) or (iteration % 3 == 0)
        if should_check_rules:
            rule_changes = await self.rule_discovery.analyze_observation(
                rule_model=self.rule_model,
                observation=env_state.description,
                action=json.dumps(action),
                result=result.output or result.error or "",
                iteration=iteration,
                history_summary=self._get_history_summary(),
            )
            if any(rule_changes.values()):
                await self.emit_event("rule_updated", rule_changes)
                self.state.known_rules = [r.to_dict() for r in self.rule_model.known_rules]
                self.state.hypotheses = [r.to_dict() for r in self.rule_model.hypothesized_rules]
        
        # ================================================================
        # STEP 9: UPDATE STRATEGY (smart conditional execution)
        # ================================================================
        should_check_strategy = self.stagnation.is_stagnant or any(rule_changes.values()) or (iteration % 5 == 0)
        if should_check_strategy:
            strategy_mgr = await self._get_strategy_manager()
            strategy_result = await strategy_mgr.evaluate_strategy(
                evaluation_results=[evaluation],
                stagnation_metrics_summary=self.stagnation.summary(),
                known_rules=[r.to_dict() for r in self.rule_model.known_rules],
                discoveries=[l.get("learning", "") for l in learnings if l.get("category") == "DISCOVERY"],
                iteration=iteration,
            )
            if strategy_result.get("change_needed"):
                self.state.current_strategy = strategy_result.get("new_strategy", self.state.current_strategy)
                self.state.current_phase = strategy_result.get("phase", self.state.current_phase)
                await self.emit_event("strategy_changed", strategy_result)
        
        # ================================================================
        # STEP 10: UPDATE HISTORY AND METRICS
        # ================================================================
        history_entry = {
            "iteration": iteration,
            "action": action,
            "result_summary": (result.output or result.error or "")[:200],
            "success": result.success,
            "reward": result.reward,
            "hypothesis": experiment.get("hypothesis", ""),
            "mode": experiment.get("mode", ""),
        }
        self.state.action_history.append(history_entry)
        
        if result.success:
            self.state.successes.append(f"Iter {iteration}: {json.dumps(action)[:100]}")
        else:
            self.state.failures.append(f"Iter {iteration}: {json.dumps(action)[:100]}")
        
        self.stagnation.record_action(
            action=json.dumps(action),
            result=result.output[:100] if result.output else "",
            was_successful=result.success,
            new_learning=bool(learnings),
        )
        
        # Emit iteration_complete event for Live View
        from datetime import datetime, timezone
        iteration_payload = {
            "id": f"{self.task_id}_{iteration}",
            "task_id": self.task_id,
            "iteration_number": iteration,
            "observation": str(env_state.description or ""),
            "hypothesis": str(experiment.get("hypothesis") or experiment.get("reasoning") or ""),
            "action": json.dumps(action, indent=2) if isinstance(action, dict) else str(action),
            "result": str(result.output or result.error or "Action completed"),
            "evaluation": json.dumps(evaluation, indent=2) if isinstance(evaluation, dict) else str(evaluation),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await self.emit_event("iteration_complete", iteration_payload)

        # Persist iteration to database for history/timeline
        try:
            from app.database.connection import async_sessionmaker_db
            from app.database.models import Iteration, Task
            from sqlalchemy import select
            async with async_sessionmaker_db() as session:
                db_iter = Iteration(
                    task_id=self.task_id,
                    iteration_number=iteration,
                    observation=str(env_state.description or ""),
                    hypothesis=str(experiment.get("hypothesis") or ""),
                    action=action if isinstance(action, dict) else {"action": str(action)},
                    action_result=str(result.output or result.error or "Action completed"),
                    evaluation=evaluation if isinstance(evaluation, dict) else {"raw": str(evaluation)},
                    score=env_state.score,
                )
                session.add(db_iter)
                task_res = await session.execute(select(Task).where(Task.id == self.task_id))
                t_row = task_res.scalar_one_or_none()
                if t_row:
                    t_row.current_iteration = iteration
                await session.commit()
        except Exception as e:
            logger.warning(f"Could not persist iteration to DB: {e}")
        
        # ================================================================
        # STEP 11: CHECK SUCCESS
        # ================================================================
        if await self.environment.is_finished():
            return True
        
        # Periodic success evaluation (every 10 iterations)
        if iteration % 10 == 0 and self.task_analysis:
            success_eval = await self._get_success_evaluator()
            success_result = await success_eval.evaluate_success(
                task_description=self.task_description,
                success_criteria=self.task_analysis.success_criteria,
                environment_state=env_state.description,
                current_score=env_state.score,
                rules_discovered=[r.to_dict() for r in self.rule_model.known_rules],
                iteration=iteration,
                max_iterations=self.max_iterations,
            )
            if success_result.get("task_complete") and success_result.get("confidence", 0) >= 0.8:
                return True
        
        return False
    
    def _get_history_summary(self) -> str:
        """Get a brief summary of recent history for context."""
        recent = self.state.action_history[-10:]
        if not recent:
            return "No previous actions."
        
        lines = []
        for h in recent:
            lines.append(
                f"Iter {h['iteration']}: {h.get('mode', '?')} - "
                f"{'✓' if h.get('success') else '✗'} "
                f"(reward: {h.get('reward', 0)})"
            )
        return "\n".join(lines)
    
    async def _save_checkpoint(self):
        """Save state for crash recovery."""
        self.file_storage.save_state(self.task_id, self.state.to_dict())
        self.file_storage.save_rules(self.task_id, self.rule_model.to_dict())
        self.file_storage.save_history(self.task_id, self.state.action_history)
    
    async def _create_snapshot(self):
        """Create a learning snapshot."""
        filepath = self.snapshot_manager.create_snapshot(
            iteration=self.state.iteration,
            known_rules=[r.to_dict() for r in self.rule_model.known_rules],
            important_discoveries=[
                l.get("learning", "")
                for l in self._accumulated_learnings
                if l.get("category") == "DISCOVERY"
            ][-20:],
            successful_strategies=[
                l.get("learning", "")
                for l in self._accumulated_learnings
                if l.get("category") == "SUCCESSFUL_STRATEGY"
            ][-10:],
            failed_strategies=[
                l.get("learning", "")
                for l in self._accumulated_learnings
                if l.get("category") == "FAILED_STRATEGY"
            ][-10:],
            remaining_unknowns=self.rule_model.unknowns,
            strategy_summary=self.state.current_strategy,
            confidence_changes=[],
            score=self.state.task_score,
        )
        await self.emit_event("snapshot_created", {
            "iteration": self.state.iteration,
            "filepath": filepath,
        })
    
    async def _run_synthesis(self):
        """Run learning synthesis and store in vector memory."""
        if not self._accumulated_learnings:
            return
        
        synthesizer = await self._get_synthesizer()
        synthesized = await synthesizer.synthesize(
            raw_learnings=self._accumulated_learnings,
            task_description=self.task_description,
            task_type=self.task_analysis.task_type if self.task_analysis else "general",
        )
        
        # Store in vector memory - ALWAYS, regardless of retrieval_enabled
        if self.memory_manager and synthesized:
            stored_ids = await self.memory_manager.store_batch(synthesized, self.task_id)
            logger.info(f"Stored {len(stored_ids)} synthesized learnings in vector memory")
            await self.emit_event("synthesis_completed", {
                "count": len(synthesized),
                "stored": len(stored_ids),
            })
        
        # Clear accumulated learnings that have been synthesized
        self._accumulated_learnings = []
    
    # ================================================================
    # CONTROL METHODS
    # ================================================================
    
    def pause(self):
        """Pause the agent loop."""
        self._paused = True
        self.state.completion_status = "paused"
        logger.info(f"Agent {self.task_id} paused at iteration {self.state.iteration}")
    
    def resume(self):
        """Resume the agent loop."""
        self._paused = False
        self.state.completion_status = "running"
        logger.info(f"Agent {self.task_id} resumed at iteration {self.state.iteration}")
    
    def stop(self):
        """Stop the agent loop."""
        self._stopped = True
        logger.info(f"Agent {self.task_id} stopped at iteration {self.state.iteration}")
    
    @classmethod
    async def resume_from_checkpoint(
        cls,
        llm: LLMProvider,
        environment: Environment,
        storage_dir: str,
        task_id: str,
        **kwargs,
    ) -> "AgentOrchestrator":
        """Create an orchestrator that resumes from a saved checkpoint."""
        file_storage = FileStorageManager(storage_dir)
        saved_state = file_storage.load_state(task_id)
        
        if not saved_state:
            raise ValueError(f"No checkpoint found for task {task_id}")
        
        state = AgentState.from_dict(saved_state)
        
        orchestrator = cls(
            llm=llm,
            environment=environment,
            task_id=task_id,
            task_description=state.task_description,
            storage_dir=storage_dir,
            **kwargs,
        )
        orchestrator.state = state
        
        # Restore rule model
        saved_rules = file_storage.load_rules(task_id)
        if saved_rules:
            orchestrator.rule_model = RuleModel.from_dict(saved_rules)
        
        # Restore history
        history = file_storage.load_history(task_id)
        if history:
            orchestrator.state.action_history = history
        
        logger.info(f"Resumed agent from checkpoint at iteration {state.iteration}")
        return orchestrator
