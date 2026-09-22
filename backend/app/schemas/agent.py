from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from enum import Enum
from app.database.models import LearningCategory

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class HypothesisOutput(BaseModel):
    hypothesis: str
    reasoning_summary: str
    confidence: float = Field(ge=0.0, le=1.0)

class ActionOutput(BaseModel):
    tool: str
    parameters: Dict[str, Any]
    reason: str
    hypothesis: str
    expected_result: str
    risk: RiskLevel

class EvaluationOutput(BaseModel):
    expected_result: str
    actual_result: str
    hypothesis_correct: bool
    action_useful: bool
    learned_something: bool
    should_repeat: bool
    should_abandon: bool
    mistake: Optional[str] = None
    discovery: Optional[str] = None
    learning: Optional[Dict[str, Any]] = None

class LearningOutput(BaseModel):
    category: LearningCategory
    observation: str
    action: Dict[str, Any]
    expected_result: str
    actual_result: str
    mistake: Optional[str] = None
    discovery: Optional[str] = None
    learning: Optional[Dict[str, Any]] = None
    rule_change: Optional[str] = None
    strategy_change: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)

class SynthesisOutput(BaseModel):
    title: str
    knowledge: str
    category: str
    conditions: List[str]
    evidence: List[str]
    exceptions: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    applicability: str
    generalizable: bool
    task_type: str
