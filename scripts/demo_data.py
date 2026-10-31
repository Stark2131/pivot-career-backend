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


DEMO_USER = {"email": "demo@careercoach.example", "password": "DemoPass123", "full_name": "Maya Chen (DEMO - fictional)"}

# Persona: a secondary-school maths teacher moving into data analysis. Entirely fictional.
DEMO_RESUME = """Maya Chen (DEMO - fictional person)
Mathematics Teacher
Summary
Mathematics teacher with 6 years of experience analysing student assessment data, now moving into data analysis.
Experience
Mathematics Teacher - Demo Valley High School (2020 - Present)
Built Excel gradebooks and pivot tables to track progress for 140 students
Analysed test-score trends with statistics and presented findings to the leadership team
Ran a department project to improve homework completion using weekly data reviews
Head of Mathematics Department - Demo Valley High School (2023 - Present)
Led a team of 6 teachers and presented results to parents and governors
Education
B.Sc. Mathematics
Example State University 2018
Projects
Attendance dashboard
Built a public Tableau dashboard of attendance patterns by week and year group
Certifications
Google Data Analytics Certificate (in progress)
Skills
Excel, Statistics, Tableau, SQL, Communication, Leadership, Problem Solving
"""
