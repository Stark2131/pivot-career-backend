"""Tracker that learns: role attributes, per-dimension analytics and evidence-gated recommendations."""
from datetime import date, timedelta

from app.modules.applications.analytics import MAX_INSIGHTS, PENDING_DAYS, AppFact, build_recommendations, wilson

TODAY = date(2026, 10, 31)
OLD = TODAY - timedelta(days=60)


def fact(responded: bool, **kw) -> AppFact:
    base = dict(role_title="Data Analyst", status="interview" if responded else "rejected", reached_interview=responded,
                experience_level="mid", skills=[], role_family="data_analyst", applied_date=OLD)
    return AppFact(**{**base, **kw})


def group(n: int, responses: int, **kw) -> list[AppFact]:
    return [fact(i < responses, **kw) for i in range(n)]


def test_not_enough_applications_gives_no_insights():
    out = build_recommendations(group(6, 3, channel="referral"), today=TODAY)
    assert out["sufficient_data"] is False and out["insights"] == [] and "Log at least 10" in out["message"]


def test_clear_referral_effect_is_reliable_and_worded_plainly():
    apps = group(8, 6, channel="referral") + group(20, 3, channel="job_board")
    out = build_recommendations(apps, today=TODAY)
    top = out["insights"][0]
    assert (top["dimension"], top["group"], top["confidence"], top["direction"]) == ("channel", "referral", "reliable", "higher")
    assert top["ci95"][0] > top["rest_ci95"][1]                      # intervals do not overlap
    assert top["text"].startswith("Referrals: 75% reached an interview vs 15% for all other applications (n=8 vs 20).")
    assert top["suggestion"] == "Prioritise referrals where you can."
    assert not any(i["dimension"] == "channel" and i["group"] == "job_board" for i in out["insights"])  # mirror, not repeated
    assert out["baseline_response_rate"] == round(9 / 28, 3)


def test_three_groups_keep_both_the_best_and_the_worst():
    apps = group(8, 7, channel="referral") + group(10, 4, channel="direct") + group(12, 0, channel="job_board")
    ch = {i["group"]: i for i in build_recommendations(apps, today=TODAY)["insights"] if i["dimension"] == "channel"}
    assert ch["referral"]["direction"] == "higher" and ch["job_board"]["direction"] == "lower"


def test_overlapping_intervals_with_a_big_gap_are_only_an_early_signal():
    apps = group(6, 4, channel="recruiter") + group(14, 4, channel="direct")
    ins = [i for i in build_recommendations(apps, today=TODAY)["insights"] if i["group"] == "recruiter"]
    assert len(ins) == 1 and ins[0]["confidence"] == "early_signal"
    assert ins[0]["ci95"][0] <= ins[0]["rest_ci95"][1] and "early signal" in ins[0]["text"]


def test_no_difference_means_no_claim():
    apps = group(10, 3, channel="referral") + group(10, 3, channel="direct") + group(10, 3, channel="job_board")
    out = build_recommendations(apps, today=TODAY)
    assert out["sufficient_data"] and out["insights"] == [] and "No channel, role, resume or skill stands out" in out["message"]


def test_small_groups_are_never_reported():
    apps = group(4, 4, channel="referral") + group(26, 3, channel="direct")        # 4/4 looks perfect but n=4
    assert not [i for i in build_recommendations(apps, today=TODAY)["insights"] if i["group"] == "referral"]


def test_recent_unanswered_applications_do_not_count_as_failures():
    pending = [fact(False, status="applied", applied_date=TODAY - timedelta(days=3)) for _ in range(12)]
    answered = group(10, 5, channel="direct")
    out = build_recommendations(pending + answered, today=TODAY)
    assert out["excluded_recent_pending"] == 12 and out["n_counted"] == 10 and out["baseline_response_rate"] == 0.5
    old_pending = [fact(False, status="applied", applied_date=TODAY - timedelta(days=PENDING_DAYS + 1)) for _ in range(3)]
    assert build_recommendations(old_pending + answered, today=TODAY)["n_counted"] == 13


def test_insights_are_capped_and_reliable_ones_come_first():
    # crossed design: channel and industry split the applications differently
    apps = (group(10, 9, channel="referral", industry="Health") + group(10, 4, channel="referral", industry="Retail")
            + group(10, 2, channel="job_board", industry="Health") + group(10, 1, channel="job_board", industry="Retail"))
    out = build_recommendations(apps, today=TODAY)
    assert 2 <= len(out["insights"]) <= MAX_INSIGHTS
    conf = [i["confidence"] for i in out["insights"]]
    assert conf == sorted(conf, key=lambda c: c != "reliable") and conf[0] == "reliable"
    assert {"channel", "industry"} <= {i["dimension"] for i in out["insights"]}


def test_skill_insights_say_highlighting():
    apps = group(8, 7, skills=["Python"]) + group(12, 1, skills=["Excel"])
    texts = [i["text"] for i in build_recommendations(apps, today=TODAY)["insights"] if i["dimension"] == "skill"]
    assert any(t.startswith("Highlighting Python:") for t in texts)


def test_insights_about_the_same_applications_are_merged():
    apps = group(8, 7, resume_version="v2", skills=["Python"]) + group(12, 1, resume_version="v1", skills=["Excel"])
    dims = [i["dimension"] for i in build_recommendations(apps, today=TODAY)["insights"]]
    assert dims.count("resume_version") == 1 and "skill" not in dims


def test_wilson_is_unchanged():
    assert wilson(5, 10) == (0.237, 0.763) and wilson(0, 0) is None


# --- through the API ---------------------------------------------------------------------------------
def _payload(i, channel, responded, **kw):
    return {"company_name": f"Co {i}", "role_title": "Data Analyst",
            "applied_date": (date.today() - timedelta(days=40)).isoformat(),
            "status": "interview" if responded else "rejected", "channel": channel, **kw}


async def test_new_fields_are_stored_validated_and_posting_url_is_its_own_field(client, auth):
    r = await client.post("/api/applications", headers=auth, json={
        "company_name": "Acme", "role_title": "Senior Product Manager", "applied_date": "2026-10-01",
        "posting_url": "https://jobs.example.com/pm/123", "industry": "Fintech", "company_size": "51-200",
        "channel": "referral", "resume_version": "v2-product", "work_mode": "hybrid", "location": "Austin, TX",
        "notes": "Met the hiring manager at a meetup"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["posting_url"] == "https://jobs.example.com/pm/123" and a["notes"] == "Met the hiring manager at a meetup"
    assert (a["role_family"], a["channel"], a["company_size"], a["work_mode"]) == ("product_manager", "referral", "51-200", "hybrid")
    bad = await client.post("/api/applications", headers=auth, json={
        "company_name": "X", "role_title": "Y", "applied_date": "2026-10-01", "channel": "carrier pigeon"})
    assert bad.status_code == 422
    patched = await client.patch(f"/api/applications/{a['id']}", headers=auth,
                                 json={"channel": "recruiter", "posting_url": "https://jobs.example.com/pm/124"})
    assert patched.json()["channel"] == "recruiter" and patched.json()["posting_url"].endswith("/124")


async def test_analytics_breaks_results_down_by_the_new_dimensions(client, auth):
    for i in range(6):
        await client.post("/api/applications", headers=auth, json=_payload(i, "referral", True, resume_version="v2"))
    for i in range(6, 12):
        await client.post("/api/applications", headers=auth, json=_payload(i, "job_board", False, resume_version="v1"))
    stats = (await client.get("/api/applications/analytics?include_ai_summary=false", headers=auth)).json()["stats"]
    assert stats["by_channel"]["referral"]["response_rate"] == 1.0 and stats["by_channel"]["job_board"]["response_rate"] == 0.0
    assert stats["by_resume_version"]["v2"]["n"] == 6 and "data_analyst" in stats["by_role_family"]


async def test_recommendations_endpoint(client, auth):
    empty = (await client.get("/api/applications/recommendations", headers=auth)).json()
    assert empty["sufficient_data"] is False and empty["insights"] == []
    for i in range(8):
        await client.post("/api/applications", headers=auth, json=_payload(i, "referral", i < 6))
    for i in range(8, 28):
        await client.post("/api/applications", headers=auth, json=_payload(i, "job_board", i < 11))
    r = await client.get("/api/applications/recommendations", headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["sufficient_data"] and out["insights"][0]["group"] == "referral" and out["insights"][0]["confidence"] == "reliable"
    assert "Referrals: 75%" in out["insights"][0]["text"] and out["disclaimer"]
    other = await client.get("/api/applications/recommendations", headers=await _second_user(client))
    assert other.json()["n_applications"] == 0                      # isolated per user


async def _second_user(client):
    from tests.conftest import register_and_login
    return await register_and_login(client, email="bob@example.com")


# --- the demo seeder must really produce the story the demo tells --------------------------------------
async def test_demo_seed_produces_the_intended_insights(client, auth):
    from scripts.seed_applications import seed

    assert await seed(client, auth) == 50
    assert await seed(client, auth) == 0                       # idempotent without --reset
    assert await seed(client, auth, reset=True) == 50
    apps = (await client.get("/api/applications", headers=auth)).json()
    assert len(apps) == 50 and all(a["company_name"].startswith("[DEMO]") for a in apps)
    assert sum(1 for a in apps if a["status"] == "offer") == 3
    assert sum(1 for a in apps if a["status"] == "rejected" and a["reached_interview"]) == 4
    rec = (await client.get("/api/applications/recommendations", headers=auth)).json()
    assert rec["sufficient_data"] and rec["n_counted"] == 44 and rec["excluded_recent_pending"] == 6
    by = {(i["dimension"], i["group"]): i for i in rec["insights"]}
    assert by[("channel", "referral")]["confidence"] == "reliable" and by[("channel", "referral")]["response_rate"] == 0.8
    assert 3 <= len(rec["insights"]) <= 5
    assert any(i["dimension"] == "channel" and i["group"] == "job_board" and i["direction"] == "lower" for i in rec["insights"])
    sigs = [(i["n"], i["responses"], i["rest_n"]) for i in rec["insights"]]
    assert len(sigs) == len(set(sigs))                          # no two insights about the same applications


def test_wording_reads_naturally_per_dimension():
    apps = group(8, 7, resume_version="v2-data", experience_level="mid") + group(12, 1, resume_version="v1", experience_level="senior")
    texts = " | ".join(i["text"] for i in build_recommendations(apps, today=TODAY)["insights"])
    assert "Resume 'v2-data':" in texts or "Mid-level postings:" in texts
    assert "V2-data" not in texts
