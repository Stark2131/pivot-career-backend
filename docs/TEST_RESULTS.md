# Test results

Run on 2026-10-31 with Python 3.13.18. LLM calls are mocked.

## SQLite (default)
```
tests/test_ai_client.py::test_openai_success_and_headers PASSED
tests/test_ai_client.py::test_gemini_success PASSED
tests/test_ai_client.py::test_invalid_output_retries_then_fails PASSED
tests/test_ai_client.py::test_http_errors_and_timeouts_become_llm_errors PASSED
tests/test_ai_client.py::test_unconfigured_provider_is_unavailable PASSED
tests/test_ai_client.py::test_wrap_untrusted_neutralises_spoofed_markers PASSED
tests/test_applications.py::test_wilson_interval PASSED
tests/test_applications.py::test_analytics_flags_insufficient_data PASSED
tests/test_applications.py::test_analytics_patterns_with_enough_data PASSED
tests/test_applications.py::test_application_crud_and_status_tracking PASSED
tests/test_applications.py::test_application_analytics_llm_narrative PASSED
tests/test_auth.py::test_register_login_me PASSED
tests/test_auth.py::test_duplicate_registration_conflicts PASSED
tests/test_auth.py::test_weak_password_rejected PASSED
tests/test_auth.py::test_wrong_password PASSED
tests/test_auth.py::test_protected_routes_require_token PASSED
tests/test_auth.py::test_rate_limiter_blocks_after_limit PASSED
tests/test_e2e.py::test_full_user_journey PASSED
tests/test_interviews.py::test_interview_flow_with_fallbacks PASSED
tests/test_interviews.py::test_llm_evaluation_overall_computed_server_side PASSED
tests/test_interviews.py::test_out_of_range_llm_scores_rejected PASSED
tests/test_interviews.py::test_reanswer_clears_evaluation_and_isolation PASSED
tests/test_interviews.py::test_evaluate_without_answers_conflicts PASSED
tests/test_interviews.py::test_heuristic_never_awards_top_marks_and_penalises_empty PASSED
tests/test_jobs.py::test_create_job_rule_based PASSED
tests/test_jobs.py::test_create_job_with_llm_normalises_and_grounds PASSED
tests/test_jobs.py::test_manual_job_entry_and_crud PASSED
tests/test_jobs.py::test_job_requires_input PASSED
tests/test_jobs.py::test_jobs_are_isolated_between_users PASSED
tests/test_jobs.py::test_url_fetch_blocks_private_addresses PASSED
tests/test_jobs.py::test_html_to_text_strips_scripts PASSED
tests/test_plans.py::test_schedule_respects_weekly_hours PASSED
tests/test_plans.py::test_generate_plan_and_complete_task PASSED
tests/test_plans.py::test_plan_with_llm_content_validated PASSED
tests/test_plans.py::test_adjust_creates_proposal_and_preserves_original PASSED
tests/test_plans.py::test_regenerate_does_not_overwrite_active PASSED
tests/test_plans.py::test_project_recommendations PASSED
tests/test_plans.py::test_llm_projects_must_cover_gaps PASSED
tests/test_profile.py::test_resume_upload_rule_based_fallback PASSED
tests/test_profile.py::test_resume_upload_with_llm_drops_hallucinated_skills PASSED
tests/test_profile.py::test_invalid_llm_json_falls_back PASSED
tests/test_profile.py::test_upload_rejects_non_pdf_and_large_files PASSED
tests/test_profile.py::test_user_reviews_and_corrects_profile PASSED
tests/test_profile.py::test_profile_validation PASSED
tests/test_progress.py::test_detect_struggles_rules PASSED
tests/test_progress.py::test_tool_registry_validates_names_and_args PASSED
tests/test_progress.py::test_progress_overview_and_assessment PASSED
tests/test_progress.py::test_progress_analyst_tool_calling PASSED
tests/test_progress.py::test_recalculate_plan_proposes_without_overwriting PASSED
tests/test_progress.py::test_recalculate_requires_active_plan PASSED
tests/test_skill_gap.py::test_compute_gaps_logic PASSED
tests/test_skill_gap.py::test_analyze_endpoint PASSED
tests/test_skill_gap.py::test_analyze_llm_cannot_change_facts PASSED
tests/test_skill_gap.py::test_analyze_requires_jobs_and_isolation PASSED
============================= 54 passed in 35.61s ==============================
```

## PostgreSQL 16
```
54 passed in 41.01s
```
