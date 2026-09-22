"""
Rule Discovery Engine - Maintains and evolves a dynamic rule model
based on observations from each iteration.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from app.agents.prompts import get_prompt
from app.models.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """A single discovered rule with metadata."""
    rule_text: str
    confidence: float = 0.3
    status: str = "hypothesis"  # unknown, hypothesis, supported, strongly_supported, confirmed, contradicted, rejected
    category: str = "general"
    evidence: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    first_observed_iteration: int = 0
    last_verified_iteration: int = 0
    conditions: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> dict:
        return {
            "rule": self.rule_text,
            "confidence": self.confidence,
            "status": self.status,
            "category": self.category,
            "evidence": self.evidence,
            "contradictions": self.contradictions,
            "first_observed": self.first_observed_iteration,
            "last_verified": self.last_verified_iteration,
            "conditions": self.conditions,
            "exceptions": self.exceptions,
        }
    
    def update_confidence(self, delta: float):
        """Adjust confidence, clamping to [0, 1]."""
        self.confidence = max(0.0, min(1.0, self.confidence + delta))
        self._update_status()
        self.updated_at = datetime.utcnow().isoformat()
    
    def _update_status(self):
        """Update status based on confidence level."""
        if self.confidence >= 0.9:
            self.status = "confirmed"
        elif self.confidence >= 0.75:
            self.status = "strongly_supported"
        elif self.confidence >= 0.5:
            self.status = "supported"
        elif self.confidence >= 0.2:
            self.status = "hypothesis"
        elif self.confidence > 0.0:
            self.status = "contradicted"
        else:
            self.status = "rejected"


class RuleModel:
    """Dynamic rule model maintaining all discovered rules and their states."""
    
    def __init__(self):
        self.rules: list[Rule] = []
        self.unknowns: list[str] = []
        self.constraints: list[str] = []
        self.success_conditions: list[str] = []
        self.failure_conditions: list[str] = []
    
    def add_rule(self, rule_text: str, confidence: float = 0.3,
                 evidence: str = "", iteration: int = 0,
                 category: str = "general") -> Rule:
        """Add a new hypothesized rule."""
        # Check for duplicates
        existing = self.find_similar_rule(rule_text)
        if existing:
            existing.update_confidence(0.1)
            if evidence:
                existing.evidence.append(evidence)
            existing.last_verified_iteration = iteration
            return existing
        
        rule = Rule(
            rule_text=rule_text,
            confidence=confidence,
            evidence=[evidence] if evidence else [],
            first_observed_iteration=iteration,
            last_verified_iteration=iteration,
            category=category,
        )
        self.rules.append(rule)
        return rule
    
    def find_similar_rule(self, rule_text: str) -> Rule | None:
        """Find an existing rule that is similar to the given text."""
        rule_lower = rule_text.lower().strip()
        for rule in self.rules:
            if rule.rule_text.lower().strip() == rule_lower:
                return rule
            # Simple similarity check - shared key words
            words1 = set(rule_lower.split())
            words2 = set(rule.rule_text.lower().strip().split())
            if len(words1) > 3 and len(words2) > 3:
                overlap = len(words1 & words2) / max(len(words1 | words2), 1)
                if overlap > 0.7:
                    return rule
        return None
    
    def confirm_rule(self, rule_text: str, evidence: str, iteration: int):
        """Strengthen confidence in a rule."""
        rule = self.find_similar_rule(rule_text)
        if rule:
            rule.update_confidence(0.15)
            rule.evidence.append(f"Iter {iteration}: {evidence}")
            rule.last_verified_iteration = iteration
        else:
            self.add_rule(rule_text, confidence=0.5, evidence=f"Iter {iteration}: {evidence}", iteration=iteration)
    
    def contradict_rule(self, rule_text: str, evidence: str, iteration: int):
        """Weaken confidence in a rule."""
        rule = self.find_similar_rule(rule_text)
        if rule:
            rule.update_confidence(-0.25)
            rule.contradictions.append(f"Iter {iteration}: {evidence}")
            rule.last_verified_iteration = iteration
    
    def add_unknown(self, unknown: str):
        """Record something we don't know yet."""
        if unknown not in self.unknowns:
            self.unknowns.append(unknown)
    
    def resolve_unknown(self, unknown: str):
        """Mark an unknown as resolved."""
        if unknown in self.unknowns:
            self.unknowns.remove(unknown)
    
    @property
    def known_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.status in ("confirmed", "strongly_supported")]
    
    @property
    def hypothesized_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.status in ("hypothesis", "supported")]
    
    @property
    def rejected_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.status in ("contradicted", "rejected")]
    
    @property
    def active_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.status not in ("rejected",)]
    
    def to_dict(self) -> dict:
        return {
            "known_rules": [r.to_dict() for r in self.known_rules],
            "hypothesized_rules": [r.to_dict() for r in self.hypothesized_rules],
            "confirmed_rules": [r.to_dict() for r in self.rules if r.status == "confirmed"],
            "rejected_rules": [r.to_dict() for r in self.rejected_rules],
            "unknowns": self.unknowns,
            "constraints": self.constraints,
            "success_conditions": self.success_conditions,
            "failure_conditions": self.failure_conditions,
        }
    
    def summary(self) -> str:
        return (
            f"Rules: {len(self.rules)} total | "
            f"{len(self.known_rules)} confirmed | "
            f"{len(self.hypothesized_rules)} hypothesized | "
            f"{len(self.rejected_rules)} rejected | "
            f"{len(self.unknowns)} unknowns"
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> "RuleModel":
        """Restore rule model from dict (for checkpoint resume)."""
        model = cls()
        for rule_list_key in ("known_rules", "hypothesized_rules", "confirmed_rules", "rejected_rules"):
            for rd in data.get(rule_list_key, []):
                existing = model.find_similar_rule(rd["rule"])
                if not existing:
                    rule = Rule(
                        rule_text=rd["rule"],
                        confidence=rd.get("confidence", 0.5),
                        status=rd.get("status", "hypothesis"),
                        evidence=rd.get("evidence", []),
                        first_observed_iteration=rd.get("first_observed", 0),
                        last_verified_iteration=rd.get("last_verified", 0),
                    )
                    model.rules.append(rule)
        model.unknowns = data.get("unknowns", [])
        model.constraints = data.get("constraints", [])
        model.success_conditions = data.get("success_conditions", [])
        model.failure_conditions = data.get("failure_conditions", [])
        return model


class RuleDiscoveryEngine:
    """Uses LLM to analyze observations and update the rule model."""
    
    def __init__(self, llm: LLMProvider, prompt_version: str = "v1"):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = get_prompt("rule_discovery", prompt_version)
    
    async def analyze_observation(
        self,
        rule_model: RuleModel,
        observation: str,
        action: str,
        result: str,
        iteration: int,
        history_summary: str = "",
    ) -> dict:
        """Analyze an observation and update the rule model."""
        user_prompt = f"""Current Known Rules:
{json.dumps([r.to_dict() for r in rule_model.known_rules], indent=2)}

Current Hypothesized Rules:
{json.dumps([r.to_dict() for r in rule_model.hypothesized_rules], indent=2)}

Current Unknowns:
{json.dumps(rule_model.unknowns)}

Recent Observation (Iteration {iteration}):
Action: {action}
Result: {result}
Full Observation: {observation}

History Summary:
{history_summary}

Analyze this observation and determine rule updates."""
        
        try:
            schema = {
                "type": "object",
                "properties": {
                    "confirmed_rules": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rule": {"type": "string"},
                                "evidence": {"type": "string"},
                                "confidence_boost": {"type": "number"},
                            },
                        },
                    },
                    "contradicted_rules": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rule": {"type": "string"},
                                "evidence": {"type": "string"},
                                "confidence_reduction": {"type": "number"},
                            },
                        },
                    },
                    "new_hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rule": {"type": "string"},
                                "evidence": {"type": "string"},
                                "initial_confidence": {"type": "number"},
                            },
                        },
                    },
                    "unknowns_identified": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
            
            analysis = await self.llm.structured_generate(
                prompt=user_prompt,
                schema=schema,
                system=self.system_prompt,
            )
            
            # Apply updates to rule model
            changes = {"confirmed": [], "contradicted": [], "new": [], "unknowns": []}
            
            for conf in analysis.get("confirmed_rules", []):
                rule_model.confirm_rule(conf["rule"], conf["evidence"], iteration)
                changes["confirmed"].append(conf["rule"])
            
            for cont in analysis.get("contradicted_rules", []):
                rule_model.contradict_rule(cont["rule"], cont["evidence"], iteration)
                changes["contradicted"].append(cont["rule"])
            
            for hyp in analysis.get("new_hypotheses", []):
                rule_model.add_rule(
                    hyp["rule"],
                    confidence=hyp.get("initial_confidence", 0.3),
                    evidence=hyp.get("evidence", ""),
                    iteration=iteration,
                )
                changes["new"].append(hyp["rule"])
            
            for unknown in analysis.get("unknowns_identified", []):
                rule_model.add_unknown(unknown)
                changes["unknowns"].append(unknown)
            
            return changes
            
        except Exception as e:
            logger.error(f"Rule discovery analysis failed: {e}")
            return {"confirmed": [], "contradicted": [], "new": [], "unknowns": []}
