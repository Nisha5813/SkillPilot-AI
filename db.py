import sqlite3
from pathlib import Path
from typing import Optional

DB_FILE_NAME = "skillpilot.db"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / DB_FILE_NAME

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 1. Learners
CREATE TABLE IF NOT EXISTS learners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    education TEXT NOT NULL DEFAULT '',
    target_role TEXT NOT NULL
);

-- 2. Learner Skills
CREATE TABLE IF NOT EXISTS learner_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    claimed_level TEXT NOT NULL CHECK (claimed_level IN ('Beginner', 'Intermediate', 'Advanced')),
    validated_level TEXT CHECK (validated_level IS NULL OR validated_level IN ('Beginner', 'Intermediate', 'Advanced')),
    FOREIGN KEY (learner_id) REFERENCES learners(id) ON DELETE CASCADE,
    UNIQUE (learner_id, skill)
);

CREATE INDEX IF NOT EXISTS idx_learner_skills_learner_id ON learner_skills(learner_id);

-- 3. Assessments
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 100),
    weak_concepts TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(weak_concepts) AND json_type(weak_concepts) = 'array'),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (learner_id) REFERENCES learners(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assessments_learner_id ON assessments(learner_id);
CREATE INDEX IF NOT EXISTS idx_assessments_learner_skill ON assessments(learner_id, skill);

-- 4. Roadmap Items
CREATE TABLE IF NOT EXISTS roadmap_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    resource_title TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('course', 'tutorial', 'exercise')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed')),
    position INTEGER NOT NULL CHECK (position >= 0),
    is_remedial INTEGER NOT NULL DEFAULT 0 CHECK (is_remedial IN (0, 1)),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    FOREIGN KEY (learner_id) REFERENCES learners(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_roadmap_items_learner ON roadmap_items(learner_id, archived, position);

-- 5. Events
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (learner_id) REFERENCES learners(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_learner_id ON events(learner_id);

-- 6. Agent Runs
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    learner_id INTEGER,
    agent_name TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
    input_summary TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    FOREIGN KEY (learner_id) REFERENCES learners(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_learner_id ON agent_runs(learner_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_run_id ON agent_runs(run_id);
"""


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return an open SQLite connection with foreign keys enabled and Row factory configured."""
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(target_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize all tables and indexes in the SQLite database."""
    conn = get_db(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized successfully at: {DEFAULT_DB_PATH}")
