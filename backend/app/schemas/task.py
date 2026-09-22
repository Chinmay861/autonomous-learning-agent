from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.database.models import TaskStatus, RuleCategory, RuleStatus, LearningCategory

class TaskCreate(BaseModel):
    title: str = "Untitled Task"
    description: str
    max_iterations: int = 100
    snapshot_interval: int = 50
    synthesis_interval: int = 100
    use_persistent_learning: Optional[bool] = None
    persistent_learning: Optional[bool] = None
    top_k: int = 5
    min_similarity: float = 0.65
    model: str = "phi3:mini"
    temperature: float = 0.7
    tools: List[str] = []

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    use_persistent_learning: Optional[bool] = None
    persistent_learning: Optional[bool] = None

class TaskResponse(BaseModel):
    id: str
    user_id: int
    title: str
    description: str
    max_iterations: int
    snapshot_interval: int
    synthesis_interval: int
    use_persistent_learning: bool
    persistent_learning: bool = False
    top_k: int
    min_similarity: float
    model: str
    temperature: float
    status: TaskStatus
    current_iteration: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def sync_learning_fields(self):
        self.persistent_learning = self.use_persistent_learning
        return self

class IterationResponse(BaseModel):
    id: int
    task_id: str
    run_id: int
    iteration_number: int
    observation: Optional[str]
    hypothesis: Optional[str]
    action: Optional[Dict[str, Any]]
    action_result: Optional[str]
    evaluation: Optional[Dict[str, Any]]
    learning: Optional[Dict[str, Any]]
    mistake: Optional[str]
    discovery: Optional[str]
    strategy_change: Optional[str]
    rule_changes: Optional[Dict[str, Any]]
    score: Optional[float]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class RuleResponse(BaseModel):
    id: int
    task_id: str
    rule_text: str
    category: RuleCategory
    confidence: float
    status: RuleStatus
    evidence: List[Dict[str, Any]]
    first_observed_iteration: int
    last_verified_iteration: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LearningResponse(BaseModel):
    id: int
    task_id: str
    iteration_number: int
    category: LearningCategory
    observation: Optional[str]
    action: Optional[Dict[str, Any]]
    expected_result: Optional[str]
    actual_result: Optional[str]
    mistake: Optional[str]
    discovery: Optional[str]
    learning: Optional[Dict[str, Any]]
    rule_change: Optional[str]
    strategy_change: Optional[str]
    confidence: float
    quality_score: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SnapshotResponse(BaseModel):
    id: int
    task_id: str
    iteration_number: int
    known_rules: Optional[Dict[str, Any]]
    important_discoveries: Optional[Dict[str, Any]]
    successful_strategies: Optional[Dict[str, Any]]
    failed_strategies: Optional[Dict[str, Any]]
    remaining_unknowns: Optional[Dict[str, Any]]
    strategy_summary: Optional[Dict[str, Any]]
    confidence_changes: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class StrategyResponse(BaseModel):
    id: int
    task_id: str
    strategy_text: str
    phase_start: int
    phase_end: Optional[int]
    reason_for_change: Optional[str]
    evidence: Optional[Dict[str, Any]]
    is_current: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
