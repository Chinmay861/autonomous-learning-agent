import uuid
import enum
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text, JSON, DateTime, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class TaskStatus(str, enum.Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"

class RuleCategory(str, enum.Enum):
    HEURISTIC = "HEURISTIC"
    CONSTRAINT = "CONSTRAINT"
    FACT = "FACT"
    PATTERN = "PATTERN"

class RuleStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    HYPOTHESIS = "HYPOTHESIS"
    SUPPORTED = "SUPPORTED"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"

class LearningCategory(str, enum.Enum):
    MISTAKE = "MISTAKE"
    DISCOVERY = "DISCOVERY"
    RULE = "RULE"
    CONSTRAINT = "CONSTRAINT"
    SUCCESSFUL_STRATEGY = "SUCCESSFUL_STRATEGY"
    FAILED_STRATEGY = "FAILED_STRATEGY"
    OBSERVATION = "OBSERVATION"
    CAUSE_EFFECT = "CAUSE_EFFECT"
    OPTIMIZATION = "OPTIMIZATION"
    RECOVERY = "RECOVERY"
    GENERALIZATION = "GENERALIZATION"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    settings: Mapped[List["Setting"]] = relationship("Setting", back_populates="user", cascade="all, delete-orphan")

def generate_uuid() -> str:
    return str(uuid.uuid4())

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    max_iterations: Mapped[int] = mapped_column(Integer)
    snapshot_interval: Mapped[int] = mapped_column(Integer)
    synthesis_interval: Mapped[int] = mapped_column(Integer)
    use_persistent_learning: Mapped[bool] = mapped_column(Boolean)
    top_k: Mapped[int] = mapped_column(Integer)
    min_similarity: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(50))
    temperature: Mapped[float] = mapped_column(Float)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), default=TaskStatus.CREATED)
    current_iteration: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    @property
    def persistent_learning(self) -> bool:
        return bool(self.use_persistent_learning)

    @persistent_learning.setter
    def persistent_learning(self, value: bool):
        self.use_persistent_learning = bool(value)
    
    user: Mapped["User"] = relationship("User", back_populates="tasks")
    agent_runs: Mapped[List["AgentRun"]] = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")
    iterations: Mapped[List["Iteration"]] = relationship("Iteration", back_populates="task", cascade="all, delete-orphan")
    rules: Mapped[List["Rule"]] = relationship("Rule", back_populates="task", cascade="all, delete-orphan")
    learning_records: Mapped[List["LearningRecord"]] = relationship("LearningRecord", back_populates="task", cascade="all, delete-orphan")
    snapshots: Mapped[List["Snapshot"]] = relationship("Snapshot", back_populates="task", cascade="all, delete-orphan")
    strategies: Mapped[List["Strategy"]] = relationship("Strategy", back_populates="task", cascade="all, delete-orphan")
    synthesized_learnings: Mapped[List["SynthesizedLearning"]] = relationship("SynthesizedLearning", back_populates="task", cascade="all, delete-orphan")

class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    run_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_iterations: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint_iteration: Mapped[int] = mapped_column(Integer, default=0)
    
    task: Mapped["Task"] = relationship("Task", back_populates="agent_runs")
    iterations: Mapped[List["Iteration"]] = relationship("Iteration", back_populates="run")

class Iteration(Base):
    __tablename__ = "iterations"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    iteration_number: Mapped[int] = mapped_column(Integer)
    observation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    action_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluation: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    learning: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    mistake: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discovery: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_change: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="iterations")
    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="iterations")

class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    rule_text: Mapped[str] = mapped_column(Text)
    category: Mapped[RuleCategory] = mapped_column(SQLEnum(RuleCategory))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[RuleStatus] = mapped_column(SQLEnum(RuleStatus))
    evidence: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    first_observed_iteration: Mapped[int] = mapped_column(Integer)
    last_verified_iteration: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="rules")

class LearningRecord(Base):
    __tablename__ = "learning_records"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    iteration_number: Mapped[int] = mapped_column(Integer)
    category: Mapped[LearningCategory] = mapped_column(SQLEnum(LearningCategory))
    observation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    expected_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mistake: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discovery: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    learning: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    rule_change: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_change: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    quality_score: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="learning_records")

class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    iteration_number: Mapped[int] = mapped_column(Integer)
    known_rules: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    important_discoveries: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    successful_strategies: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    failed_strategies: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    remaining_unknowns: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    strategy_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    confidence_changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="snapshots")

class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    strategy_text: Mapped[str] = mapped_column(Text)
    phase_start: Mapped[int] = mapped_column(Integer)
    phase_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason_for_change: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="strategies")

class SynthesizedLearning(Base):
    __tablename__ = "synthesized_learnings"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(255))
    knowledge: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    conditions: Mapped[List[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[List[str]] = mapped_column(JSON, default=list)
    exceptions: Mapped[List[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    applicability: Mapped[str] = mapped_column(Text)
    source_iterations: Mapped[List[int]] = mapped_column(JSON, default=list)
    task_type: Mapped[str] = mapped_column(String(100))
    generalizable: Mapped[bool] = mapped_column(Boolean, default=False)
    vector_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    task: Mapped["Task"] = relationship("Task", back_populates="synthesized_learnings")

class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    user: Mapped["User"] = relationship("User", back_populates="settings")
