# SkillPilot AI

> **Understand Your Skills. Discover Your Gaps. Navigate Your Career.**

An AI-powered personalized learning and career navigation platform built for the **Promptwar Solo Hackathon**.

SkillPilot AI solves the fundamental flaw of traditional e-learning platforms—recommending identical static course lists to every student. By orchestrating a specialized team of autonomous software agents, SkillPilot analyzes self-reported and validated proficiencies, identifies critical missing and weak skill gaps against target roles, constructs personalized prerequisite-ordered roadmaps, and dynamically adapts when learners struggle with assessments or pivot their career goals.

---

## Architecture Overview

SkillPilot AI uses a clean, decoupled architecture: a FastAPI backend powered by standard library SQLite3 and Pydantic validation, a single-page reactive dashboard built with vanilla JavaScript and Tailwind CSS (CDN), and an asynchronous multi-agent coordination loop.

```
                              +---------------------------------------+
                              |      Single-Page Web Dashboard        |
                              |   (vanilla JS + Tailwind CSS CDN)     |
                              +-------------------+-------------------+
                                                  | REST (JSON)
                                                  v
+-------------------------------------------------------------------------------------------------+
|                                    FastAPI Application (main.py)                                 |
|                                12 Normalized REST API Endpoints                                 |
+-------------------------------------------------+-----------------------------------------------+
                                                  |
                                                  v
+-------------------------------------------------------------------------------------------------+
|                                Orchestrator Engine (orchestrator.py)                            |
|             Runs agents with shared run_id, passes structured context, manages event logs       |
+---------+--------------------+---------------------+--------------------+-----------------------+
          |                    |                     |                    |
          v                    v                     v                    v
  +---------------+    +---------------+    +-------------------+  +-------------------+
  | Skill Analyst |    | Career Analyst|    | Learning Architect|  | Progress Evaluator|
  |  (Proficiency |    | (Role Gap &   |    | (Prerequisite     |  | (Assessment &     |
  |   Evaluation) |    |  Transferable)|    |  Roadmap Gen)     |  |  Weak Concepts)   |
  +-------+-------+    +-------+-------+    +---------+---------+  +---------+---------+
          |                    |                      |                      |
          +--------------------+----------------------+----------------------+
                                         |
                                         v
                              +---------------------+
                              |    Career Mentor    |
                              |  (Gemini REST with  |
                              |   Template Fallback)|
                              +----------+----------+
                                         |
                                         v
+-------------------------------------------------------------------------------------------------+
|                                  SQLite3 Database (skillpilot.db)                               |
|        learners | learner_skills | assessments | roadmap_items | events | agent_runs          |
+-------------------------------------------------------------------------------------------------+
```

---

## Multi-Agent System

Every learner interaction initiates an orchestration run with a shared `run_id`. Downstream agents consume structured outputs from upstream agents, logging real execution timestamps and durations directly to the `agent_runs` table:

1. **Skill Analyst Agent** (`agents/skill_analyst.py`)
   - **Responsibility**: Ingests baseline self-reported skills and recent assessment records to determine effective proficiency levels.
   - **Boundary**: Segregates validated and claimed proficiencies into `strong` and `weak` categories.
   - **Output**: `{"strong": [...], "weak": [...], "levels": {skill: level}}`.

2. **Career Analyst Agent** (`agents/career_analyst.py`)
   - **Responsibility**: Compares the learner's effective proficiencies against target career role benchmarks.
   - **Boundary**: Identifies mandatory skills, missing skills, developing skills, and transferable skills.
   - **Output**: `{"required": [...], "missing": [...], "weak": [...], "transferable": [...]}`.

3. **Learning Architect Agent** (`agents/learning_architect.py`)
   - **Responsibility**: Builds a customized learning roadmap from the course catalog.
   - **Boundary**: Filters out completed courses, orders milestones strictly by prerequisite dependency chains, matches resource difficulty to learner level, and prioritizes high-impact remedial modules.
   - **Output**: `{"roadmap": [{"position": int, "skill": str, "resource_title": str, "resource_type": str, "is_remedial": bool}]}`.

4. **Progress Evaluator Agent** (`agents/progress_evaluator.py`)
   - **Responsibility**: Evaluates submitted assessment answers against objective criteria without exposing correct answers to clients.
   - **Boundary**: Flags specific missed concepts (e.g. closures, async), applies performance score thresholds (<50%, 50-79%, 80-100%), and signals when roadmap restructuring is needed.
   - **Output**: `{"score": float, "passed": bool, "weak_concepts": [...], "validated_level": str, "needs_roadmap_update": bool}`.

5. **Career Mentor Agent** (`agents/career_mentor.py`)
   - **Responsibility**: Formulates encouraging, context-aware career guidance for milestone achievements, assessment outcomes, and career pivots.
   - **Boundary**: Calls Google Gemini via REST (5-second timeout, 1 retry). If the key is missing, network is offline, or the call fails, it instantly falls back to deterministic expert templates without blocking the application.
   - **Output**: `{"message": str, "source": "gemini" | "template"}`.

---

## Business Logic & Rules

### Role Readiness Calculation
- **Claimed Level**: Self-reported proficiency from learner registration.
- **Validated Level**: Established exclusively via objective assessment results.
- **Intermediate Cap**: Unassessed skills are strictly capped at Intermediate credit (65%), regardless of self-reported claims.
- **Proficiency Values**:
  - Missing = `0%`
  - Beginner = `25%`
  - Intermediate = `65%`
  - Advanced = `100%`
- **Per-Skill Credit**: `min(learner_pct, required_pct) / required_pct`
- **Overall Readiness**: Average credit across all required skills in the target role.
- **Non-Conflation**: Readiness is **never** derived from course completion checkboxes. Completed activities are tracked and displayed separately.
- **Mandatory Disclaimer**: All readiness displays bear the label:
  > *"Estimated indicator, not a guaranteed job-readiness score."*

### Adaptive Assessment Handling
- **Score < 50%**: Keeps claimed level, flags missed concepts, and immediately inserts targeted remedial resources at **Position #1** (the top) of the active learning roadmap.
- **Score 50% – 79%**: Upgrades validated level to `Intermediate`, recommending additional practice exercises.
- **Score 80% – 100%**: Upgrades validated level to `Advanced`, marks the skill passed, and advances the learner to the next prerequisite-satisfied skill in the curriculum.
- **Mastery Integrity**: Completing a course is never claimed to prove mastery.

### Career Goal Pivots
- Recalculates required, missing, weak, and transferable skills for the new career role.
- Archives incomplete (`status = 'pending'`) roadmap items from the previous role (`archived = 1`).
- **Preservation Guarantee**: Completed activities and historical assessment records are **never deleted or archived**.
- Generates a fresh, prerequisite-ordered roadmap tailored to the new domain.
- Identifies and highlights transferable skills (e.g., Python and SQL moving from Full Stack to Data Science).

---

## Technology Stack

- **Backend**: Python 3.14 / 3.10+, FastAPI, SQLite3 (standard library, zero ORM), Pydantic v2.
- **Frontend**: Single-page application (`static/index.html`), vanilla JavaScript (ES6+), Tailwind CSS (CDN). No build step, no Node.js runtime, zero `node_modules`.
- **AI & Fallback**: Google Gemini REST API (`gemini-1.5-flash`) via `httpx` with 5s timeout and deterministic template fallback. Works 100% offline without an API key.
- **Storage**: SQLite3 with foreign keys enabled (`PRAGMA foreign_keys = ON;`) and cascade deletes.

---

## Project Structure

```
skillpilot/
  main.py                  FastAPI app, routes, serves index.html
  db.py                    SQLite connection and schema creation
  seed.py                  Idempotent seed data validator and initializer
  orchestrator.py          Multi-agent coordinator, run logging, adaptive loop
  agents/
    base.py                Base agent interface
    skill_analyst.py       Proficiency & baseline skill evaluation
    career_analyst.py      Career gap & transferable skills mapping
    learning_architect.py  Prerequisite-ordered roadmap construction
    progress_evaluator.py  Objective scoring & weak concept detection
    career_mentor.py       Gemini REST client & deterministic templates
  data/
    roles.json             Full Stack Developer & Data Scientist benchmark profiles
    courses.json           28 learning resources across 11 skills + remedial courses
    assessments.json       Server-side MCQs (functions, closures, async)
  static/
    index.html             Single-page responsive dashboard UI
  requirements.txt         Minimal dependencies
  .env.example             Environment configuration template
  .gitignore               Git exclusion rules
  README.md                Documentation & walkthrough
```

---

## Setup & Running Locally

### 1. Clone & Enter Repository
```bash
git clone <repository_url>
cd hacktoskill
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. (Optional) Configure Gemini API Key
```bash
cp .env.example .env
# Edit .env and supply GEMINI_API_KEY=your_key_here
```
> **Note**: SkillPilot AI functions completely without an API key. When omitted, the platform uses deterministic expert guidance templates.

### 4. Run Seed & Data Verification
```bash
python seed.py
```
> `seed.py` is safe to run multiple times; it will never overwrite or erase existing learner profiles.

### 5. Start Application Server
```bash
uvicorn main:app --reload
```
Open your browser at: **`http://localhost:8000`**

---

## Step-by-Step Demo Walkthrough

Follow this exact walkthrough to verify all 15 required evaluation criteria:

1. **Launch Dashboard**: Open `http://localhost:8000`.
2. **Auto-Fill Demo Student**: Click the green **"Auto-Fill Demo Student"** button in the header.
   - Name: `Demo Student`
   - Role: `Full Stack Developer`
   - Skills: `Python (Intermediate)`, `SQL (Intermediate)`, `HTML (Beginner)`
3. **Analyze Gaps**: Click **"Analyze Gaps & Generate Roadmap"**.
   - **Missing Skills**: `JavaScript`, `React`, `Node.js`, `CSS`, `REST APIs` (Red badges).
   - **Weak Skills**: `HTML` (Amber badge).
   - **Transferable / Strong Skills**: `Python`, `SQL` (Blue/Emerald badges).
4. **Inspect Initial Roadmap**: Observe 17 prerequisite-ordered milestones starting with foundational web concepts.
5. **Inspect Agent Activity Log**: Scroll down to the **Multi-Agent Execution Log** table. Notice real execution entries for `Skill Analyst`, `Career Analyst`, `Learning Architect`, and `Career Mentor` sharing one `run_id`.
6. **Check Initial Readiness**: Observe the readiness score (`29.8%`) displaying the mandatory estimate label.
7. **Simulate Failed Assessment (<50%)**:
   - In the **Skill Assessment** panel on the right, ensure `JavaScript` is selected.
   - Click **"Load Questions"**.
   - Click the amber **"Select Poor Answers (<50%)"** shortcut button (or select incorrect options).
   - Click **"Submit Assessment"**.
8. **Verify Adaptive Remediation**:
   - Score reports `0.0%` with weak concepts flagged: `closures`, `functions`, `async`.
   - Notice the high-priority remedial resource: *"JavaScript fundamentals: functions and closures"* is automatically inserted at **Position #1** at the top of the roadmap with a pulsing **"Remedial Focus"** badge.
   - The Career Mentor immediately updates with actionable advice explaining the weak concepts.
9. **Mark Activity Completed**:
   - On the roadmap, check the box next to any activity.
   - Notice it is recorded under **"Completed Learning Activities"** separately from the readiness score.
10. **Perform Career Pivot**:
    - In the top banner, select **"Data Scientist"** from the Career Pivot dropdown.
    - Click **"Switch Goal"**.
    - Notice that `Python` and `SQL` are immediately recognized as **Transferable Skills** toward Data Science.
    - Historical assessments and completed items are preserved.
    - Incomplete Full Stack items are archived, and a fresh Data Science roadmap (Statistics, Pandas, Machine Learning) is generated.
    - The readiness indicator recalculates dynamically to `40.0%`.

---

## REST API Reference

Every endpoint returns a normalized response envelope:
`{"ok": bool, "data": Any, "error": Optional[str]}`

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/learners` | Register profile, analyze gaps, generate initial roadmap |
| `GET` | `/api/learners/{id}` | Retrieve learner profile and recorded skills |
| `GET` | `/api/learners/{id}/gap` | Retrieve gap analysis (missing, weak, transferable) |
| `GET` | `/api/learners/{id}/roadmap` | Retrieve active prerequisite-ordered roadmap items |
| `PATCH`| `/api/learners/{id}/roadmap/{item_id}` | Mark a roadmap milestone as completed |
| `GET` | `/api/assessments/{skill}` | Retrieve MCQs (server-side answers securely stripped) |
| `POST` | `/api/learners/{id}/assessments` | Submit assessment, evaluate score, adapt roadmap |
| `POST` | `/api/learners/{id}/target-role` | Pivot career goal, archive old items, recalculate gaps |
| `GET` | `/api/learners/{id}/progress` | Compute readiness percentage and fetch completed items |
| `GET` | `/api/learners/{id}/agent-log` | Retrieve execution details for the latest agent run |
| `POST` | `/api/mentor` | Ask Career Mentor a direct question |
| `GET` | `/api/roles` | List available career roles and skill benchmarks |

---

## License & Integrity

Developed for the Promptwar Hackathon under strict compliance with specification rules: zero ORM, standard library SQLite, vanilla JavaScript, no heavy frameworks, and 100% deterministic local reliability.
