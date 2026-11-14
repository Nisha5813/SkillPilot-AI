"""
SkillPilot AI - Main Application
FastAPI backend providing REST APIs, serving static single-page frontend,
and orchestrating multi-agent career readiness workflows.
"""

import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    clear_auth_cookies,
    create_session,
    delete_session,
    get_current_user,
    get_user_by_session_token,
    hash_password,
    is_rate_limited,
    record_login_attempt,
    require_current_user,
    set_auth_cookies,
    validate_email,
    validate_password_strength,
    verify_csrf,
    verify_password,
)
from db import get_db, init_db
from orchestrator import Orchestrator

app = FastAPI(
    title="SkillPilot AI",
    description="AI-powered personalized learning and skill navigation platform",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
INDEX_HTML = STATIC_DIR / "index.html"

orchestrator = Orchestrator()


# Ensure consistent API response format: {"ok": bool, "data": ..., "error": ...}
def success_response(data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": True, "data": data, "error": None})


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "data": None, "error": message})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    msg = "; ".join([f"{e.get('loc', ['field'])[-1]}: {e.get('msg')}" for e in errors])
    return error_response(f"Validation error: {msg}", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return error_response(exc.detail, status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return error_response(f"Internal server error: {str(exc)}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Pydantic Schemas
class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)


class SkillInput(BaseModel):
    skill: str = Field(..., min_length=1)
    claimed_level: str = Field(..., pattern="^(Beginner|Intermediate|Advanced)$")


class CreateLearnerRequest(BaseModel):
    name: str = Field(..., min_length=1)
    education: Optional[str] = ""
    target_role: str = Field(..., min_length=1)
    skills: List[SkillInput] = Field(default_factory=list)


class SubmitAssessmentRequest(BaseModel):
    skill: str = Field(..., min_length=1)
    answers: Dict[str, str] = Field(default_factory=dict)


class TargetRoleRequest(BaseModel):
    role: str = Field(..., min_length=1)


class MentorQuestionRequest(BaseModel):
    learner_id: int
    question: str = Field(..., min_length=1)


class RoadmapPatchRequest(BaseModel):
    status: Optional[str] = "completed"


# Lifespan / Startup
@app.on_event("startup")
def startup_event():
    init_db()


# Frontend Routes
@app.get("/")
def serve_root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return success_response({"message": "SkillPilot AI backend running. Place index.html in static/"})


# =====================================================================
# Authentication Endpoints (Phase 2)
# =====================================================================

@app.post("/api/auth/register")
def register_user(payload: RegisterRequest):
    try:
        clean_name = payload.name.strip()
        if not clean_name:
            return error_response("Name cannot be empty", status_code=status.HTTP_400_BAD_REQUEST)
        clean_email = validate_email(payload.email)
        validate_password_strength(payload.password)
    except ValueError as ve:
        return error_response(str(ve), status_code=status.HTTP_400_BAD_REQUEST)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (clean_email,))
        if cur.fetchone():
            return error_response("An account with this email already exists", status_code=status.HTTP_400_BAD_REQUEST)

        pwd_hash = hash_password(payload.password)

        with conn:
            cur.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (clean_name, clean_email, pwd_hash),
            )
            user_id = cur.lastrowid

        raw_token, csrf_token = create_session(user_id, conn)
        resp = success_response(
            {
                "user": {
                    "id": user_id,
                    "name": clean_name,
                    "email": clean_email,
                },
                "has_profile": False,
                "learner_id": None,
                "csrf_token": csrf_token,
            },
            status_code=status.HTTP_201_CREATED,
        )
        set_auth_cookies(resp, raw_token, csrf_token)
        return resp
    finally:
        conn.close()


@app.post("/api/auth/login")
def login_user(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    clean_email = payload.email.strip().lower()

    conn = get_db()
    try:
        if is_rate_limited(clean_email, conn) or is_rate_limited(client_ip, conn):
            return error_response(
                "Too many failed login attempts. Please wait 5 minutes before trying again.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        cur = conn.cursor()
        cur.execute("SELECT id, name, email, password_hash, is_active FROM users WHERE email = ?", (clean_email,))
        user_row = cur.fetchone()

        if not user_row or not verify_password(payload.password, user_row["password_hash"]):
            record_login_attempt(clean_email, False, conn)
            record_login_attempt(client_ip, False, conn)
            return error_response("Invalid email or password", status_code=status.HTTP_401_UNAUTHORIZED)

        if not user_row["is_active"]:
            return error_response("Account is disabled", status_code=status.HTTP_403_FORBIDDEN)

        record_login_attempt(clean_email, True, conn)

        raw_token, csrf_token = create_session(user_row["id"], conn)

        cur.execute("SELECT id, name, education, target_role FROM learners WHERE user_id = ?", (user_row["id"],))
        learner = cur.fetchone()
        has_profile = learner is not None

        resp = success_response({
            "user": {
                "id": user_row["id"],
                "name": user_row["name"],
                "email": user_row["email"],
            },
            "has_profile": has_profile,
            "learner_id": learner["id"] if learner else None,
            "target_role": learner["target_role"] if learner else None,
            "education": learner["education"] if learner else None,
            "csrf_token": csrf_token,
        })
        set_auth_cookies(resp, raw_token, csrf_token)
        return resp
    finally:
        conn.close()


@app.post("/api/auth/logout")
def logout_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user = get_user_by_session_token(token)
        if user:
            submitted_csrf = request.headers.get(CSRF_HEADER_NAME)
            if not submitted_csrf or not secrets.compare_digest(submitted_csrf, user["csrf_token"]):
                return error_response("Invalid or missing CSRF token", status_code=status.HTTP_403_FORBIDDEN)
        delete_session(token)

    resp = success_response({"message": "Successfully logged out"})
    clear_auth_cookies(resp)
    return resp


@app.get("/api/auth/me")
def get_auth_me(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return error_response("Not authenticated", status_code=status.HTTP_401_UNAUTHORIZED)

    conn = get_db()
    try:
        user = get_user_by_session_token(token, conn)
        if not user:
            return error_response("Session invalid or expired", status_code=status.HTTP_401_UNAUTHORIZED)

        cur = conn.cursor()
        cur.execute("SELECT id, name, education, target_role FROM learners WHERE user_id = ?", (user["id"],))
        learner = cur.fetchone()
        has_profile = learner is not None

        return success_response({
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "created_at": user.get("created_at"),
            },
            "has_profile": has_profile,
            "learner_id": learner["id"] if learner else None,
            "target_role": learner["target_role"] if learner else None,
            "education": learner["education"] if learner else None,
            "csrf_token": user["csrf_token"],
        })
    finally:
        conn.close()


# =====================================================================
# Existing 12 Core API Endpoints
# =====================================================================

# 1. POST /api/learners
@app.post("/api/learners")
def create_learner(payload: CreateLearnerRequest, request: Request):
    try:
        user = get_current_user(request)
        user_id = user["id"] if user else None

        if user:
            submitted_csrf = request.headers.get(CSRF_HEADER_NAME)
            if not submitted_csrf or not secrets.compare_digest(submitted_csrf, user["csrf_token"]):
                return error_response("Invalid or missing CSRF token", status_code=status.HTTP_403_FORBIDDEN)

            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM learners WHERE user_id = ?", (user_id,))
            existing = cur.fetchone()
            conn.close()
            if existing:
                return error_response("A learner profile already exists for this account", status_code=status.HTTP_400_BAD_REQUEST)

        skills_dicts = [{"skill": s.skill, "claimed_level": s.claimed_level} for s in payload.skills]
        res = orchestrator.create_learner(
            name=payload.name,
            education=payload.education or "",
            target_role=payload.target_role,
            skills=skills_dicts,
            user_id=user_id,
        )
        return success_response(res, status_code=status.HTTP_201_CREATED)
    except ValueError as ve:
        return error_response(str(ve), status_code=status.HTTP_400_BAD_REQUEST)


# 2. GET /api/learners/{id}
@app.get("/api/learners/{id}")
def get_learner(id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, education, target_role FROM learners WHERE id = ?", (id,))
    learner = cur.fetchone()
    if not learner:
        conn.close()
        return error_response("Learner not found", status_code=status.HTTP_404_NOT_FOUND)

    cur.execute(
        "SELECT id, skill, claimed_level, validated_level FROM learner_skills WHERE learner_id = ?",
        (id,),
    )
    skills = [dict(row) for row in cur.fetchall()]
    conn.close()

    data = dict(learner)
    data["skills"] = skills
    return success_response(data)


# 3. GET /api/learners/{id}/gap
@app.get("/api/learners/{id}/gap")
def get_learner_gap(id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT target_role FROM learners WHERE id = ?", (id,))
    learner = cur.fetchone()
    if not learner:
        conn.close()
        return error_response("Learner not found", status_code=status.HTTP_404_NOT_FOUND)

    target_role = learner["target_role"]
    cur.execute(
        "SELECT skill, claimed_level, validated_level FROM learner_skills WHERE learner_id = ?",
        (id,),
    )
    skills_rows = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT skill, score, weak_concepts FROM assessments WHERE learner_id = ?", (id,))
    assessments_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    skill_analyst_out = orchestrator.skill_analyst.run({
        "skills": skills_rows,
        "assessments": assessments_rows,
    })

    roles_cat = orchestrator._get_roles_catalog()
    career_analyst_out = orchestrator.career_analyst.run({
        "target_role": target_role,
        "roles_catalog": roles_cat,
        "current_levels": skill_analyst_out.get("levels", {}),
        "weak_skills": skill_analyst_out.get("weak", []),
    })

    return success_response(career_analyst_out)


# 4. GET /api/learners/{id}/roadmap
@app.get("/api/learners/{id}/roadmap")
def get_learner_roadmap(id: int, archived: Optional[int] = 0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM learners WHERE id = ?", (id,))
    if not cur.fetchone():
        conn.close()
        return error_response("Learner not found", status_code=status.HTTP_404_NOT_FOUND)

    if archived == 1:
        # Retrieve archived incomplete items from previous career goals
        cur.execute(
            """
            SELECT id, skill, resource_title, resource_type, status, position, is_remedial, archived
            FROM roadmap_items
            WHERE learner_id = ? AND archived = 1
            ORDER BY id ASC
            """,
            (id,),
        )
    else:
        # Retrieve active pending items for the current active career role
        cur.execute(
            """
            SELECT id, skill, resource_title, resource_type, status, position, is_remedial, archived
            FROM roadmap_items
            WHERE learner_id = ? AND archived = 0 AND status = 'pending'
            ORDER BY position ASC, id ASC
            """,
            (id,),
        )

    rows = cur.fetchall()
    conn.close()

    items = []
    for idx, row in enumerate(rows, start=1):
        items.append({
            "id": row["id"],
            "skill": row["skill"],
            "resource_title": row["resource_title"],
            "resource_type": row["resource_type"],
            "status": row["status"],
            "position": idx if archived == 0 else row["position"],
            "is_remedial": bool(row["is_remedial"]),
            "archived": bool(row["archived"]),
        })

    return success_response(items)


@app.get("/api/learners/{id}/roadmap/archived")
def get_learner_archived_roadmap(id: int):
    return get_learner_roadmap(id=id, archived=1)


# 5. PATCH /api/learners/{id}/roadmap/{item_id} (mark completed)
@app.patch("/api/learners/{id}/roadmap/{item_id}")
def mark_roadmap_item(id: int, item_id: int, payload: Optional[RoadmapPatchRequest] = None):
    new_status = payload.status if payload and payload.status else "completed"
    if new_status not in ("pending", "completed"):
        return error_response("Invalid status (must be pending or completed)", status_code=400)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, resource_title, skill FROM roadmap_items WHERE id = ? AND learner_id = ?",
        (item_id, id),
    )
    item = cur.fetchone()
    if not item:
        conn.close()
        return error_response("Roadmap item not found for learner", status_code=status.HTTP_404_NOT_FOUND)

    title = item["resource_title"]
    skill = item["skill"]

    with conn:
        cur.execute(
            "UPDATE roadmap_items SET status = ? WHERE id = ? AND learner_id = ?",
            (new_status, item_id, id),
        )
        if new_status == "completed":
            cur.execute(
                "INSERT INTO events (learner_id, message) VALUES (?, ?)",
                (id, f"Completed learning activity: '{title}' for {skill}."),
            )
    conn.close()

    return success_response({"id": item_id, "status": new_status, "resource_title": title})


# 6. GET /api/assessments/{skill} (questions only, no correct answers exposed)
@app.get("/api/assessments/{skill}")
def get_assessment_questions(skill: str):
    assessments_cat = orchestrator._get_assessments_catalog()
    questions = assessments_cat.get(skill)
    if not questions:
        return error_response(f"No assessment found for skill '{skill}'", status_code=status.HTTP_404_NOT_FOUND)

    # Server-side safety: strip correct_answer and concept from response
    public_questions = [
        {
            "id": q["id"],
            "question": q["question"],
            "options": q["options"],
        }
        for q in questions
    ]
    return success_response({"skill": skill, "questions": public_questions})


# 7. POST /api/learners/{id}/assessments
@app.post("/api/learners/{id}/assessments")
def submit_learner_assessment(id: int, payload: SubmitAssessmentRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM learners WHERE id = ?", (id,))
    if not cur.fetchone():
        conn.close()
        return error_response("Learner not found", status_code=status.HTTP_404_NOT_FOUND)
    conn.close()

    try:
        res = orchestrator.submit_assessment(
            learner_id=id,
            skill=payload.skill,
            answers=payload.answers,
        )
        return success_response(res)
    except ValueError as ve:
        return error_response(str(ve), status_code=status.HTTP_400_BAD_REQUEST)


# 8. POST /api/learners/{id}/target-role
@app.post("/api/learners/{id}/target-role")
def change_learner_target_role(id: int, payload: TargetRoleRequest):
    try:
        res = orchestrator.change_target_role(learner_id=id, new_role=payload.role)
        return success_response(res)
    except ValueError as ve:
        return error_response(str(ve), status_code=status.HTTP_400_BAD_REQUEST)


# 9. GET /api/learners/{id}/progress
@app.get("/api/learners/{id}/progress")
def get_learner_progress(id: int):
    try:
        prog = orchestrator.compute_readiness(learner_id=id)
        return success_response(prog)
    except ValueError as ve:
        return error_response(str(ve), status_code=status.HTTP_404_NOT_FOUND)


# 10. GET /api/learners/{id}/agent-log
@app.get("/api/learners/{id}/agent-log")
def get_learner_agent_log(id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM learners WHERE id = ?", (id,))
    if not cur.fetchone():
        conn.close()
        return error_response("Learner not found", status_code=status.HTTP_404_NOT_FOUND)
    conn.close()

    logs = orchestrator.get_latest_agent_logs(learner_id=id)
    return success_response(logs)


# 11. POST /api/mentor
@app.post("/api/mentor")
def ask_mentor(payload: MentorQuestionRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, target_role FROM learners WHERE id = ?", (payload.learner_id,))
    learner = cur.fetchone()
    conn.close()

    learner_name = learner["name"] if learner else "Learner"
    target_role = learner["target_role"] if learner else "Software Engineer"

    mentor_input = {
        "event_type": "learner_query",
        "context": {
            "learner_name": learner_name,
            "target_role": target_role,
            "query": payload.question,
        },
    }
    mentor_out = orchestrator.career_mentor.run(mentor_input)

    # Log interaction to events if learner exists
    if learner:
        orchestrator._log_event(
            payload.learner_id,
            f"Learner asked Mentor: '{payload.question[:60]}...'. Mentor replied.",
        )

    return success_response({
        "question": payload.question,
        "message": mentor_out.get("message", ""),
        "source": mentor_out.get("source", "template"),
    })


# 12. GET /api/roles
@app.get("/api/roles")
def get_roles():
    roles = orchestrator._get_roles_catalog()
    return success_response(roles)


# Mount static directory for any static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
