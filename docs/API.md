# API Endpoints

Generated from the OpenAPI spec (`python -m scripts.export_openapi`). Interactive docs: `http://localhost:8000/docs`.

All `/api/*` endpoints except register/login require `Authorization: Bearer <token>`.

## Authentication

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/auth/register` | Register | 201, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/auth/login` | Login | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/auth/me` | Me | 200, 401, 404, 409, 429, 502 |

## Profile & Resume

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/profile/resume` | Upload a PDF resume; text is extracted and parsed into structured data for review | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/profile` | Get Profile | 200, 401, 404, 409, 429, 502 |
| `PUT` | `/api/profile` | Update intake details and review/correct extracted data | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/profile/resumes` | List Resumes | 200, 401, 404, 409, 429, 502 |
| `GET` | `/api/profile/resumes/{resume_id}` | Get Resume | 200, 401, 404, 409, 422, 429, 502 |

## Job Descriptions

| Method | Path | Summary | Responses |
|---|---|---|---|
| `GET` | `/api/jobs` | List Jobs | 200, 401, 404, 409, 429, 502 |
| `POST` | `/api/jobs` | Create Job | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/jobs/{job_id}` | Get Job | 200, 401, 404, 409, 422, 429, 502 |
| `DELETE` | `/api/jobs/{job_id}` | Delete Job | 204, 401, 404, 409, 422, 429, 502 |

## Skill Gap Analysis

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/skill-gap/analyze` | Analyze | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/skill-gap` | List Analyses | 200, 401, 404, 409, 429, 502 |
| `GET` | `/api/skill-gap/{analysis_id}` | Get Analysis | 200, 401, 404, 409, 422, 429, 502 |

## Learning Plans

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/plans/generate` | Generate a week-by-week plan (becomes 'proposed' if an active plan already exists) | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/plans` | List Plans | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/plans/{plan_id}` | Get Plan | 200, 401, 404, 409, 422, 429, 502 |
| `PATCH` | `/api/plans/{plan_id}/tasks/{task_id}` | Update Task | 200, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/plans/{plan_id}/adjust` | Propose an adjusted version (the original plan is preserved) | 201, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/plans/{plan_id}/accept` | Accept a proposed plan (archives the current one) | 200, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/plans/{plan_id}/reject` | Reject a proposed plan | 200, 401, 404, 409, 422, 429, 502 |

## Portfolio Projects

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/projects/recommend` | Recommend | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/projects` | List Projects | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/projects/{project_id}` | Get Project | 200, 401, 404, 409, 422, 429, 502 |
| `PATCH` | `/api/projects/{project_id}` | Update Project | 200, 401, 404, 409, 422, 429, 502 |

## Mock Interviews

| Method | Path | Summary | Responses |
|---|---|---|---|
| `GET` | `/api/interviews` | List Interviews | 200, 401, 404, 409, 429, 502 |
| `POST` | `/api/interviews` | Create Interview | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/interviews/{interview_id}` | Get Interview | 200, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/interviews/{interview_id}/answer` | Submit Answer | 200, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/interviews/{interview_id}/evaluate` | Evaluate | 200, 401, 404, 409, 422, 429, 502 |

## Progress Tracking

| Method | Path | Summary | Responses |
|---|---|---|---|
| `GET` | `/api/progress` | Get Progress | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/progress/assessments` | List Assessments | 200, 401, 404, 409, 429, 502 |
| `POST` | `/api/progress/assessments` | Create Assessment | 201, 401, 404, 409, 422, 429, 502 |
| `POST` | `/api/progress/recalculate-plan` | Propose a new plan version based on detected struggles (does not overwrite the current plan) | 201, 401, 404, 409, 422, 429, 502 |

## Application Tracker

| Method | Path | Summary | Responses |
|---|---|---|---|
| `POST` | `/api/applications` | Create | 201, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/applications` | List Apps | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/applications/analytics` | Analytics | 200, 401, 404, 409, 422, 429, 502 |
| `GET` | `/api/applications/{application_id}` | Get App | 200, 401, 404, 409, 422, 429, 502 |
| `PATCH` | `/api/applications/{application_id}` | Update | 200, 401, 404, 409, 422, 429, 502 |
| `DELETE` | `/api/applications/{application_id}` | Delete | 204, 401, 404, 409, 422, 429, 502 |

## Health

| Method | Path | Summary | Responses |
|---|---|---|---|
| `GET` | `/health` | Health | 200 |
