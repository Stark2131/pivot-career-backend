"""DEMO DATA - entirely fictional.

The person, companies, job postings and application outcomes below are invented
for demonstrating the app. They are NOT real job-market data or statistics.
"""


def make_pdf(text: str) -> bytes:
    """Build a minimal, valid one-page PDF containing `text` (no extra dependencies)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    ops = ["BT", "/F1 10 Tf", "14 TL", "40 800 Td"] + [f"({esc(line)}) Tj T*" for line in text.split("\n")] + ["ET"]
    stream = "\n".join(ops).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


DEMO_USER = {"email": "demo@careercoach.example", "password": "DemoPass123", "full_name": "Demo User (fictional)"}

DEMO_RESUME = """Alex Rivera (DEMO - fictional person)
Data Analyst
Summary
Data analyst with 4 years of experience in retail analytics, moving into machine learning engineering.
Experience
Data Analyst - Demo Retail Co (2021 - Present)
Built Tableau dashboards used by regional managers
Wrote SQL queries on PostgreSQL to analyse sales and inventory
Automated weekly reporting with Python and Pandas
Junior Analyst - Example Logistics (2020 - 2021)
Maintained Excel models and presented findings to stakeholders
Education
B.Sc. Statistics
Example State University 2020
Projects
Customer churn analysis
Used Python and scikit-learn logistic regression to predict churn
Certifications
Google Data Analytics Certificate
Skills
SQL, Python, Pandas, Tableau, Excel, Statistics, Git, Communication
"""

DEMO_JOBS = [
    {"title": "Machine Learning Engineer", "company": "[DEMO] Nimbus AI", "text": """Machine Learning Engineer (DEMO posting - fictional)
Responsibilities:
Build and deploy machine learning models to production
Design REST APIs that serve model predictions
Monitor model performance and data drift
Requirements:
3+ years of experience with Python
Strong SQL skills
Experience with Machine Learning and scikit-learn
Experience with Docker and AWS
Bachelor's degree in Computer Science, Statistics or related field
Nice to have:
PyTorch, Kubernetes, MLOps experience
"""},
    {"title": "Junior ML Engineer", "company": "[DEMO] Orbit Labs", "text": """Junior ML Engineer (DEMO posting - fictional)
What you'll do:
Train and evaluate machine learning models
Build data pipelines with Python and SQL
Requirements:
Python, Machine Learning, Docker, Git
Familiarity with PostgreSQL
Preferred:
AWS, FastAPI, PyTorch
"""},
    {"title": "ML Platform Engineer", "company": "[DEMO] Quanta Health", "text": """ML Platform Engineer (DEMO posting - fictional)
Responsibilities:
Own CI/CD for model training and deployment
Build feature pipelines and model serving infrastructure
Requirements:
Python and SQL
Docker and Kubernetes
CI/CD with GitHub Actions
Experience with AWS or GCP
Nice to have:
MLOps tooling such as MLflow, Terraform
"""},
]

# (company, role, status, reached_interview, experience_level, skills_highlighted, days_ago)
DEMO_APPLICATIONS = [
    ("[DEMO] Nimbus AI", "Machine Learning Engineer", "interview", True, "mid", ["Python", "SQL", "Machine Learning"], 30),
    ("[DEMO] Orbit Labs", "Junior ML Engineer", "offer", True, "junior", ["Python", "SQL", "Docker"], 28),
    ("[DEMO] Quanta Health", "ML Platform Engineer", "rejected", False, "mid", ["Python", "SQL"], 27),
    ("[DEMO] Helix Bank", "Data Scientist", "rejected", False, "mid", ["Python", "Statistics"], 25),
    ("[DEMO] Lumen Retail", "Data Scientist", "applied", False, "mid", ["Python", "Statistics", "SQL"], 20),
    ("[DEMO] Vector Labs", "Machine Learning Engineer", "rejected", True, "mid", ["Python", "Docker", "SQL"], 18),
    ("[DEMO] Atlas Freight", "Junior ML Engineer", "interview", True, "junior", ["Python", "Docker", "SQL"], 15),
    ("[DEMO] Pine Insurance", "Data Scientist", "rejected", False, "senior", ["Python", "SQL"], 12),
    ("[DEMO] Nova Media", "Machine Learning Engineer", "applied", False, "mid", ["Python", "SQL"], 10),
    ("[DEMO] Kite Travel", "Junior ML Engineer", "rejected", False, "junior", ["Python", "SQL"], 8),
    ("[DEMO] Cedar Energy", "Machine Learning Engineer", "interview", True, "mid", ["Python", "Docker", "SQL"], 5),
    ("[DEMO] Iris Analytics", "Data Scientist", "applied", False, "mid", ["Python", "Statistics"], 2),
]
