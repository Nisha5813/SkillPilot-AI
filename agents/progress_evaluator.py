"""
Progress Evaluator Agent
Boundary: Evaluates assessment submissions against objective scoring criteria.
Input: {
    "skill": str,
    "user_answers": dict,  # {question_id: answer_text}
    "questions": list      # list of full question objects with correct_answer and concept
}
Output: {
    "score": float,
    "passed": bool,
    "weak_concepts": [str],
    "validated_level": Optional[str],
    "needs_roadmap_update": bool
}
"""

from typing import Any, Dict, List, Optional
from agents.base import BaseAgent


class ProgressEvaluator(BaseAgent):
    def __init__(self):
        super().__init__(name="Progress Evaluator")

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        skill = input_dict.get("skill", "")
        user_answers = input_dict.get("user_answers", {})
        questions = input_dict.get("questions", [])

        if not questions:
            return {
                "score": 0.0,
                "passed": False,
                "weak_concepts": [],
                "validated_level": None,
                "needs_roadmap_update": False,
            }

        total_questions = len(questions)
        correct_count = 0
        weak_concepts: List[str] = []

        for q in questions:
            qid = q.get("id")
            correct = q.get("correct_answer", "").strip()
            submitted = user_answers.get(qid, "").strip()
            concept = q.get("concept", "general")

            if submitted and submitted == correct:
                correct_count += 1
            else:
                if concept not in weak_concepts:
                    weak_concepts.append(concept)

        score = round((correct_count / total_questions) * 100.0, 1)

        # Apply specification threshold rules:
        # Score < 50: keep claimed level, flag weak concepts, insert remedial resources at top
        # Score 50-79: set validated level to Intermediate, recommend additional practice
        # Score 80-100: set validated level to Advanced, mark assessment passed, recommend next skill
        if score < 50.0:
            passed = False
            validated_level: Optional[str] = None
            needs_roadmap_update = True
        elif score < 80.0:
            passed = False
            validated_level = "Intermediate"
            needs_roadmap_update = False
        else:
            passed = True
            validated_level = "Advanced"
            needs_roadmap_update = True
            weak_concepts = []  # cleared on high score

        return {
            "score": score,
            "passed": passed,
            "weak_concepts": weak_concepts,
            "validated_level": validated_level,
            "needs_roadmap_update": needs_roadmap_update,
        }
