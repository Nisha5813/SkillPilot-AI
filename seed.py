"""
SkillPilot AI - Seed & Data Verification Script
Loads, validates, and verifies catalog definitions for roles, courses, and assessments.
Safe to execute multiple times without deleting or resetting learner data.
"""

import json
from pathlib import Path
from db import init_db, get_db

DATA_DIR = Path(__file__).resolve().parent / "data"
ROLES_FILE = DATA_DIR / "roles.json"
COURSES_FILE = DATA_DIR / "courses.json"
ASSESSMENTS_FILE = DATA_DIR / "assessments.json"


def load_json(file_path: Path):
    if not file_path.exists():
        raise FileNotFoundError(f"Missing required data file: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_roles(roles_data: dict) -> None:
    required_roles = ["Full Stack Developer", "Data Scientist"]
    for role in required_roles:
        if role not in roles_data:
            raise ValueError(f"Required role '{role}' is missing from roles.json")
    
    fs_skills = roles_data["Full Stack Developer"]["required_skills"]
    expected_fs = [
        "Python", "SQL", "HTML", "CSS", "JavaScript", "React", "Node.js", "REST APIs"
    ]
    for skill in expected_fs:
        if skill not in fs_skills:
            raise ValueError(f"Full Stack Developer missing required skill '{skill}'")

    ds_skills = roles_data["Data Scientist"]["required_skills"]
    expected_ds = ["Python", "SQL", "Statistics", "Pandas", "Machine Learning"]
    for skill in expected_ds:
        if skill not in ds_skills:
            raise ValueError(f"Data Scientist missing required skill '{skill}'")


def verify_courses(courses_data: list) -> None:
    required_counts = {
        "JavaScript": 3,
        "React": 3,
        "Node.js": 3,
        "CSS": 3,
        "REST APIs": 3,
        "Python": 1,
        "SQL": 1,
        "HTML": 1,
        "Statistics": 1,
        "Pandas": 1,
        "Machine Learning": 1,
    }
    skill_counts = {}
    remedial_js_found = False

    for item in courses_data:
        skill = item.get("skill")
        skill_counts[skill] = skill_counts.get(skill, 0) + 1
        if (
            skill == "JavaScript"
            and item.get("title") == "JavaScript fundamentals: functions and closures"
            and item.get("is_remedial") is True
        ):
            remedial_js_found = True

    for skill, min_count in required_counts.items():
        actual_count = skill_counts.get(skill, 0)
        if actual_count < min_count:
            raise ValueError(
                f"Skill '{skill}' requires at least {min_count} courses, found {actual_count}"
            )

    if not remedial_js_found:
        raise ValueError(
            "Missing required remedial resource 'JavaScript fundamentals: functions and closures' (is_remedial=True)"
        )


def verify_assessments(assessments_data: dict) -> None:
    if "JavaScript" not in assessments_data:
        raise ValueError("Missing 'JavaScript' assessment suite in assessments.json")
    
    js_qs = assessments_data["JavaScript"]
    if len(js_qs) < 5:
        raise ValueError(f"JavaScript assessment must have at least 5 questions, found {len(js_qs)}")

    concepts = {q.get("concept") for q in js_qs}
    required_concepts = {"functions", "closures", "async"}
    if not required_concepts.issubset(concepts):
        raise ValueError(
            f"JavaScript assessment must cover {required_concepts}, found {concepts}"
        )

    for skill, questions in assessments_data.items():
        for q in questions:
            if not q.get("correct_answer"):
                raise ValueError(f"Question {q.get('id')} in {skill} missing server-side correct_answer")


def run_seed():
    print("=" * 60)
    print("SkillPilot AI - Running Safe Seed & Data Verification")
    print("=" * 60)

    # 1. Initialize DB safely (CREATE TABLE IF NOT EXISTS preserves existing data)
    print("\n1. Ensuring database schema is ready...")
    init_db()
    conn = get_db()
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM learners;")
        learners_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM assessments;")
        assessments_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM roadmap_items;")
        roadmap_count = cur.fetchone()[0]
    conn.close()
    print(f"   [DB Ready] Existing user records preserved:")
    print(f"     - Learners: {learners_count}")
    print(f"     - Past Assessments: {assessments_count}")
    print(f"     - Roadmap Items: {roadmap_count}")

    # 2. Load and verify roles.json
    print("\n2. Loading and verifying roles.json...")
    roles = load_json(ROLES_FILE)
    verify_roles(roles)
    print(f"   [OK] Loaded {len(roles)} roles: {list(roles.keys())}")

    # 3. Load and verify courses.json
    print("\n3. Loading and verifying courses.json...")
    courses = load_json(COURSES_FILE)
    verify_courses(courses)
    print(f"   [OK] Loaded {len(courses)} learning resources across 11 skills.")
    print("   [OK] Remedial JavaScript course verified.")

    # 4. Load and verify assessments.json
    print("\n4. Loading and verifying assessments.json...")
    assessments = load_json(ASSESSMENTS_FILE)
    verify_assessments(assessments)
    for skill, qs in assessments.items():
        print(f"   [OK] Assessment '{skill}': {len(qs)} questions verified (answers stored server-side).")

    print("\n" + "=" * 60)
    print("SUCCESS: Phase 2 Seed & Data Verification Completed Successfully.")
    print("=" * 60)


if __name__ == "__main__":
    run_seed()
