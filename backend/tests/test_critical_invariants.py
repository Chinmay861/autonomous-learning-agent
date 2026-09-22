"""
Critical tests verifying the core memory invariants and system behavior.
These tests verify the most important architectural requirements.
"""
import pytest
import json
import os
import tempfile
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


# ============================================================================
# TEST 1: Memory retrieval OFF → Agent does NOT query vector memory
# ============================================================================
class TestMemoryRetrievalOff:
    """When retrieval is OFF, no vector queries should be made."""
    
    @pytest.mark.asyncio
    async def test_no_vector_queries_when_retrieval_off(self):
        """Test that memory manager returns None (not empty list) when retrieval is disabled."""
        from app.memory.memory_manager import MemoryManager
        
        # Create mock dependencies
        embedding_service = MagicMock()
        qdrant_store = MagicMock()
        retriever = AsyncMock()
        
        manager = MemoryManager(
            embedding_service=embedding_service,
            qdrant_store=qdrant_store,
            retriever=retriever,
        )
        manager.retrieval_enabled = False
        
        result = await manager.retrieve_relevant_memories(
            task="test task",
            state="test state",
        )
        
        # Should return None (retrieval skipped), NOT an empty list
        assert result is None
        # Retriever should NOT have been called
        retriever.retrieve_for_context.assert_not_called()


# ============================================================================
# TEST 2: Memory retrieval OFF → Agent STILL writes raw learning
# ============================================================================
class TestLearningAlwaysWritten:
    """Learning must always be written regardless of retrieval setting."""
    
    def test_raw_learning_written_regardless_of_retrieval(self):
        """Test that raw learning logger writes every iteration."""
        from app.learning.persistence import RawLearningLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RawLearningLogger(tmpdir, "test-task-001")
            
            # Write 5 iterations
            for i in range(1, 6):
                logger.append_iteration(
                    task_id="test-task-001",
                    iteration=i,
                    observation=f"State at iteration {i}",
                    action=f"Action {i}",
                    actual_result=f"Result {i}",
                    learning=f"Learned something at iteration {i}",
                    task_description="Test task",
                )
            
            # Verify all iterations are in the file
            content = logger.get_content()
            assert "[Iteration 1]" in content
            assert "[Iteration 2]" in content
            assert "[Iteration 3]" in content
            assert "[Iteration 4]" in content
            assert "[Iteration 5]" in content
            assert logger.get_iteration_count() == 5


# ============================================================================
# TEST 3: Memory retrieval OFF → Agent STILL synthesizes and inserts memories
# ============================================================================
class TestSynthesisAlwaysHappens:
    """Synthesis and vector DB insertion must happen regardless of retrieval setting."""
    
    @pytest.mark.asyncio
    async def test_store_learning_always_works(self):
        """Test that store_synthesized_learning works when retrieval is OFF."""
        from app.memory.memory_manager import MemoryManager
        
        embedding_service = MagicMock()
        embedding_service.embed = AsyncMock(return_value=[0.1] * 384)
        
        qdrant_store = MagicMock()
        qdrant_store.find_duplicates = AsyncMock(return_value=[])
        qdrant_store.insert = AsyncMock(return_value=True)
        
        retriever = AsyncMock()
        
        manager = MemoryManager(
            embedding_service=embedding_service,
            qdrant_store=qdrant_store,
            retriever=retriever,
        )
        manager.retrieval_enabled = False  # OFF
        
        # save_learning should ALWAYS be True
        assert manager.save_learning is True
        
        # Storing should work even with retrieval OFF
        learning_id = await manager.store_synthesized_learning(
            learning={
                "title": "Test learning",
                "knowledge": "This is a test",
                "category": "DISCOVERY",
                "confidence": 0.8,
                "generalizable": True,
            },
            task_id="test-task",
        )
        
        assert learning_id is not None
        qdrant_store.insert.assert_called_once()


# ============================================================================
# TEST 4: Memory retrieval ON → Relevant previous memories ARE retrieved
# ============================================================================
class TestMemoryRetrievalOn:
    """When retrieval is ON, relevant memories should be retrieved."""
    
    @pytest.mark.asyncio
    async def test_memories_retrieved_when_enabled(self):
        from app.memory.memory_manager import MemoryManager
        
        embedding_service = MagicMock()
        qdrant_store = MagicMock()
        retriever = AsyncMock()
        retriever.retrieve_for_context = AsyncMock(return_value=[
            {"id": "mem1", "learning": "Previously learned X", "similarity": 0.85},
        ])
        
        manager = MemoryManager(
            embedding_service=embedding_service,
            qdrant_store=qdrant_store,
            retriever=retriever,
        )
        manager.retrieval_enabled = True  # ON
        
        result = await manager.retrieve_relevant_memories(
            task="test task",
            state="test state",
        )
        
        assert result is not None
        assert len(result) == 1
        assert result[0]["similarity"] == 0.85
        retriever.retrieve_for_context.assert_called_once()


# ============================================================================
# TEST 5: Learning is persisted throughout 1000 iterations
# ============================================================================
class TestLongRunPersistence:
    """Learning must be persisted throughout all iterations of a long run."""
    
    def test_1000_iterations_persist(self):
        from app.learning.persistence import RawLearningLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RawLearningLogger(tmpdir, "long-run-task")
            
            # Simulate 1000 iterations
            for i in range(1, 1001):
                logger.append_iteration(
                    task_id="long-run-task",
                    iteration=i,
                    observation=f"State {i}",
                    action=f"Action {i}",
                    actual_result=f"Result {i}",
                    learning=f"Learning {i}",
                    task_description="Long run test",
                )
            
            assert logger.get_iteration_count() == 1000
            
            # Verify file is growing (not truncated/overwritten)
            content = logger.get_content()
            assert "[Iteration 1]" in content
            assert "[Iteration 500]" in content
            assert "[Iteration 1000]" in content


# ============================================================================
# TEST 6: Crash/restart → Agent resumes from checkpoint
# ============================================================================
class TestCheckpointResume:
    """Agent must resume from checkpoint after crash."""
    
    def test_state_save_and_restore(self):
        from app.learning.persistence import FileStorageManager
        from app.agents.orchestrator import AgentState
        
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorageManager(tmpdir)
            
            # Create state at iteration 647
            state = AgentState(
                task_id="crash-test",
                task_description="Test crash recovery",
                iteration=647,
                current_strategy="Testing strategy B",
                task_score=42.5,
                completion_status="running",
            )
            state.action_history = [
                {"iteration": i, "action": f"action_{i}", "success": True}
                for i in range(1, 648)
            ]
            
            # Save checkpoint
            storage.save_state("crash-test", state.to_dict())
            
            # Simulate crash and restore
            loaded = storage.load_state("crash-test")
            assert loaded is not None
            
            restored = AgentState.from_dict(loaded)
            assert restored.iteration == 647
            assert restored.task_description == "Test crash recovery"
            assert restored.current_strategy == "Testing strategy B"
            assert restored.task_score == 42.5
    
    def test_rules_save_and_restore(self):
        from app.learning.persistence import FileStorageManager
        from app.agents.rule_discovery import RuleModel
        
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorageManager(tmpdir)
            
            # Create rule model
            model = RuleModel()
            model.add_rule("Action A increases score", confidence=0.85, evidence="Iter 10", iteration=10)
            model.add_rule("Action B requires condition X", confidence=0.6, evidence="Iter 20", iteration=20)
            model.add_unknown("Hidden state transitions")
            
            # Save
            storage.save_rules("crash-test", model.to_dict())
            
            # Restore
            loaded = storage.load_rules("crash-test")
            assert loaded is not None
            
            restored = RuleModel.from_dict(loaded)
            assert len(restored.rules) >= 2
            assert "Hidden state transitions" in restored.unknowns


# ============================================================================
# TEST 7: Contradiction → Conflicting knowledge handled correctly
# ============================================================================
class TestContradictionHandling:
    """Contradictory rules must not be silently merged."""
    
    def test_contradictory_rules_both_preserved(self):
        from app.agents.rule_discovery import RuleModel
        
        model = RuleModel()
        
        # Add initial rule
        rule1 = model.add_rule(
            "Action X increases score",
            confidence=0.7,
            evidence="Score went up after X",
            iteration=5,
        )
        
        # Contradict it
        model.contradict_rule(
            "Action X increases score",
            evidence="Score went DOWN after X when condition Y existed",
            iteration=15,
        )
        
        # The rule should still exist but with lower confidence
        assert rule1.confidence < 0.7
        assert len(rule1.contradictions) == 1
        
        # Both the original evidence and contradiction should be preserved
        assert len(rule1.evidence) >= 1
        assert len(rule1.contradictions) >= 1
    
    def test_conditional_rule_created(self):
        from app.agents.rule_discovery import RuleModel
        
        model = RuleModel()
        
        # General rule
        model.add_rule("Action X increases score", confidence=0.7, iteration=5)
        
        # Conditional rule (different enough to be separate)
        model.add_rule(
            "Action X decreases score when condition Y is active",
            confidence=0.5,
            iteration=15,
        )
        
        # Both rules should exist
        assert len(model.rules) == 2


# ============================================================================
# TEST 8: Duplicate → Nearly identical learnings are deduplicated
# ============================================================================
class TestDeduplication:
    """Nearly identical learnings should be deduplicated."""
    
    def test_duplicate_rules_merged(self):
        from app.agents.rule_discovery import RuleModel
        
        model = RuleModel()
        
        # Add same rule multiple times
        model.add_rule("Action A causes result B", confidence=0.3, evidence="Iter 1", iteration=1)
        model.add_rule("Action A causes result B", confidence=0.3, evidence="Iter 5", iteration=5)
        model.add_rule("Action A causes result B", confidence=0.3, evidence="Iter 10", iteration=10)
        
        # Should only have one rule, with merged evidence and higher confidence
        matching = [r for r in model.rules if "Action A causes result B" in r.rule_text]
        assert len(matching) == 1
        assert matching[0].confidence > 0.3
        assert matching[0].last_verified_iteration == 10


# ============================================================================
# TEST: Snapshot creation and comparison
# ============================================================================
class TestSnapshots:
    def test_snapshot_creation_and_comparison(self):
        from app.learning.persistence import SnapshotManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(tmpdir, "snapshot-test", interval=100)
            
            # Create snapshot at iteration 100
            manager.create_snapshot(
                iteration=100,
                known_rules=[{"rule": "Rule A", "confidence": 0.6}],
                important_discoveries=["Discovery 1"],
                successful_strategies=["Strategy A"],
                failed_strategies=[],
                remaining_unknowns=["Unknown 1"],
                strategy_summary="Exploring broadly",
                confidence_changes=[],
                score=25.0,
            )
            
            # Create snapshot at iteration 200
            manager.create_snapshot(
                iteration=200,
                known_rules=[
                    {"rule": "Rule A", "confidence": 0.9},
                    {"rule": "Rule B", "confidence": 0.7},
                ],
                important_discoveries=["Discovery 1", "Discovery 2"],
                successful_strategies=["Strategy A", "Strategy B"],
                failed_strategies=["Strategy C"],
                remaining_unknowns=[],
                strategy_summary="Exploiting Strategy B",
                confidence_changes=[],
                score=60.0,
            )
            
            # Compare
            comparison = manager.compare_snapshots(100, 200)
            assert comparison["iteration_a"] == 100
            assert comparison["iteration_b"] == 200
            assert len(comparison["new_rules"]) == 1  # Rule B
            assert comparison["score_change"]["before"] == 25.0
            assert comparison["score_change"]["after"] == 60.0
            assert "Unknown 1" in comparison["resolved_unknowns"]


# ============================================================================
# TEST: The critical save_learning invariant
# ============================================================================
class TestSaveLearningInvariant:
    """Verify that save_learning is ALWAYS True and cannot be changed."""
    
    @pytest.mark.asyncio
    async def test_save_learning_always_true(self):
        from app.memory.memory_manager import MemoryManager
        
        manager = MemoryManager(
            embedding_service=MagicMock(),
            qdrant_store=MagicMock(),
            retriever=AsyncMock(),
        )
        
        # Default should be True
        assert manager.save_learning is True
        
        # Even after changing retrieval setting
        manager.retrieval_enabled = False
        assert manager.save_learning is True
        
        manager.retrieval_enabled = True
        assert manager.save_learning is True


# ============================================================================
# TEST: Stagnation detection
# ============================================================================
class TestStagnationDetection:
    def test_stagnation_detected_on_repeated_actions(self):
        from app.agents.experiment_planner import StagnationMetrics
        
        metrics = StagnationMetrics()
        
        # Repeat the same action
        for _ in range(5):
            metrics.record_action("same_action", "same_result", False, False)
        
        assert metrics.is_stagnant
    
    def test_no_stagnation_with_varied_actions(self):
        from app.agents.experiment_planner import StagnationMetrics
        
        metrics = StagnationMetrics()
        
        for i in range(10):
            metrics.record_action(f"action_{i}", f"result_{i}", True, True)
        
        assert not metrics.is_stagnant
