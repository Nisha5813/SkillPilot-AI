"""
Career Mentor Agent
Boundary: Provides personalized career guidance, gap summaries, and adaptive advice.
Input: {
    "event_type": str,   # "learner_created", "assessment_result", "career_changed", "learner_query"
    "context": dict      # Structured context for prompt / template generation
}
Output: {
    "message": str,
    "source": "gemini" | "template"
}
"""

import os
import time
from typing import Any, Dict
import httpx
from agents.base import BaseAgent

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


class CareerMentor(BaseAgent):
    def __init__(self):
        super().__init__(name="Career Mentor")

    def _call_gemini(self, prompt: str) -> str:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")

        url = f"{GEMINI_API_URL}?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.3
            }
        }

        # 5 seconds timeout, at most one retry (2 attempts total)
        for attempt in range(2):
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                    # If non-200, retry once or raise
                    if attempt == 1:
                        resp.raise_for_status()
            except Exception as e:
                if attempt == 1:
                    raise e
                time.sleep(0.5)

        raise RuntimeError("Failed to obtain response from Gemini API")

    def _template_response(self, event_type: str, context: Dict[str, Any]) -> str:
        learner_name = context.get("learner_name", "Learner")
        target_role = context.get("target_role", "Target Role")

        if event_type == "learner_created":
            missing = context.get("missing_skills", [])
            weak = context.get("weak_skills", [])
            transferable = context.get("transferable_skills", [])
            missing_str = ", ".join(missing) if missing else "None"
            weak_str = ", ".join(weak) if weak else "None"
            trans_str = ", ".join(transferable) if transferable else "None"
            return (
                f"Welcome {learner_name}! To excel as a {target_role}, your skill audit indicates "
                f"solid transferable foundations in {trans_str}. However, you currently have critical gaps in "
                f"{missing_str} and developing proficiency in {weak_str}. "
                f"A personalized roadmap has been generated to guide you step-by-step from fundamental principles to full development readiness."
            )

        elif event_type == "assessment_result":
            skill = context.get("skill", "the skill")
            score = context.get("score", 0.0)
            weak_concepts = context.get("weak_concepts", [])
            weak_str = ", ".join(weak_concepts) if weak_concepts else "core patterns"

            if score < 50:
                return (
                    f"Assessment Update for {skill}: Your score of {score}% indicates foundational gaps, "
                    f"particularly around {weak_str}. To build lasting competency, your roadmap has been adapted "
                    f"with high-priority remedial resources placed right at the top. Master these core concepts before moving ahead."
                )
            elif score < 80:
                return (
                    f"Assessment Update for {skill}: Solid effort! You scored {score}%, validating an Intermediate level. "
                    f"Focus on practical lab exercises to solidify your grasp before attempting advanced topics."
                )
            else:
                next_skill = context.get("next_skill", "your next roadmap milestone")
                return (
                    f"Assessment Update for {skill}: Outstanding work! You achieved a score of {score}%, validating Advanced proficiency. "
                    f"You have satisfied requirements for {skill} and are ready to tackle {next_skill}."
                )

        elif event_type == "career_changed":
            old_role = context.get("old_role", "previous career")
            new_role = context.get("new_role", target_role)
            transferable = context.get("transferable_skills", [])
            trans_str = ", ".join(transferable) if transferable else "None"
            return (
                f"Career Pivot to {new_role}: Switching from {old_role} to {new_role}. "
                f"Great news—your existing proficiencies in {trans_str} transfer directly toward your new goal. "
                f"Your historical assessments and completed activities have been safely preserved, and an updated learning roadmap "
                f"focused on new domain requirements is now active."
            )

        elif event_type == "learner_query":
            query = context.get("query", "")
            return (
                f"Mentor Advice regarding '{query}': Consistent deliberate practice and building end-to-end projects "
                f"are the fastest ways to bridge technical gaps. Focus on one roadmap milestone at a time, validate your understanding with assessments, "
                f"and remember that course completion is a stepping stone toward genuine problem-solving capability."
            )

        return (
            f"Career guidance for {learner_name}: Focus on completing your prioritized roadmap milestones and validating each skill."
        )

    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        event_type = input_dict.get("event_type", "general")
        context = input_dict.get("context", {})

        # Construct prompt for Gemini
        prompt = (
            f"You are the Career Mentor in SkillPilot AI. "
            f"Provide concise, encouraging, professional mentorship advice (2-3 sentences max). "
            f"Event: {event_type}. Context: {context}. "
            f"Rule: Never claim completing a course proves mastery, and never claim a skill is mastered just because an AI said so."
        )

        try:
            message = self._call_gemini(prompt)
            return {"message": message, "source": "gemini"}
        except Exception:
            # Deterministic template fallback
            message = self._template_response(event_type, context)
            return {"message": message, "source": "template"}
