"""
Skill Analyst Agent
Boundary: Evaluates self-reported skills against assessment records to determine effective proficiencies.
Input: {"skills": [{"skill": str, "claimed_level": str, "validated_level": Optional[str]}], "assessments": [...]}
Output: {"strong": [str], "weak": [str], "levels": {str: str}}
"""

from typing import Any, Dict, List
from agents.base import BaseAgent


class SkillAnalyst(BaseAgent):
    def __init__(self):
        super().__init__(name="Skill Analyst")

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        learner_skills = input_dict.get("skills", [])
        recent_assessments = input_dict.get("assessments", [])

        # Map latest assessment scores by skill
        latest_assessment_scores: Dict[str, float] = {}
        for a in recent_assessments:
            skill = a.get("skill")
            score = a.get("score", 0.0)
            latest_assessment_scores[skill] = score

        levels: Dict[str, str] = {}
        strong: List[str] = []
        weak: List[str] = []

        for s in learner_skills:
            skill_name = s.get("skill")
            claimed = s.get("claimed_level", "Beginner")
            validated = s.get("validated_level")

            effective_level = validated if validated else claimed
            levels[skill_name] = effective_level

            # If there's a recent failing assessment (< 50), mark as weak
            score = latest_assessment_scores.get(skill_name)
            if score is not None and score < 50:
                weak.append(skill_name)
            elif effective_level == "Beginner":
                weak.append(skill_name)
            else:
                strong.append(skill_name)

        return {
            "strong": sorted(list(set(strong))),
            "weak": sorted(list(set(weak))),
            "levels": levels,
        }
