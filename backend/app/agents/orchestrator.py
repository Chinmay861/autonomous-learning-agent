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
    
    def _quota_error(self) -> str | None:
        """Return the provider's quota-exhaustion message, if any."""
        return getattr(self.llm, "quota_exhausted", None)

    async def _abort_for_quota(self, message: str) -> AgentState:
        """Abort the run cleanly when the LLM quota is exhausted."""
        logger.error(f"Aborting task {self.task_id}: LLM quota exhausted.")
        self.state.completion_status = "failed"
        await self.emit_event("task_failed", {
            "error": f"LLM quota exhausted, run aborted. {message[:300]}",
        })
        await self._save_checkpoint()
        return self.state

    async def run(self) -> AgentState:
        """Execute the main agent loop."""
        logger.info(f"Starting agent run for task {self.task_id}")
        await self.emit_event("task_started", {"max_iterations": self.max_iterations})

        # Preflight: fail fast when the LLM credentials are rejected, instead of
        # burning the whole iteration budget on fallbacks that learn nothing.
        try:
            await self.llm.list_models()
        except Exception as e:
            message = str(e)
            if any(signal in message for signal in (
                "401", "403", "Unauthorized", "unauthorized",
                "invalid_api_key", "expired_api_key", "Invalid API Key",
            )):
                logger.error(f"LLM authentication failed, aborting task {self.task_id}: {message[:200]}")
                self.state.completion_status = "failed"
                await self.emit_event("task_failed", {
                    "error": "LLM authentication failed (401 Unauthorized). "
                             "The configured API key is invalid or expired.",
                })
                await self._save_checkpoint()
                return self.state
            logger.warning(f"LLM preflight check failed, continuing anyway: {message[:200]}")

        try:
            # Phase 1: Analyze the task
            self.task_analysis = await self.task_analyzer.analyze(
                self.task_description,
                available_tools=[{"name": a.get("name", ""), "description": a.get("description", "")}
                                 for a in self.environment.get_available_actions()],
                environment_info=self.environment.description if hasattr(self.environment, 'description') else None,
            )
            await self.emit_event("task_analyzed", {"analysis": self.task_analysis.to_dict()})

            quota_error = self._quota_error()
            if quota_error:
                return await self._abort_for_quota(quota_error)

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

                quota_error = self._quota_error()
                if quota_error:
                    return await self._abort_for_quota(quota_error)

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
        # Retrieval is best-effort: a failure here (missing embedding token,
        # unreachable vector store, cold model) must never abort the run.
        retrieved = None
        if self.retrieval_enabled and self.memory_manager:
            try:
                retrieved = await self.memory_manager.retrieve_relevant_memories(
                    task=self.task_description,
                    state=env_state.description,
                    top_k=self.top_k,
                    min_similarity=self.min_similarity,
                )
            except Exception as e:
                logger.warning(f"Memory retrieval failed, continuing without memories: {e}")
                retrieved = None
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
            loop_warning=self._loop_warning(),
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
                # Persist the rule model to the database so the rules tab
                # survives restarts and does not depend on ephemeral files.
                try:
                    from app.database.connection import async_sessionmaker_db as _rule_session_factory
                    from app.database.models import Rule as DBRule
                    from app.database.models import RuleCategory as DBRuleCategory
                    from app.database.models import RuleStatus as DBRuleStatus
                    from sqlalchemy import select as _select

                    def _rule_status(value: str):
                        name = str(value or "").upper()
                        if name == "HYPOTHESIZED":
                            name = "HYPOTHESIS"
                        return DBRuleStatus.__members__.get(name, DBRuleStatus.HYPOTHESIS)

                    def _rule_category(value: str):
                        name = str(value or "").lower()
                        if name == "constraint":
                            return DBRuleCategory.CONSTRAINT
                        if name == "fact":
                            return DBRuleCategory.FACT
                        if name == "pattern":
                            return DBRuleCategory.PATTERN
                        return DBRuleCategory.HEURISTIC

                    async with _rule_session_factory() as rule_session:
                        for model_rule in self.rule_model.rules:
                            existing = await rule_session.execute(
                                _select(DBRule).where(
                                    DBRule.task_id == self.task_id,
                                    DBRule.rule_text == model_rule.rule_text,
                                )
                            )
                            row = existing.scalar_one_or_none()
                            evidence = [
                                {"text": str(item)}
                                for item in (model_rule.evidence or [])
                                if str(item).strip()
                            ]
                            if row is None:
                                row = DBRule(
                                    task_id=self.task_id,
                                    rule_text=model_rule.rule_text,
                                    category=_rule_category(model_rule.category),
                                    confidence=float(model_rule.confidence or 0.0),
                                    status=_rule_status(model_rule.status),
                                    evidence=evidence,
                                    first_observed_iteration=model_rule.first_observed_iteration or iteration,
                                    last_verified_iteration=model_rule.last_verified_iteration or iteration,
                                )
                                rule_session.add(row)
                            else:
                                row.confidence = float(model_rule.confidence or 0.0)
                                row.status = _rule_status(model_rule.status)
                                row.evidence = evidence
                                row.last_verified_iteration = model_rule.last_verified_iteration or iteration
                        await rule_session.commit()
                except Exception as e:
                    logger.warning(f"Could not persist rules to DB: {e}")
        
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
            from app.database.models import Iteration, LearningRecord, Task
            from app.database.models import LearningCategory as DBLearningCategory
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
                # Persist extracted learnings so the timeline/learnings tabs
                # survive restarts and do not depend on ephemeral log files.
                for learning in learnings:
                    if not isinstance(learning, dict):
                        learning = {"learning": str(learning)}
                    try:
                        confidence = float(learning.get("confidence", 0.5))
                    except (TypeError, ValueError):
                        confidence = 0.5
                    try:
                        quality_score = float(learning.get("quality_score", 0.5))
                    except (TypeError, ValueError):
                        quality_score = 0.5
                    category_name = str(learning.get("category", "OBSERVATION") or "OBSERVATION").upper()
                    if category_name not in DBLearningCategory.__members__:
                        category_name = "OBSERVATION"
                    session.add(LearningRecord(
                        task_id=self.task_id,
                        iteration_number=iteration,
                        category=DBLearningCategory[category_name],
                        observation=str(env_state.description or ""),
                        action=action if isinstance(action, dict) else {"action": str(action)},
                        expected_result=str(experiment.get("expected_result", "") or ""),
                        actual_result=str(result.output or result.error or ""),
                        mistake=mistake or None,
                        discovery=discovery or None,
                        learning=learning,
                        confidence=confidence,
                        quality_score=quality_score,
                    ))
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
    
    def _loop_warning(self, window: int = 4) -> str:
        """Detect tight request loops (equivalent consecutive actions).

        Open-ended tasks have no natural end state, so an agent can burn the
        whole iteration budget re-issuing equivalent requests (same tool,
        method and host). When the recent history shows such a loop, return a
        directive for the planner; otherwise return "".
        """
        # Only HTTP-style tasks loop this way; grid/maze agents legitimately
        # repeat moves (e.g. walking a straight corridor).
        from app.environments.http_env import HTTPEnvironment
        if not isinstance(self.environment, HTTPEnvironment):
            return ""
        from urllib.parse import urlparse

        def _signature(action: Any) -> str | None:
            if not isinstance(action, dict):
                return None
            params = action.get("parameters")
            if not isinstance(params, dict):
                params = action.get("arguments")
            if not isinstance(params, dict):
                params = action.get("args")
            merged = dict(action)
            if isinstance(params, dict):
                for key, value in params.items():
                    merged.setdefault(key, value)
            tool = str(merged.get("tool") or merged.get("name") or "").lower()
            method = str(merged.get("method") or "").upper()
            url = merged.get("url") or ""
            host = ""
            if isinstance(url, str) and url:
                try:
                    host = urlparse(url).netloc.lower() or url.lower()
                except Exception:
                    host = str(url).lower()
            direction = str(merged.get("direction") or "").lower()
            signature = "|".join(part for part in (tool, method, host, direction) if part)
            return signature or None

        recent = [
            signature
            for entry in self.state.action_history[-window:]
            if (signature := _signature(entry.get("action")))
        ]
        if len(recent) >= window and len(set(recent)) == 1:
            return (
                f"Loop warning: your last {len(recent)} actions were equivalent "
                f"({recent[-1]}). Do not repeat this request. Either advance the task "
                "goal with a different action, or state what is blocking completion."
            )
        return ""

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
            logger.info(f"[Synthesis] No accumulated learnings to synthesize for task {self.task_id}")
            return
        
        logger.info(f"[Synthesis] Starting synthesis of {len(self._accumulated_learnings)} accumulated learnings for task {self.task_id}")
        
        try:
            synthesizer = await self._get_synthesizer()
            synthesized = await synthesizer.synthesize(
                raw_learnings=self._accumulated_learnings,
                task_description=self.task_description,
                task_type=self.task_analysis.task_type if self.task_analysis else "general",
            )
        except Exception as e:
            logger.error(f"[Synthesis] LLM synthesis call failed for task {self.task_id}: {e}", exc_info=True)
            await self.emit_event("synthesis_failed", {
                "error": f"Synthesis LLM call failed: {str(e)[:200]}",
                "accumulated_count": len(self._accumulated_learnings),
            })
            # Keep learnings for next attempt
            self._accumulated_learnings = self._accumulated_learnings[-200:]
            return
        
        if not synthesized:
            logger.warning(f"[Synthesis] LLM returned 0 synthesized units for task {self.task_id} (from {len(self._accumulated_learnings)} raw learnings)")
            await self.emit_event("synthesis_failed", {
                "error": "LLM returned 0 synthesized units",
                "accumulated_count": len(self._accumulated_learnings),
            })
            # Clear anyway to avoid re-synthesizing stale learnings forever
            self._accumulated_learnings = []
            return
        
        logger.info(f"[Synthesis] LLM produced {len(synthesized)} units, now storing in vector memory...")
        
        # Store in vector memory - ALWAYS, regardless of retrieval_enabled.
        # A storage failure must never abort the run: on failure the learnings
        # are retained (trimmed) for the next synthesis attempt.
        if self.memory_manager:
            try:
                stored_ids = await self.memory_manager.store_batch(synthesized, self.task_id)
            except Exception as e:
                logger.error(f"[Synthesis] Vector storage failed for task {self.task_id}: {e}", exc_info=True)
                await self.emit_event("synthesis_failed", {
                    "error": f"Vector storage failed: {str(e)[:200]}",
                    "synthesized_count": len(synthesized),
                })
                self._accumulated_learnings = self._accumulated_learnings[-200:]
                return
            logger.info(f"[Synthesis] ✓ Stored {len(stored_ids)} synthesized learnings in vector memory for task {self.task_id}")
            await self.emit_event("synthesis_completed", {
                "count": len(synthesized),
                "stored": len(stored_ids),
            })
        else:
            logger.warning(f"[Synthesis] No memory_manager available — {len(synthesized)} synthesized units were NOT stored!")
            await self.emit_event("synthesis_failed", {
                "error": "No memory manager available",
                "synthesized_count": len(synthesized),
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
