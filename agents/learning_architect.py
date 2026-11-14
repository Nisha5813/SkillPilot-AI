"""
Learning Architect Agent
Boundary: Constructs a structured, prerequisite-ordered learning roadmap based on skill gaps.
Input: {
    "missing_skills": [str],
    "weak_skills": [str],
    "courses_catalog": [dict],
    "learner_levels": {str: str},
    "completed_items": [str],  # resource titles already completed
    "remedial_skills": [str]   # skills that require remedial resources
}
Output: {
    "roadmap": [
        {
            "position": int,
            "skill": str,
            "resource_title": str,
            "resource_type": str,
            "is_remedial": bool
        }
    ]
}
"""

from typing import Any, Dict, List, Set
from agents.base import BaseAgent


class LearningArchitect(BaseAgent):
    def __init__(self):
        super().__init__(name="Learning Architect")

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        missing_skills = set(input_dict.get("missing_skills", []))
        weak_skills = set(input_dict.get("weak_skills", []))
        courses_catalog = input_dict.get("courses_catalog", [])
        learner_levels = input_dict.get("learner_levels", {})
        completed_titles = set(input_dict.get("completed_items", []))
        remedial_skills = set(input_dict.get("remedial_skills", []))

        target_skills = missing_skills.union(weak_skills)

        # 1. Filter out already completed resources
        candidate_courses = [
            c for c in courses_catalog
            if c.get("title") not in completed_titles
        ]

        # 2. Separate remedial resources for skills requiring remediation
        remedial_items: List[Dict[str, Any]] = []
        normal_items: List[Dict[str, Any]] = []

        for c in candidate_courses:
            skill = c.get("skill")
            if skill not in target_skills:
                continue

            is_rem = c.get("is_remedial", False)
            if is_rem:
                # Include remedial only if skill is in remedial_skills
                if skill in remedial_skills:
                    remedial_items.append(c)
            else:
                normal_items.append(c)

        # 3. Order normal courses by prerequisite dependencies and level
        # Level sort weight
        level_weight = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
        
        # Determine satisfied prerequisites
        satisfied_skills: Set[str] = {
            s for s, lvl in learner_levels.items()
            if lvl in ("Intermediate", "Advanced")
        }
        satisfied_course_ids: Set[str] = set()

        # Multi-pass dependency resolution
        ordered_normal: List[Dict[str, Any]] = []
        remaining = list(normal_items)
        
        # Sort remaining by level initially
        remaining.sort(key=lambda x: level_weight.get(x.get("level", "Beginner"), 1))

        # We allow up to len(remaining) passes to resolve prereqs
        progress = True
        while remaining and progress:
            progress = False
            unmet = []
            for course in remaining:
                prereqs = course.get("prerequisites", [])
                can_take = True
                for p in prereqs:
                    # Prereq can be a skill or a course ID
                    if p in courses_catalog:  # course id
                        if p not in satisfied_course_ids:
                            can_take = False
                            break
                    else:
                        # skill name
                        if p not in satisfied_skills:
                            can_take = False
                            break

                if can_take:
                    ordered_normal.append(course)
                    satisfied_course_ids.add(course.get("id"))
                    satisfied_skills.add(course.get("skill"))
                    progress = True
                else:
                    unmet.append(course)
            remaining = unmet

        # Append any remaining courses whose prereqs might be unmet in catalog
        # to ensure learner has complete guidance
        ordered_normal.extend(remaining)

        # 4. Construct final roadmap: Remedial resources come FIRST!
        all_ordered = remedial_items + ordered_normal

        roadmap = []
        for idx, item in enumerate(all_ordered, start=1):
            roadmap.append({
                "position": idx,
                "skill": item.get("skill"),
                "resource_title": item.get("title"),
                "resource_type": item.get("resource_type", "tutorial"),
                "is_remedial": bool(item.get("is_remedial", False)),
            })

        return {"roadmap": roadmap}
