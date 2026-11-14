"""
Learning Architect Agent
Boundary: Constructs structured, prerequisite-ordered learning roadmaps based on skill gaps
          and adapts active roadmaps with targeted remedial resources upon assessment evaluation.
Input (Roadmap Generation): {
    "missing_skills": [str],
    "weak_skills": [str],
    "courses_catalog": [dict],
    "learner_levels": {str: str},
    "completed_items": [str],
    "remedial_skills": [str]
}
Input (Assessment Remedial Adaptation): {
    "action": "adapt_remedial",
    "assessment_result": {
        "score": float,
        "passed": bool,
        "weak_concepts": [str],
        "validated_level": Optional[str],
        "needs_roadmap_update": bool
    },
    "skill": str,
    "courses_catalog": [dict],
    "current_roadmap": [dict],
    "completed_items": [str]
}
Output:
    Roadmap Generation: {"roadmap": [{position, skill, resource_title, resource_type, is_remedial}]}
    Remedial Adaptation: {
        "adapted": bool,
        "remedial_resources_selected": list,
        "shift_positions_by": int,
        "remedial_added_titles": list,
        "summary": str
    }
"""

from typing import Any, Dict, List, Set
from agents.base import BaseAgent


class LearningArchitect(BaseAgent):
    def __init__(self):
        super().__init__(name="Learning Architect")

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        # Branch 1: Assessment Remedial Adaptation Workflow
        if input_dict.get("action") == "adapt_remedial" or "assessment_result" in input_dict:
            return self._adapt_remedial_roadmap(input_dict)

        # Branch 2: Standard Full Roadmap Generation
        return self._generate_full_roadmap(input_dict)

    def _adapt_remedial_roadmap(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        assessment_result = input_dict.get("assessment_result", {})
        skill = input_dict.get("skill", "")
        courses_catalog = input_dict.get("courses_catalog", [])
        current_roadmap = input_dict.get("current_roadmap", [])
        completed_titles = set(input_dict.get("completed_items", []))

        score = assessment_result.get("score", 100.0)
        needs_update = assessment_result.get("needs_roadmap_update", False)
        weak_concepts = assessment_result.get("weak_concepts", [])

        # Remedial resources are required when score < 50%
        if score >= 50.0 and not needs_update:
            return {
                "adapted": False,
                "remedial_resources_selected": [],
                "shift_positions_by": 0,
                "remedial_added_titles": [],
                "summary": f"Score {score}% satisfies minimum threshold. No remedial injection required.",
            }

        # Find existing active titles to avoid duplicate remedial entries
        existing_active_titles = {
            item.get("resource_title") for item in current_roadmap
            if not item.get("archived", False)
        }

        # Learning Architect selects matching remedial courses for the assessed skill
        candidate_remedials = [
            c for c in courses_catalog
            if c.get("skill") == skill
            and c.get("is_remedial") is True
            and c.get("title") not in completed_titles
            and c.get("title") not in existing_active_titles
        ]

        if not candidate_remedials:
            return {
                "adapted": False,
                "remedial_resources_selected": [],
                "shift_positions_by": 0,
                "remedial_added_titles": [],
                "summary": f"No new remedial resources needed or all already active/completed for {skill}.",
            }

        # Prepare selected remedial items with top positions (starting at position 1)
        selected = []
        for idx, course in enumerate(candidate_remedials, start=1):
            selected.append({
                "position": idx,
                "skill": course.get("skill", skill),
                "resource_title": course.get("title"),
                "resource_type": course.get("resource_type", "tutorial"),
                "is_remedial": True,
            })

        titles = [item["resource_title"] for item in selected]
        return {
            "adapted": True,
            "remedial_resources_selected": selected,
            "shift_positions_by": len(selected),
            "remedial_added_titles": titles,
            "summary": f"Selected {len(selected)} remedial resource(s) at position #1 for {skill} targeting weak concepts: {weak_concepts}.",
        }

    def _generate_full_roadmap(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        missing_skills = set(input_dict.get("missing_skills", []))
        weak_skills = set(input_dict.get("weak_skills", []))
        courses_catalog = input_dict.get("courses_catalog", [])
        learner_levels = input_dict.get("learner_levels", {})
        completed_titles = set(input_dict.get("completed_items", []))
        remedial_skills = set(input_dict.get("remedial_skills", []))

        # Only recommend resources for missing or weak skills
        target_skills = missing_skills.union(weak_skills)

        # Lookup mapping of catalog courses by ID
        courses_by_id = {c["id"]: c for c in courses_catalog}

        # Candidate courses: must be for target skills, not already completed, not remedial
        candidate_courses = [
            c for c in courses_catalog
            if c.get("skill") in target_skills
            and c.get("title") not in completed_titles
            and not c.get("is_remedial", False)
        ]

        # Separate any requested remedial resources
        remedial_items: List[Dict[str, Any]] = [
            c for c in courses_catalog
            if c.get("skill") in remedial_skills
            and c.get("is_remedial", True)
            and c.get("title") not in completed_titles
        ]

        # Foundational domain order (tie-breaker when multiple courses have ready prerequisites)
        # Guarantees foundational web markups & core languages precede dependent libraries/runtimes
        foundation_order = {
            "HTML": 1,
            "CSS": 2,
            "JavaScript": 3,
            "React": 4,
            "Node.js": 5,
            "REST APIs": 6,
            "Python": 1,
            "SQL": 2,
            "Statistics": 3,
            "Pandas": 4,
            "Machine Learning": 5,
        }
        level_weight = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}

        # Track satisfied skills and satisfied course IDs
        satisfied_skills: Set[str] = {
            s for s, lvl in learner_levels.items()
            if lvl in ("Intermediate", "Advanced")
        }
        satisfied_course_ids: Set[str] = {
            c["id"] for c in courses_catalog
            if c.get("title") in completed_titles
        }

        # Topological dependency resolution loop
        ordered_normal: List[Dict[str, Any]] = []
        remaining = list(candidate_courses)

        while remaining:
            # Find all candidate courses whose prerequisites are completely satisfied
            ready = []
            for c in remaining:
                prereqs = c.get("prerequisites", [])
                can_take = True
                for p in prereqs:
                    if p in courses_by_id:
                        # Course-level prerequisite
                        if p not in satisfied_course_ids:
                            can_take = False
                            break
                    else:
                        # Skill-level prerequisite
                        if p not in satisfied_skills:
                            can_take = False
                            break
                if can_take:
                    ready.append(c)

            if not ready:
                # Fallback if circular dependency or unresolved external prereq
                ready = [remaining[0]]

            # Sort ready candidates: foundational skills first, beginner levels first, then courses before exercises
            ready.sort(key=lambda x: (
                foundation_order.get(x.get("skill"), 99),
                level_weight.get(x.get("level", "Beginner"), 1),
                1 if x.get("resource_type") == "course" else (2 if x.get("resource_type") == "tutorial" else 3)
            ))

            # Schedule the top candidate
            next_course = ready[0]
            ordered_normal.append(next_course)
            remaining.remove(next_course)

            # Satisfy this course and its skill for subsequent dependent milestones
            satisfied_course_ids.add(next_course["id"])
            satisfied_skills.add(next_course["skill"])

        # Remedial resources come FIRST if any were specifically requested
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
