"""
Orchestrator Module for SkillPilot AI
Coordinates multi-agent execution workflows, manages run_ids, logs agent activities,
enforces business rules, calculates readiness, and handles adaptive loops.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import get_db
from agents.skill_analyst import SkillAnalyst
from agents.career_analyst import CareerAnalyst
from agents.learning_architect import LearningArchitect
from agents.progress_evaluator import ProgressEvaluator
from agents.career_mentor import CareerMentor

DATA_DIR = Path(__file__).resolve().parent / "data"

LEVEL_PERCENTAGES = {
    "Missing": 0.0,
    "Beginner": 25.0,
    "Intermediate": 65.0,
    "Advanced": 100.0,
}

READINESS_LABEL = "Estimated indicator, not a guaranteed job-readiness score."


def _load_data_file(filename: str):
    path = DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class Orchestrator:
    def __init__(self):
        self.skill_analyst = SkillAnalyst()
        self.career_analyst = CareerAnalyst()
        self.learning_architect = LearningArchitect()
        self.progress_evaluator = ProgressEvaluator()
        self.career_mentor = CareerMentor()

    def _get_roles_catalog(self) -> dict:
        return _load_data_file("roles.json")

    def _get_courses_catalog(self) -> list:
        return _load_data_file("courses.json")

    def _get_assessments_catalog(self) -> dict:
        return _load_data_file("assessments.json")

    def _log_agent_run(
        self,
        run_id: str,
        learner_id: Optional[int],
        agent_name: str,
        task: str,
        status: str,
        input_summary: str,
        result_summary: str,
        started_at: str,
        duration_ms: float,
    ) -> None:
        conn = get_db()
        with conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, learner_id, agent_name, task, status,
                    input_summary, result_summary, started_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    learner_id,
                    agent_name,
                    task,
                    status,
                    input_summary,
                    result_summary,
                    started_at,
                    max(0.0, float(duration_ms)),
                ),
            )
        conn.close()

    def _log_event(self, learner_id: int, message: str) -> None:
        conn = get_db()
        with conn:
            conn.execute(
                "INSERT INTO events (learner_id, message) VALUES (?, ?)",
                (learner_id, message),
            )
        conn.close()

    def _execute_agent(
        self,
        agent,
        task: str,
        input_data: Dict[str, Any],
        run_id: str,
        learner_id: Optional[int],
    ) -> Dict[str, Any]:
        started_iso = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        status = "success"
        output_data = {}
        try:
            output_data = agent.run(input_data)
        except Exception as e:
            status = "failed"
            output_data = {"error": str(e)}
        finally:
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            in_summary = json.dumps(
                {k: (str(v)[:100] if not isinstance(v, (int, float, bool)) else v) for k, v in input_data.items()}
            )
            out_summary = json.dumps(
                {k: (str(v)[:100] if not isinstance(v, (int, float, bool)) else v) for k, v in output_data.items()}
            )
            self._log_agent_run(
                run_id=run_id,
                learner_id=learner_id,
                agent_name=agent.name,
                task=task,
                status=status,
                input_summary=in_summary[:255],
                result_summary=out_summary[:255],
                started_at=started_iso,
                duration_ms=duration_ms,
            )

        return output_data

    # 1. Flow: Create Learner
    def create_learner(
        self,
        name: str,
        education: str,
        target_role: str,
        skills: List[Dict[str, str]],
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        roles = self._get_roles_catalog()
        courses = self._get_courses_catalog()

        if target_role not in roles:
            raise ValueError(f"Unknown target role '{target_role}'")

        # Insert learner
        conn = get_db()
        with conn:
            cur = conn.cursor()
            if user_id is not None:
                cur.execute(
                    "INSERT INTO learners (name, education, target_role, user_id) VALUES (?, ?, ?, ?)",
                    (name, education, target_role, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO learners (name, education, target_role) VALUES (?, ?, ?)",
                    (name, education, target_role),
                )
            learner_id = cur.lastrowid

            # Insert learner_skills
            for s in skills:
                cur.execute(
                    """
                    INSERT INTO learner_skills (learner_id, skill, claimed_level, validated_level)
                    VALUES (?, ?, ?, NULL)
                    """,
                    (learner_id, s["skill"], s["claimed_level"]),
                )
        conn.close()

        self._log_event(learner_id, f"Learner profile created for {name} with target role {target_role}.")

        # Step A: Skill Analyst
        skill_input = {"skills": skills, "assessments": []}
        skill_out = self._execute_agent(
            self.skill_analyst,
            task="Analyze baseline skill levels",
            input_data=skill_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Step B: Career Analyst (using Skill Analyst output)
        career_input = {
            "target_role": target_role,
            "roles_catalog": roles,
            "current_levels": skill_out.get("levels", {}),
            "weak_skills": skill_out.get("weak", []),
        }
        career_out = self._execute_agent(
            self.career_analyst,
            task="Compare learner profile against target role requirements",
            input_data=career_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Step C: Learning Architect (using Career Analyst output)
        architect_input = {
            "missing_skills": career_out.get("missing", []),
            "weak_skills": career_out.get("weak", []),
            "courses_catalog": courses,
            "learner_levels": skill_out.get("levels", {}),
            "completed_items": [],
            "remedial_skills": [],
        }
        architect_out = self._execute_agent(
            self.learning_architect,
            task="Generate personalized prerequisite-ordered learning roadmap",
            input_data=architect_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Save roadmap items in DB
        roadmap_items = architect_out.get("roadmap", [])
        conn = get_db()
        with conn:
            for item in roadmap_items:
                conn.execute(
                    """
                    INSERT INTO roadmap_items (
                        learner_id, skill, resource_title, resource_type,
                        status, position, is_remedial, archived
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, 0)
                    """,
                    (
                        learner_id,
                        item["skill"],
                        item["resource_title"],
                        item["resource_type"],
                        item["position"],
                        1 if item["is_remedial"] else 0,
                    ),
                )
        conn.close()

        # Step D: Career Mentor
        mentor_input = {
            "event_type": "learner_created",
            "context": {
                "learner_name": name,
                "target_role": target_role,
                "missing_skills": career_out.get("missing", []),
                "weak_skills": career_out.get("weak", []),
                "transferable_skills": career_out.get("transferable", []),
            },
        }
        mentor_out = self._execute_agent(
            self.career_mentor,
            task="Generate personalized gap summary and welcoming guidance",
            input_data=mentor_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        self._log_event(learner_id, f"Mentor guidance generated: {mentor_out.get('message', '')}")

        return {
            "learner_id": learner_id,
            "run_id": run_id,
            "gap": career_out,
            "roadmap": roadmap_items,
            "mentor_message": mentor_out.get("message", ""),
            "mentor_source": mentor_out.get("source", "template"),
        }

    # 2. Flow: Submit Assessment
    def submit_assessment(
        self,
        learner_id: int,
        skill: str,
        answers: Dict[str, str],
    ) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        assessments_cat = self._get_assessments_catalog()
        questions = assessments_cat.get(skill)
        if not questions:
            raise ValueError(f"No assessment questions found for skill '{skill}'")

        # Step A: Progress Evaluator
        eval_input = {
            "skill": skill,
            "user_answers": answers,
            "questions": questions,
        }
        eval_out = self._execute_agent(
            self.progress_evaluator,
            task=f"Evaluate assessment submission for {skill}",
            input_data=eval_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        score = eval_out.get("score", 0.0)
        passed = eval_out.get("passed", False)
        weak_concepts = eval_out.get("weak_concepts", [])
        validated_level = eval_out.get("validated_level")
        needs_roadmap_update = eval_out.get("needs_roadmap_update", False)

        # Record in assessments table
        conn = get_db()
        with conn:
            conn.execute(
                """
                INSERT INTO assessments (learner_id, skill, score, weak_concepts)
                VALUES (?, ?, ?, ?)
                """,
                (learner_id, skill, score, json.dumps(weak_concepts)),
            )

            # Update learner_skills if validated level is set (Intermediate or Advanced)
            if validated_level:
                conn.execute(
                    """
                    INSERT INTO learner_skills (learner_id, skill, claimed_level, validated_level)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(learner_id, skill) DO UPDATE SET validated_level = excluded.validated_level
                    """,
                    (learner_id, skill, "Beginner", validated_level),
                )
        conn.close()

        # Step B: Learning Architect - Adapt Roadmap
        # Fetch current active roadmap items and completed items
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, skill, resource_title, resource_type, status, position, is_remedial, archived
            FROM roadmap_items
            WHERE learner_id = ? AND archived = 0
            ORDER BY position ASC
            """,
            (learner_id,),
        )
        current_active_roadmap = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT resource_title FROM roadmap_items
            WHERE learner_id = ? AND status = 'completed'
            """,
            (learner_id,),
        )
        completed_titles = [r["resource_title"] for r in cur.fetchall()]
        conn.close()

        courses_cat = self._get_courses_catalog()

        # Pass structured output from Progress Evaluator directly to Learning Architect
        architect_input = {
            "action": "adapt_remedial",
            "assessment_result": eval_out,
            "skill": skill,
            "courses_catalog": courses_cat,
            "current_roadmap": current_active_roadmap,
            "completed_items": completed_titles,
        }
        architect_out = self._execute_agent(
            self.learning_architect,
            task=f"Adapt roadmap with remedial resources for {skill}",
            input_data=architect_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        remedial_added = architect_out.get("remedial_added_titles", [])
        shift_by = architect_out.get("shift_positions_by", 0)
        remedials_to_insert = architect_out.get("remedial_resources_selected", [])

        # Persist the Learning Architect's selected remedial items at top of roadmap
        if shift_by > 0 and remedials_to_insert:
            conn = get_db()
            with conn:
                # Shift active items down
                conn.execute(
                    "UPDATE roadmap_items SET position = position + ? WHERE learner_id = ? AND archived = 0",
                    (shift_by, learner_id),
                )
                # Insert the selected remedial items at the top
                for rem in remedials_to_insert:
                    conn.execute(
                        """
                        INSERT INTO roadmap_items (
                            learner_id, skill, resource_title, resource_type,
                            status, position, is_remedial, archived
                        ) VALUES (?, ?, ?, ?, 'pending', ?, 1, 0)
                        """,
                        (
                            learner_id,
                            rem["skill"],
                            rem["resource_title"],
                            rem["resource_type"],
                            rem["position"],
                        ),
                    )
            conn.close()

        # Determine next skill if passed
        roles = self._get_roles_catalog()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT target_role FROM learners WHERE id = ?", (learner_id,))
        lr_row = cur.fetchone()
        target_role = lr_row["target_role"] if lr_row else ""
        conn.close()

        next_skill = None
        if passed and target_role in roles:
            req_skills = list(roles[target_role].get("required_skills", {}).keys())
            try:
                cur_idx = req_skills.index(skill)
                if cur_idx + 1 < len(req_skills):
                    next_skill = req_skills[cur_idx + 1]
            except ValueError:
                pass

        # Step C: Career Mentor
        mentor_input = {
            "event_type": "assessment_result",
            "context": {
                "skill": skill,
                "score": score,
                "weak_concepts": weak_concepts,
                "passed": passed,
                "next_skill": next_skill or "your next roadmap topic",
            },
        }
        mentor_out = self._execute_agent(
            self.career_mentor,
            task=f"Provide feedback on assessment performance for {skill}",
            input_data=mentor_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        event_msg = f"Assessment submitted for {skill}: {score}%. {mentor_out.get('message', '')}"
        self._log_event(learner_id, event_msg)

        return {
            "run_id": run_id,
            "skill": skill,
            "score": score,
            "passed": passed,
            "weak_concepts": weak_concepts,
            "validated_level": validated_level,
            "remedial_added": remedial_added,
            "mentor_message": mentor_out.get("message", ""),
            "mentor_source": mentor_out.get("source", "template"),
        }

    # 3. Flow: Change Target Role
    def change_target_role(self, learner_id: int, new_role: str) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        roles = self._get_roles_catalog()
        courses = self._get_courses_catalog()

        if new_role not in roles:
            raise ValueError(f"Unknown target role '{new_role}'")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT target_role, name FROM learners WHERE id = ?", (learner_id,))
        learner = cur.fetchone()
        if not learner:
            conn.close()
            raise ValueError(f"Learner {learner_id} not found")

        old_role = learner["target_role"]
        learner_name = learner["name"]

        with conn:
            # Update target role
            cur.execute("UPDATE learners SET target_role = ? WHERE id = ?", (new_role, learner_id))

            # Archive incomplete items from old role. NEVER archive completed items!
            cur.execute(
                "UPDATE roadmap_items SET archived = 1 WHERE learner_id = ? AND status = 'pending'",
                (learner_id,),
            )

            # Fetch completed titles (never delete or re-recommend completed)
            cur.execute(
                "SELECT resource_title FROM roadmap_items WHERE learner_id = ? AND status = 'completed'",
                (learner_id,),
            )
            completed_titles = [row["resource_title"] for row in cur.fetchall()]

            # Fetch current skills
            cur.execute(
                "SELECT skill, claimed_level, validated_level FROM learner_skills WHERE learner_id = ?",
                (learner_id,),
            )
            learner_skills = [dict(row) for row in cur.fetchall()]

            # Fetch recent assessments
            cur.execute(
                "SELECT skill, score, weak_concepts FROM assessments WHERE learner_id = ?",
                (learner_id,),
            )
            assessments = [dict(row) for row in cur.fetchall()]
        conn.close()

        # Step A: Skill Analyst
        skill_input = {"skills": learner_skills, "assessments": assessments}
        skill_out = self._execute_agent(
            self.skill_analyst,
            task="Re-evaluate skills for new career trajectory",
            input_data=skill_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Step B: Career Analyst
        career_input = {
            "target_role": new_role,
            "roles_catalog": roles,
            "current_levels": skill_out.get("levels", {}),
            "weak_skills": skill_out.get("weak", []),
        }
        career_out = self._execute_agent(
            self.career_analyst,
            task=f"Analyze career gap transition from {old_role} to {new_role}",
            input_data=career_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Step C: Learning Architect
        architect_input = {
            "missing_skills": career_out.get("missing", []),
            "weak_skills": career_out.get("weak", []),
            "courses_catalog": courses,
            "learner_levels": skill_out.get("levels", {}),
            "completed_items": completed_titles,
            "remedial_skills": [],
        }
        architect_out = self._execute_agent(
            self.learning_architect,
            task=f"Generate updated roadmap for {new_role}",
            input_data=architect_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        # Insert new active roadmap items
        new_items = architect_out.get("roadmap", [])
        conn = get_db()
        with conn:
            for item in new_items:
                conn.execute(
                    """
                    INSERT INTO roadmap_items (
                        learner_id, skill, resource_title, resource_type,
                        status, position, is_remedial, archived
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, 0)
                    """,
                    (
                        learner_id,
                        item["skill"],
                        item["resource_title"],
                        item["resource_type"],
                        item["position"],
                        1 if item["is_remedial"] else 0,
                    ),
                )
        conn.close()

        # Step D: Career Mentor
        mentor_input = {
            "event_type": "career_changed",
            "context": {
                "learner_name": learner_name,
                "old_role": old_role,
                "new_role": new_role,
                "transferable_skills": career_out.get("transferable", []),
            },
        }
        mentor_out = self._execute_agent(
            self.career_mentor,
            task=f"Explain career pivot from {old_role} to {new_role}",
            input_data=mentor_input,
            run_id=run_id,
            learner_id=learner_id,
        )

        trans_str = ", ".join(career_out.get("transferable", []))
        self._log_event(
            learner_id,
            f"Career goal changed to {new_role}. Transferable skills: {trans_str or 'None'}.",
        )

        return {
            "run_id": run_id,
            "old_role": old_role,
            "new_role": new_role,
            "gap": career_out,
            "new_roadmap": new_items,
            "mentor_message": mentor_out.get("message", ""),
            "mentor_source": mentor_out.get("source", "template"),
        }

    # 4. Readiness Calculation (Exact Section 5 Rules)
    def compute_readiness(self, learner_id: int) -> Dict[str, Any]:
        roles = self._get_roles_catalog()
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT target_role FROM learners WHERE id = ?", (learner_id,))
        lr = cur.fetchone()
        if not lr:
            conn.close()
            raise ValueError(f"Learner {learner_id} not found")

        target_role = lr["target_role"]
        role_info = roles.get(target_role, {})
        required_skills = role_info.get("required_skills", {})

        cur.execute(
            "SELECT skill, claimed_level, validated_level FROM learner_skills WHERE learner_id = ?",
            (learner_id,),
        )
        skill_rows = {row["skill"]: dict(row) for row in cur.fetchall()}

        # Fetch completed items separately (Readiness does NOT use roadmap completion!)
        cur.execute(
            """
            SELECT id, skill, resource_title, resource_type
            FROM roadmap_items
            WHERE learner_id = ? AND status = 'completed'
            ORDER BY id ASC
            """,
            (learner_id,),
        )
        completed_activities = [dict(r) for r in cur.fetchall()]

        # Fetch events log
        cur.execute(
            "SELECT message, created_at FROM events WHERE learner_id = ? ORDER BY id DESC LIMIT 20",
            (learner_id,),
        )
        events = [dict(r) for r in cur.fetchall()]
        conn.close()

        if not required_skills:
            return {
                "readiness_percentage": 0.0,
                "label": READINESS_LABEL,
                "breakdown": {},
                "completed_activities": completed_activities,
                "events": events,
            }

        total_credit = 0.0
        breakdown = {}

        for req_skill, req_level_str in required_skills.items():
            req_pct = LEVEL_PERCENTAGES.get(req_level_str, 65.0)

            learner_skill_info = skill_rows.get(req_skill)
            if not learner_skill_info:
                learner_pct = LEVEL_PERCENTAGES["Missing"]
                effective_level = "Missing"
                assessed = False
            else:
                claimed = learner_skill_info.get("claimed_level", "Beginner")
                validated = learner_skill_info.get("validated_level")
                if validated:
                    effective_level = validated
                    learner_pct = LEVEL_PERCENTAGES.get(validated, 25.0)
                    assessed = True
                else:
                    # Unassessed: credit is capped at Intermediate (65%)
                    effective_level = claimed
                    raw_pct = LEVEL_PERCENTAGES.get(claimed, 25.0)
                    learner_pct = min(raw_pct, LEVEL_PERCENTAGES["Intermediate"])
                    assessed = False

            per_skill_credit = min(learner_pct, req_pct) / req_pct if req_pct > 0 else 0.0
            total_credit += per_skill_credit

            breakdown[req_skill] = {
                "required_level": req_level_str,
                "effective_level": effective_level,
                "is_validated": assessed,
                "learner_pct": learner_pct,
                "required_pct": req_pct,
                "credit": round(per_skill_credit, 4),
            }

        num_skills = len(required_skills)
        readiness_pct = round((total_credit / num_skills) * 100.0, 1)

        return {
            "readiness_percentage": readiness_pct,
            "label": READINESS_LABEL,
            "breakdown": breakdown,
            "completed_activities": completed_activities,
            "events": events,
        }

    # 5. Fetch Agent Activity Log for latest run
    def get_latest_agent_logs(self, learner_id: int) -> List[Dict[str, Any]]:
        conn = get_db()
        cur = conn.cursor()
        # Find latest run_id for this learner
        cur.execute(
            """
            SELECT run_id FROM agent_runs
            WHERE learner_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (learner_id,),
        )
        latest_row = cur.fetchone()
        if not latest_row:
            conn.close()
            return []

        latest_run_id = latest_row["run_id"]
        cur.execute(
            """
            SELECT id, run_id, learner_id, agent_name, task, status,
                   input_summary, result_summary, started_at, duration_ms
            FROM agent_runs
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (latest_run_id,),
        )
        logs = [dict(row) for row in cur.fetchall()]
        conn.close()
        return logs
