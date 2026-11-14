"""
Career Analyst Agent
Boundary: Evaluates a learner's current skill levels against target role requirements.
Input: {"target_role": str, "roles_catalog": dict, "current_levels": {str: str}, "weak_skills": [str]}
Output: {"required": [str], "missing": [str], "weak": [str], "transferable": [str]}
"""

from typing import Any, Dict, List
from agents.base import BaseAgent


class CareerAnalyst(BaseAgent):
    def __init__(self):
        super().__init__(name="Career Analyst")

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        target_role = input_dict.get("target_role", "")
        roles_catalog = input_dict.get("roles_catalog", {})
        current_levels = input_dict.get("current_levels", {})
        known_weak = set(input_dict.get("weak_skills", []))

        role_info = roles_catalog.get(target_role, {})
        required_skills_dict = role_info.get("required_skills", {})
        required = list(required_skills_dict.keys())

        missing: List[str] = []
        weak: List[str] = []
        transferable: List[str] = []

        for req_skill in required:
            if req_skill not in current_levels:
                missing.append(req_skill)
            else:
                level = current_levels[req_skill]
                if req_skill in known_weak or level == "Beginner":
                    weak.append(req_skill)
                else:
                    transferable.append(req_skill)

        return {
            "required": required,
            "missing": missing,
            "weak": weak,
            "transferable": transferable,
        }
