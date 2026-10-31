# Career Pivot Coach — Backend

An AI-assisted FastAPI backend that helps people move into a new role. It does six things:

1. **Reads your resume** and works out which skills you have.
2. **Analyses job descriptions** you're targeting and pulls out what they ask for.
3. **Compares the two** to find your skill gaps and decide which to work on first.
4. **Builds a weekly learning plan** that fits the hours you have, and suggests **portfolio projects** that close those gaps.
5. **Runs text-based mock interviews** and scores your answers against a fixed rubric.
6. **Tracks your progress** (and adjusts the plan when you fall behind) and **your job applications** (with simple statistics that are honest about small samples).

Works with **OpenAI or Gemini**. Also runs **without any AI provider**: every AI feature has a rule-based fallback, and every result records which one produced it in a `generated_by` field.

> Architecture & DB diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Endpoint list: [`docs/API.md`](docs/API.md) · Live docs: `http://localhost:8000/docs`

---

## 1. Quick start

### Option A — Docker (recommended)

```bash
cd backend
cp .env.example .env          # set JWT_SECRET_KEY; optionally LLM_PROVIDER + API key
docker compose up --build     # starts Postgres + API, runs migrations automatically
# Swagger UI: http://localhost:8000/docs
```

### Option B — Local Python

Requires Python 3.12+ and PostgreSQL 14+.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                     # edit DATABASE_URL / JWT_SECRET_KEY
createdb career_coach                                    # or create it in pgAdmin
alembic upgrade head                                     # create tables
uvicorn app.main:app --reload
```

### Load demo data (optional)

```bash
python -m scripts.seed_demo --reset
# login: demo@careercoach.example / DemoPass123
```

The demo person, companies, job postings and application outcomes are **fictional** and labelled `[DEMO]`.
They are not real job-market data. The script drives the real API in-process, so every number you see,
such as the match score or plan hours, is computed by the actual application logic.

### Using Swagger

1. `POST /api/auth/register`, then `POST /api/auth/login`, and copy `access_token`.
2. Click **Authorize** (top right) and paste the token.
3. Follow the journey in section 4.

---

## 2. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/career_coach` | Async SQLAlchemy URL |
| `JWT_SECRET_KEY` | *(placeholder — change it)* | HS256 signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime |
| `LLM_PROVIDER` | `none` | `openai`, `gemini` or `none` (rule-based only) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | — / `gpt-4o-mini` / OpenAI | Any OpenAI-compatible endpoint works |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-2.0-flash` | Google Gemini |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `45` / `1` | Per-call timeout; corrective retries on invalid JSON |
| `MAX_RESUME_SIZE_MB` / `MAX_RESUME_PAGES` | `5` / `15` | Upload limits |
| `MAX_DOCUMENT_CHARS` | `30000` | Long documents are cut to this length before being sent to the LLM |
| `URL_FETCH_ENABLED` | `true` | Optional job-posting URL fetching |
| `RATE_LIMIT_ENABLED`, `AUTH_RATE_LIMIT_PER_MINUTE`, `AI_RATE_LIMIT_PER_MINUTE` | `true`, `20`, `30` | In-memory rate limits |
| `CORS_ORIGINS` | localhost:3000, 5173 | JSON list |

**External dependencies:** PostgreSQL (required), plus an OpenAI or Gemini API key (optional).
Redis and pgvector are **not** required (see section 6).

---

## 3. Project structure

```
backend/
├── app/
│   ├── main.py                 # app factory, CORS, error handlers, /health
│   ├── api/router.py           # mounts every module under /api
│   ├── core/                   # config, database, security (bcrypt/JWT), errors, rate_limit, deps
│   ├── models/                 # SQLAlchemy models (user.py, career.py, tracking.py)
│   ├── modules/                # one folder per feature: router.py → service.py (+ schemas.py)
│   │   ├── auth/  profile/  jobs/  skill_gap/  learning_plans/
│   │   └── projects/  interviews/  progress/  applications/ (+ analytics.py)
│   ├── ai/                     # AI orchestration (never touches the DB)
│   │   ├── client.py           # LLMClient: OpenAI/Gemini over httpx, JSON + Pydantic validation
│   │   ├── orchestrator.py     # the single entry point used by services
│   │   ├── schemas.py          # Pydantic contracts for every LLM output
│   │   ├── resume_parser.py  jd_extractor.py  skill_analyzer.py  planner.py
│   │   ├── project_recommender.py  interviewer.py  evaluator.py
│   │   ├── progress_analyst.py  tools.py (validated tool calling)  application_analyst.py
│   └── utils/                  # skills_taxonomy.py, pdf.py, url_fetch.py
├── alembic/                    # migrations (0001_initial_schema.py)
├── scripts/                    # seed_demo.py, demo_data.py, export_openapi.py
├── tests/                      # pytest suite (LLM always mocked)
├── docs/                       # ARCHITECTURE.md, architecture.svg, API.md, openapi.json
├── Dockerfile  docker-compose.yml  requirements*.txt  .env.example
```

---

## 4. The user journey (API)

| Step | Endpoint | What happens |
|---|---|---|
| 1 | `POST /api/auth/register`, `/login` | bcrypt-hashed password; JWT access token |
| 2 | `POST /api/profile/resume` (multipart `file`) | PDF validated → text extracted → **Resume Parser**. Skills not found in the resume text are dropped and listed in `validation_warnings`. |
| 3 | `GET /api/profile` → `PUT /api/profile` | Review extracted data (`needs_review`), then correct the skill list and proficiency (1–5) and set target role, experience level and weekly hours. |
| 4 | `POST /api/jobs` | Paste the JD `text`, give a `source_url`, or enter `required_skills` manually. Skills are normalised (e.g. "k8s" becomes Kubernetes) and split into required and preferred. |
| 5 | `POST /api/skill-gap/analyze` | Per-skill report: `current_proficiency`, `required_proficiency`, `gap_level` (none/partial/missing), `importance` (frequency across JDs), `priority_rank`, `is_priority`, `explanation`, `job_references` |
| 6 | `POST /api/plans/generate` | Week-by-week tasks (skills, topics, activities, exercises, hours, expected outcome) that never exceed your weekly hours |
| 7 | `PATCH /api/plans/{id}/tasks/{task_id}` | Mark a task completed, in progress or skipped; add notes and a difficulty rating (1–5) |
| 8 | `POST /api/projects/recommend`, `PATCH /api/projects/{id}` | Portfolio projects that each cover at least one real gap; track their status and repo URL |
| 9 | `POST /api/interviews` → `/answer` → `/evaluate` | Questions focus on your gaps. Answers are scored on 5 rubric criteria (0–10); the overall score is computed by the server. Key points are hidden until a question is evaluated. |
| 10 | `GET /api/progress`, `POST /api/progress/assessments` | Tasks, consistency and streak, skill-level changes, interview trend, projects, and the areas where you're struggling. Add `?include_ai_insights=true` for the AI Progress Analyst. |
| 11 | `POST /api/progress/recalculate-plan` or `/api/plans/{id}/adjust` | Creates a **proposed** new plan version with a `change_summary`. `POST /api/plans/{id}/accept` or `/reject`. The current plan is never overwritten. |
| 12 | `/api/applications` (CRUD) + `GET /api/applications/analytics` | Status tracking (applied/interview/rejected/offer) plus conversion rates by role, experience level and skills, with 95% confidence intervals and data-sufficiency flags |

Errors always look like `{"error": {"code": "...", "message": "...", "details": {}}}`. Pydantic validation
errors use FastAPI's standard 422 format.

---

## 5. How the AI is kept honest

| Component | The LLM decides | Code decides and enforces |
|---|---|---|
| Resume Parser | structured extraction | every skill must appear literally in the resume (name or alias) |
| JD extraction | required/preferred skills, responsibilities | grounding check; required wins over preferred when a skill is listed as both |
| Skill Gap Analyst | explanation wording only | gap levels, importance, priority, match score; a *related* skill gives at most a **partial** match |
| Learning Planner | topics/activities/exercises | which skill goes in which week and for how many hours. Content for skills outside the schedule is discarded. |
| Project Recommender | project ideas | each idea must cover at least one real gap skill, otherwise a template is used |
| Interviewer | questions + key points | count, skill normalisation, top-up from the question bank |
| Evaluator | 5 rubric scores (0–10) + feedback | score range validation, temperature 0, fixed rubric; the **overall score is the server-computed mean** |
| Progress Analyst | coaching narrative via **tool calls** | allow-listed, read-only tools with Pydantic-validated arguments; struggle detection is rule-based |
| Application Analyst | narrative | all statistics, confidence intervals and "insufficient data" flags |

Untrusted text (resumes, JDs, answers) is wrapped in delimiters, the model is told to treat it as data, and
spoofed delimiters are neutralised. None of the AI modules receive a DB session, so the LLM cannot execute
SQL, run code or see another user's data.

**Fallback labels in `generated_by` / `evaluator`:**

- `llm`: the AI provider produced the result.
- `llm_partial`: some plan tasks came from the AI and the rest from templates.
- `rule_based`: deterministic logic.
- `heuristic_fallback`: interview scoring without an LLM. Its scores are capped at 8/10, and the feedback says that correctness was not verified.
- `llm_tools`: the Progress Analyst answered using tool calls.

---

## 6. Design choices & trade-offs

- **Modular monolith.** One process, with modules communicating through service functions. There are no microservices.
- **No pgvector, for now.** A curated taxonomy of ~100 skills with aliases and "related" links gives exact, explainable matching. Unknown skills are kept as written. Embeddings would add fuzzy matching, but they risk claiming similarity where none exists. Adding a `skills.embedding` column and a "you may also know…" suggestion endpoint is a contained future change.
- **No Redis.** AI calls are bounded by `LLM_TIMEOUT_SECONDS`, and the rate limiter is in-memory. For multiple workers, back the limiter with Redis and move slow AI calls to a task queue.
- **No repository layer.** Services use the async SQLAlchemy session directly, which keeps the code easy to follow.

---

## 7. Tests

```bash
pytest -q                                   # fast: SQLite in a temp file, LLM mocked
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/career_coach_test pytest -q   # same suite on PostgreSQL
```

The test database is dropped and recreated before every test, so point `TEST_DATABASE_URL` at a throwaway database.

The 54 tests cover:

- **Auth:** register, login, `/me`, wrong password, invalid token, rate limiter.
- **Resume:** rule-based and LLM parsing, hallucinated skills dropped, invalid JSON triggering a retry and then the fallback, file type, size and signature checks, profile review.
- **Jobs:** extraction, grounding, manual entry, CRUD, cross-user isolation, SSRF guard, HTML stripping.
- **Skill gap:** gap logic (including related skill → partial), the LLM unable to change facts, isolation.
- **Plans:** weekly hours never exceeded, deferred skills, LLM content validation, task completion, versioned adjust/accept/reject, regeneration not overwriting the active plan.
- **Projects:** recommendations and gap-coverage validation.
- **Interviews:** heuristic and LLM evaluation, server-side overall score, out-of-range scores rejected, re-answering, isolation.
- **Progress:** struggle rules, tool registry validation, the tool-calling loop (including a rejected `run_sql` tool), proposals that leave the active plan intact.
- **Applications:** Wilson interval, insufficient-data flags, skill correlations, sticky interview flag, isolation, LLM narrative.
- **LLM client:** OpenAI and Gemini request/response shapes, retry, HTTP 500 and timeout handling, delimiter spoofing.
- **End to end:** register → resume → review → JDs → gap → plan → task → projects → interview → assessment → recalculate → accept → applications → analytics.

Latest run: **54 passed** on SQLite and **54 passed** on PostgreSQL 16.

---

## 8. Limitations

- Only text-based PDFs are supported (no OCR for scanned resumes); DOCX isn't supported.
- Skill alternatives in a JD ("AWS **or** GCP") are treated as separate requirements, so one of them shows up as a gap.
- The skill taxonomy is curated and English-only (~100 skills). Unknown skills are kept but can't use alias matching or related-skill partial credit.
- The rule-based resume and JD parsers rely on common section headings and are less accurate than the LLM path; that's why users review the extracted data.
- Heuristic interview scoring measures coverage and structure, not correctness. Configure an LLM for real evaluation.
- Rate limiting is per process and resets on restart.
- Many job boards block automated fetching (robots.txt, JavaScript rendering, login walls). Pasting the JD is the primary path.
- There are no refresh tokens, no email verification and no password reset yet.

## 9. Future improvements

- pgvector semantic search over saved JDs, plus "related skill" suggestions (as suggestions only, never as possessed skills).
- Background jobs (Redis + RQ/Celery or Arq) for slow AI calls, with streaming progress.
- Voice and WebSocket mock interviews; follow-up questions based on the previous answer.
- Official job-board APIs (e.g. Greenhouse/Lever public posting APIs) for JD import.
- Spaced-repetition quizzes to measure skill improvement objectively.
- Refresh tokens, account deletion/export (GDPR), audit log, per-user LLM cost tracking.
# pivot-career-backend
