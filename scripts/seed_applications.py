"""Generate 50 SYNTHETIC job applications for the demo user, with deliberate patterns, so the tracker has
something to learn from on first load.

    python -m scripts.seed_applications            # demo user; skips if [DEMO] applications already exist
    python -m scripts.seed_applications --reset    # delete the [DEMO] applications first, then re-create

Everything here is fictional and labelled "[DEMO]". The patterns are built in on purpose (outcomes follow exact
quotas, not random draws) so the demo is reproducible:

    channel         referral 80% response, recruiter ~40%, direct 20%, job board ~13%   (counted applications)
    industry        edtech responds more often than retail / finance (a tendency, not a rule)
    resume version  "v2-data" (analytics-focused) outperforms "v1-teaching"
    recency         6 applications are < 14 days old and unanswered: the tracker leaves them out, as it should

The tracker's recommendations are computed from these rows by the real code, not hard-coded.
"""
import argparse
import asyncio
from datetime import date, timedelta

import httpx

from app.main import app
from scripts.demo_data import DEMO_USER
from scripts.seed_jds import login_or_register

TITLES = ["Data Analyst", "Junior Data Analyst", "Business Intelligence Analyst", "Marketing Analyst",
          "Product Analyst", "Reporting Analyst", "Operations Analyst", "Analytics Associate"]
ADJ = ["Bright", "North", "Cedar", "Atlas", "Lumen", "Harbor", "Pine", "Quartz", "Maple", "Sable", "Vivid", "Summit", "Ember", "Willow"]
NOUN = ["Learning", "Health", "Retail", "Bank", "Freight", "Labs", "Media", "Energy", "Works", "Systems"]
SIZES = ["1-10", "11-50", "51-200", "201-1000", "1001+"]

# (channel, counted applications, how many reached an interview)
MATURED = [("referral", 10, 8), ("recruiter", 8, 3), ("direct", 10, 2), ("job_board", 16, 2)]
PENDING = [("direct", 3), ("job_board", 3)]       # recent and unanswered: excluded from the statistics
OFFER_AT = {0, 5, 10}                               # which responders (in order) received an offer
REJECTED_AT = {2, 6, 9, 13}                         # ...and which were rejected after interviewing


def build_demo_applications(today: date | None = None) -> list[dict]:
    """Returns create-payloads (plus a `_final_status` key for those that end rejected after an interview)."""
    today = today or date.today()
    rows: list[dict] = []
    resp_industries = ["edtech", "edtech", "nonprofit", "healthcare", "edtech", "retail", "finance"]
    other_industries = ["retail", "finance", "logistics", "edtech", "retail", "healthcare", "finance", "nonprofit"]
    responder_no = other_no = n = 0
    for channel, total, responded in MATURED:
        for k in range(total):
            n += 1
            final = None
            if k < responded:                                   # this application reached an interview
                industry = resp_industries[responder_no % len(resp_industries)]
                if responder_no in OFFER_AT:
                    status = "offer"
                else:
                    status = "interview"
                    final = "rejected" if responder_no in REJECTED_AT else None   # sticky "reached interview"
                responder_no += 1
            else:
                industry = other_industries[other_no % len(other_industries)]
                other_no += 1
                status = "rejected"
            rows.append(_row(n, today, channel, industry, status, final, days_ago=15 + (n * 7) % 100,
                             resume="v2-data" if (channel != "job_board" or k % 4 == 3) else "v1-teaching"))
    for channel, count in PENDING:
        for k in range(count):
            n += 1
            rows.append(_row(n, today, channel, other_industries[k % len(other_industries)], "applied", None,
                             days_ago=1 + (n * 3) % 10, resume="v2-data"))
    return rows


def _row(n: int, today: date, channel: str, industry: str, status: str, final: str | None, *, days_ago: int, resume: str) -> dict:
    title = TITLES[n % len(TITLES)]
    senior = "junior" if "Junior" in title or "Associate" in title else "mid"
    return {
        "company_name": f"[DEMO] {ADJ[n % len(ADJ)]} {NOUN[(n * 3) % len(NOUN)]} {n:02d}",
        "role_title": title,
        "applied_date": (today - timedelta(days=days_ago)).isoformat(),
        "status": status,
        "experience_level": senior,
        "skills_highlighted": ["SQL", "Excel", "Tableau"] if resume == "v2-data" else ["Communication", "Excel"],
        "posting_url": f"https://jobs.example.com/demo/{n}",
        "industry": industry,
        "company_size": SIZES[(n * 2) % len(SIZES)],
        "channel": channel,
        "resume_version": resume,
        "work_mode": ["remote", "hybrid", "onsite"][n % 3],
        "location": ["Austin, TX", "Chicago, IL", "Remote", "Denver, CO"][n % 4],
        "notes": "[DEMO] synthetic application",
        "_final_status": final,
    }


async def seed(client: httpx.AsyncClient, headers: dict, reset: bool = False) -> int:
    existing = [a for a in (await client.get("/api/applications", headers=headers)).json() if a["company_name"].startswith("[DEMO]")]
    if existing and not reset:
        print(f"{len(existing)} [DEMO] applications already exist; use --reset to recreate them.")
        return 0
    for a in existing:
        await client.delete(f"/api/applications/{a['id']}", headers=headers)
    created = 0
    for row in build_demo_applications():
        final = row.pop("_final_status")
        r = await client.post("/api/applications", headers=headers, json=row)
        r.raise_for_status()
        if final:
            (await client.patch(f"/api/applications/{r.json()['id']}", headers=headers, json={"status": final})).raise_for_status()
        created += 1
    return created


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default=DEMO_USER["email"])
    ap.add_argument("--password", default=DEMO_USER["password"])
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://seed", timeout=120) as client:
        headers = await login_or_register(client, args.email, args.password, DEMO_USER["full_name"])
        created = await seed(client, headers, args.reset)
        if created:
            rec = (await client.get("/api/applications/recommendations", headers=headers)).json()
            print(f"Created {created} applications. The tracker now says ({rec['n_counted']} counted):")
            for i in rec["insights"]:
                print(f"  [{i['confidence']}] {i['text']}")


if __name__ == "__main__":
    asyncio.run(main())
