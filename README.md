# Career Pivot Coach — Backend

An AI-assisted FastAPI backend that helps people move into a new role. It does six things:

1. **Reads your resume** (PDF or Word) and works out which skills you have.
2. **Analyses many real job postings** for your target role (imported from a job board, or 20 built-in samples per role) and pulls out what they ask for.
3. **Compares the two** to find your skill gaps and decide which to work on first. The report says how many postings it is based on.
4. **Builds a weekly learning plan** that fits the hours you have, with curated free resources, and suggests **portfolio projects** ranked by how many of your top gaps they close.
5. **Runs text-based mock interviews** and scores your answers against a visible rubric, with the quote behind each score.
6. **Adapts by itself.** A weak interview answer, a self-assessment, or a skipped / too-hard task updates your skill level, re-ranks the gaps and proposes a new plan version with the reasons written out.
7. **Tracks your job applications** and learns which kinds of roles, channels and resumes get responses, saying "reliable" or "early signal" and never more than the data supports.

Works with **OpenAI or Gemini**. Also runs **without any AI provider**: every AI feature has a rule-based fallback, and every result records which one produced it in a `generated_by` field.

> **Just want to see it?** From the repository root run `./demo.sh` (macOS/Linux/Git Bash) or `.\demo.ps1` (Windows PowerShell). It
> installs, migrates, seeds a fictional demo user and starts both apps. See `../DEMO.md` for the 3-minute walkthrough.
>
> Architecture & DB diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Endpoint list: [`docs/API.md`](docs/API.md) · Live docs: `http://localhost:8000/docs`

---

## 1. Quick start

### Option A — Docker (recommended)

```bash
cd pivot-career-backend
cp .env.example .env          # set JWT_SECRET_KEY; optionally LLM_PROVIDER + API key
docker compose up --build     # starts Postgres + API, runs migrations automatically
# Swagger UI: http://localhost:8000/docs
```

### Option B — Local Python

Requires Python 3.12+ and PostgreSQL 14+ (or SQLite for local development: `DATABASE_URL=sqlite+aiosqlite:///./dev.db`).

```bash
cd pivot-career-backend
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

This creates Maya, a maths teacher moving into data analysis: a reviewed profile, 20 sample Data Analyst postings and the
skill-gap map built from them, a learning plan two weeks in, project recommendations, one past interview, and 50 applications
with deliberate patterns so the tracker has something to learn from. The person, companies, postings and application outcomes
are **fictional** and not real job-market data. The script drives the real API in-process, so every number you see (match
score, plan hours, interview scores, the tracker's insights) is computed by the actual application logic. It always uses the
built-in sample postings, even if a job-board key is configured, so the demo is reproducible.

Individual seeders (all idempotent): `python -m scripts.seed_jds` (20 sample postings for each of Data Analyst, Product Manager,
ML Engineer) and `python -m scripts.seed_applications [--reset]` (50 synthetic applications).

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
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-3.8-flash` | Google Gemini |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | `45` / `1` | Per-call timeout; corrective retries on invalid JSON |
| `MAX_RESUME_SIZE_MB` / `MAX_RESUME_PAGES` | `5` / `15` | Upload limits |
| `MAX_DOCUMENT_CHARS` | `30000` | Long documents are cut to this length before being sent to the LLM |
| `URL_FETCH_ENABLED` | `true` | Optional job-posting URL fetching |
| `JSEARCH_API_KEY` | *(empty)* | Optional. Live postings via JSearch on RapidAPI. Empty means the built-in sample postings are used. Keep it in `.env`, never in `.env.example` |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | *(empty)* | Optional. Live postings via Adzuna (its descriptions are short snippets) |
| `MARKET_CACHE_HOURS` | `24` | How long live job-board results are cached in the database |
| `RATE_LIMIT_ENABLED`, `AUTH_RATE_LIMIT_PER_MINUTE`, `AI_RATE_LIMIT_PER_MINUTE` | `true`, `20`, `30` | In-memory rate limits |
| `CORS_ORIGINS` | localhost and 127.0.0.1 on ports 3000 and 5173 | JSON list |

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
│   │   └── projects/  interviews/  progress/ (+ adaptation.py)  applications/ (+ analytics.py)
│   ├── ai/                     # AI orchestration (never touches the DB)
│   │   ├── client.py           # LLMClient: OpenAI/Gemini over httpx, JSON + Pydantic validation
│   │   ├── orchestrator.py     # the single entry point used by services
│   │   ├── schemas.py          # Pydantic contracts for every LLM output
│   │   ├── resume_parser.py  jd_extractor.py  skill_analyzer.py  planner.py
│   │   ├── project_recommender.py  interviewer.py  evaluator.py  resources.py
│   │   ├── progress_analyst.py  tools.py (validated tool calling)  application_analyst.py
│   └── utils/                  # skills_taxonomy.py, pdf.py, docx_text.py, url_fetch.py
├── data/                       # content, editable without touching code
│   ├── skills_taxonomy.json    # ~160 skills with synonyms and related skills
│   ├── jds/                    # 20 synthetic postings each for data_analyst / product_manager / ml_engineer
│   ├── resources.json          # curated free resources per skill (every URL was checked); the AI can only pick from this
│   ├── projects.json           # 31 portfolio project templates tagged with skills
│   └── rubric.json             # interview rubric: 5 dimensions x 5 anchored levels
├── alembic/                    # migrations 0001-0004
├── scripts/                    # seed_demo.py, seed_jds.py, seed_applications.py, demo_data.py, export_openapi.py
├── tests/                      # pytest suite (LLM always mocked)
├── docs/                       # ARCHITECTURE.md, architecture.svg, API.md, openapi.json
├── Dockerfile  docker-compose.yml  requirements*.txt  .env.example
```

---

## 4. The user journey (API)

| Step | Endpoint | What happens |
|---|---|---|
| 1 | `POST /api/auth/register`, `/login` | bcrypt-hashed password; JWT access token |
| 2 | `POST /api/profile/resume` (multipart `file`) | PDF or DOCX validated → text extracted → **Resume Parser**. Skills not found in the resume text are dropped and listed in `validation_warnings`. |
| 3 | `GET /api/profile` → `PUT /api/profile` | Review extracted data (`needs_review`), then correct the skill list and proficiency (1–5) and set target role, experience level and weekly hours. |
| 4 | `POST /api/jobs/import-market` | Import postings for your target role: live job board (if a key is set) → cache → built-in samples. Safe to repeat. |
| 4b | `POST /api/jobs` | Paste the JD `text`, give a `source_url`, or enter `required_skills` manually. Skills are normalised (e.g. "k8s" becomes Kubernetes) and split into required and preferred. |
| 5 | `POST /api/skill-gap/analyze` | `job_count` / `based_on` ("Based on 20 job postings"). Uses only postings for your target role unless you pick some. Per-skill report: `current_proficiency`, `required_proficiency`, `gap_level` (none/partial/missing), `importance` (frequency across JDs), `priority_rank`, `is_priority`, `explanation`, `job_references` |
| 6 | `POST /api/plans/generate` | Week-by-week tasks (skills, topics, activities, exercises, curated `resources`, hours, expected outcome) that never exceed your weekly hours |
| 7 | `PATCH /api/plans/{id}/tasks/{task_id}` | Mark a task completed, in progress or skipped; add notes and a difficulty rating (1–5) |
| 8 | `POST /api/projects/recommend`, `PATCH /api/projects/{id}` | Template-backed projects ranked by how many of your top gaps they close (`gaps_covered`); track their status and repo URL |
| 9 | `GET /api/interviews/rubric`, `POST /api/interviews` → `/answer` → `/evaluate` | Questions focus on your gaps. Answers are scored on 5 rubric criteria (0–10, shown with a 1–5 level); each score carries a quote from your answer (verified against it). The overall score is computed by the server. `/evaluate` also returns `adaptation`: what the closed loop did. |
| 10 | `GET /api/progress`, `POST /api/progress/assessments` | Tasks, consistency and streak, skill-level changes, interview trend, projects, and the areas where you're struggling. Add `?include_ai_insights=true` for the AI Progress Analyst. |
| 11 | automatic, or `POST /api/progress/recalculate-plan` / `/api/plans/{id}/adjust` | After an evaluated interview, an assessment, or a skipped / hard-rated task, proficiency moves (moving average of the rubric score), gaps are recomputed and a **proposed** plan version is created with `change_summary.reasons`, e.g. "SQL: average mock-interview score 1.2/10 → +5.5h (11.0h to 16.5h), starts week 1". `POST /api/plans/{id}/accept` or `/reject`. The current plan is never overwritten. |
| 12 | `/api/applications` (CRUD) + `GET /api/applications/analytics` + `GET /api/applications/recommendations` | Status tracking plus channel, company size, industry, resume version, work mode and posting URL. Analytics give response rates with 95% confidence intervals; recommendations turn them into up to 5 plain-English insights, "reliable" only if the group's interval does not overlap everyone else's, otherwise "early signal" |

Errors always look like `{"error": {"code": "...", "message": "...", "details": {}}}`. Pydantic validation
errors use FastAPI's standard 422 format.

---

## 5. How the AI is kept honest

| Component | The LLM decides | Code decides and enforces |
|---|---|---|
| Resume Parser | structured extraction | every skill must appear literally in the resume (name or alias) |
| JD extraction | required/preferred skills, responsibilities | grounding check; required wins over preferred when a skill is listed as both |
| Skill Gap Analyst | explanation wording only | gap levels, importance, priority, match score; a *related* skill gives at most a **partial** match |
| Learning Planner | topics/activities/exercises, and which of the listed resources fit | which skill goes in which week and for how many hours. Content for skills outside the schedule is discarded. Resource ids not in `data/resources.json` are ignored: the AI cannot add a link. |
| Project Recommender | rewording only | which templates are chosen (ranked by top-gap coverage), their skills, stack, difficulty and hours |
| Interviewer | questions + key points | count, skill normalisation, top-up from the question bank |
| Evaluator | 5 rubric scores (0–10) + feedback + evidence quotes | score range validation, temperature 0, rubric from `data/rubric.json`; the **overall score is the server-computed mean**; quotes that are not in the answer are dropped |
| Progress Analyst | coaching narrative via **tool calls** | allow-listed, read-only tools with Pydantic-validated arguments; struggle detection is rule-based |
| Application Analyst | narrative | all statistics, confidence intervals and "insufficient data" flags. The recommendations endpoint is fully deterministic |

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

The 121 tests cover:

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
- **Adaptive loop:** score → proficiency (moving average) → gap recompute → proposal with reasons, mastered skills removed, no proposal spam, skipped tasks, missing skills not invented.
- **Market postings:** role-family scoping, seed integrity, live JSearch via a mocked transport, cache, every failure falling back to the sample postings without leaking the key, HTTP status in the fallback reason.
- **Tracker:** new fields, legacy `Posting:` notes, reliable vs early-signal vs nothing, pending applications excluded, mirrored findings merged, the demo seed producing the intended insights.
- **Rubric & evidence, resources, project ranking, DOCX resumes** (tables, zip bombs, wrong types).
- **Resilience:** the whole journey with the AI provider down and returning garbage.
- **End to end:** register → resume → review → JDs → gap → plan → task → projects → interview → assessment → recalculate → accept → applications → analytics.

Latest run: **121 passed** on SQLite (see `docs/TEST_RESULTS.md`). PostgreSQL was not re-run after migrations 0002-0004. A Playwright smoke test
of the main flow lives in `../careerpivotfrontend/e2e` (`npm run test:e2e`).

---

## 8. Limitations

- Resumes must be text-based PDF or `.docx` (no OCR for scanned resumes, no legacy `.doc`). DOCX page count is an estimate (500 words per page).
- Skill alternatives in a JD ("AWS **or** GCP") are treated as separate requirements, so one of them shows up as a gap.
- The skill taxonomy is curated and English-only (~160 skills); a strict spelling repair handles typos in longer names (it never maps one skill to another). Unknown skills are kept but can't use alias matching or related-skill partial credit.
- The rule-based resume and JD parsers rely on common section headings and are less accurate than the LLM path; that's why users review the extracted data.
- Heuristic interview scoring measures coverage and structure, not correctness. Configure an LLM for real evaluation.
- Rate limiting is per process and resets on restart.
- Live postings need a job-board key. JSearch (RapidAPI, `/search-v2`) was verified against a real account: 10 postings imported, skills extracted, cache and de-duplication working. Adzuna is covered by tests only and returns short description snippets. A posting whose text yields no recognisable skills is left out of a gap report, so it can be based on slightly fewer postings than were imported. The 60 sample postings are synthetic.
- The recommendations compare each group with all other applications; with a small history they are suggestions, not findings (that is what the "early signal" label means).
- Resource links were checked when `data/resources.json` was built and can still move.
- Many job boards block automated fetching (robots.txt, JavaScript rendering, login walls). Pasting the JD is the primary path.
- There are no refresh tokens, no email verification and no password reset yet.
- Interview scores stay on a 0–10 scale internally; the rubric's 1–5 levels are bands of that scale.

## 9. Future improvements

- pgvector semantic search over saved JDs, plus "related skill" suggestions (as suggestions only, never as possessed skills).
- Background jobs (Redis + RQ/Celery or Arq) for slow AI calls, with streaming progress.
- Voice and WebSocket mock interviews; follow-up questions based on the previous answer.
- Official job-board APIs (e.g. Greenhouse/Lever public posting APIs) for JD import.
- Spaced-repetition quizzes to measure skill improvement objectively.
- Refresh tokens, account deletion/export (GDPR), audit log, per-user LLM cost tracking.
