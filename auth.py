"""
SkillPilot AI - Authentication & Security Module
Provides password hashing (scrypt), session management, CSRF protection,
and login rate limiting using standard library tools.
"""

import datetime
import hashlib
import os
import re
import secrets
from typing import Optional, Tuple
from fastapi import Depends, HTTPException, Request, Response, status

from db import get_db

SESSION_COOKIE_NAME = "skillpilot_session"
CSRF_COOKIE_NAME = "skillpilot_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days
MAX_FAILED_LOGINS = 5
RATE_LIMIT_WINDOW_MINUTES = 5

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# --- Password Hashing & Verification (scrypt) ---

def hash_password(password: str) -> str:
    """Hash password using scrypt with a unique random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    n = 16384
    r = 8
    p = 1
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=32 * 1024 * 1024,
    )
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored scrypt hash in constant time."""
    if not password or not stored_hash:
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        _, n_str, r_str, p_str, salt_hex, hash_hex = parts
        n = int(n_str)
        r = int(r_str)
        p = int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=32 * 1024 * 1024,
        )
        return secrets.compare_digest(derived, expected)
    except Exception:
        return False


# --- Validation ---

def validate_email(email: str) -> str:
    """Validate and normalize email."""
    if not email:
        raise ValueError("Email address is required")
    email = email.strip().lower()
    if len(email) > 120 or not EMAIL_REGEX.match(email):
        raise ValueError("Please provide a valid email address")
    return email


def validate_password_strength(password: str) -> None:
    """Validate password length and character requirements."""
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[a-zA-Z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"[0-9!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one number or special character")


# --- Rate Limiting ---

def is_rate_limited(identifier: str, conn=None) -> bool:
    """Check if an email or IP has exceeded failed login attempts within window."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM login_attempts
            WHERE ip_or_email = ? AND success = 0
            AND attempted_at >= datetime('now', ? || ' minutes')
            """,
            (identifier, f"-{RATE_LIMIT_WINDOW_MINUTES}"),
        )
        count = cur.fetchone()[0]
        return count >= MAX_FAILED_LOGINS
    finally:
        if close_conn:
            conn.close()


def record_login_attempt(identifier: str, success: bool, conn=None) -> None:
    """Record a login attempt (successful or failed)."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        with conn:
            conn.execute(
                "INSERT INTO login_attempts (ip_or_email, success) VALUES (?, ?)",
                (identifier, 1 if success else 0),
            )
    finally:
        if close_conn:
            conn.close()


# --- Session & CSRF Token Management ---

def create_session(user_id: int, conn=None) -> Tuple[str, str]:
    """Create a new session record tied to user with raw session token and CSRF token."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        csrf_token = secrets.token_hex(32)
        
        # Calculate expiration time in UTC ISO format
        expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=SESSION_MAX_AGE_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")

        with conn:
            conn.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, csrf_token, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, token_hash, csrf_token, expires_at),
            )
        return raw_token, csrf_token
    finally:
        if close_conn:
            conn.close()


def delete_session(raw_token: str, conn=None) -> None:
    """Delete a session by raw session token."""
    if not raw_token:
        return
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with conn:
            conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))
    finally:
        if close_conn:
            conn.close()


def get_user_by_session_token(raw_token: str, conn=None) -> Optional[dict]:
    """Look up active user and session info from raw session token."""
    if not raw_token:
        return None
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.name, u.email, u.created_at, u.is_active,
                   s.csrf_token, s.expires_at, s.id AS session_id
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token_hash = ? AND s.expires_at > datetime('now') AND u.is_active = 1
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        if close_conn:
            conn.close()


# --- Cookie Helpers ---

COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")

def set_auth_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    """Set secure session (HttpOnly) and CSRF (script-accessible) cookies."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete session and CSRF cookies on logout."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")


# --- FastAPI Dependency Providers & Learner Authorization ---

def get_current_user(request: Request) -> Optional[dict]:
    """Dependency: Extract current authenticated user or return None."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_user_by_session_token(token)


def require_current_user(request: Request) -> dict:
    """Dependency: Require an active authenticated user; raises 401 if unauthenticated."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
        )
    return user


def verify_csrf(request: Request, user: dict = Depends(require_current_user)) -> None:
    """Dependency: Enforce CSRF protection for state-changing requests."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        submitted_token = request.headers.get(CSRF_HEADER_NAME)
        expected_token = user.get("csrf_token")
        if not submitted_token or not expected_token or not secrets.compare_digest(submitted_token, expected_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing CSRF token. Request rejected.",
            )


def authorize_learner_access(learner_id: int, request: Request, conn=None) -> dict:
    """
    Authorize access to a specific learner's data.
    Enforces IDOR protection, session ownership, and legacy isolation.

    Rules:
    1. If learner does not exist: raises 404 Not Found.
    2. If learner has user_id IS NOT NULL (registered user profile):
       - If unauthenticated: raises 401 Unauthorized.
       - If authenticated user id != learner.user_id: raises 403 Forbidden (cross-user IDOR access blocked).
       - If state-changing method (POST, PATCH, PUT, DELETE): enforces CSRF verification.
    3. If learner has user_id IS NULL (legacy demo record):
       - If authenticated: raises 403 Forbidden (legacy demo records are strictly isolated from user accounts).
       - If unauthenticated: allowed for read/demo access.

    Returns the learner row as a dictionary.
    """
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, education, target_role, user_id FROM learners WHERE id = ?", (learner_id,))
        learner = cur.fetchone()
        if not learner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found")

        learner_dict = dict(learner)
        learner_owner_id = learner_dict.get("user_id")
        current_user = get_current_user(request)

        # Case A: Learner belongs to a registered user
        if learner_owner_id is not None:
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to access this learner profile",
                )
            if current_user["id"] != learner_owner_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: you do not have permission to access this learner profile",
                )
            # Enforce CSRF on state changes
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                submitted_csrf = request.headers.get(CSRF_HEADER_NAME)
                expected_csrf = current_user.get("csrf_token")
                if not submitted_csrf or not expected_csrf or not secrets.compare_digest(submitted_csrf, expected_csrf):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invalid or missing CSRF token",
                    )

        # Case B: Legacy demo record (user_id IS NULL)
        else:
            if current_user:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: legacy demo records are isolated from registered user accounts",
                )
            # Unauthenticated guest demo access is allowed

        return learner_dict
    finally:
        if close_conn:
            conn.close()

