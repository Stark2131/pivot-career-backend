"""A small, curated skill taxonomy used to normalise skill names.

Why not embeddings? Exact alias matching is predictable, explainable and never
claims a user has a skill "because it's semantically close". Related skills are
listed explicitly and only ever produce a *partial* match.

Each entry: canonical name -> {cat, aliases, related, hours}
  * aliases  – alternative spellings that normalise to the canonical name
  * related  – adjacent skills (transferable knowledge => partial match)
  * hours    – rough hours for a motivated learner to reach working proficiency
               (used only for scheduling; deliberately conservative)
"""
import re
from dataclasses import dataclass

_T: dict[str, dict] = {
    # --- Programming languages ---------------------------------------------
    "Python": {"cat": "programming_language", "aliases": ["python3", "py"], "related": ["R"], "hours": 30},
    "JavaScript": {"cat": "programming_language", "aliases": ["js", "ecmascript", "es6"], "related": ["TypeScript"], "hours": 30},
    "TypeScript": {"cat": "programming_language", "aliases": ["ts"], "related": ["JavaScript"], "hours": 15},
    "Java": {"cat": "programming_language", "aliases": ["java 8", "java 17"], "related": ["Kotlin", "C#"], "hours": 35},
    "Kotlin": {"cat": "programming_language", "aliases": [], "related": ["Java"], "hours": 25},
    "C#": {"cat": "programming_language", "aliases": ["c sharp", "csharp"], "related": ["Java", ".NET"], "hours": 35},
    "C++": {"cat": "programming_language", "aliases": ["cpp"], "related": ["C"], "hours": 45},
    "C": {"cat": "programming_language", "aliases": ["ansi c"], "related": ["C++"], "hours": 35},
    "Go": {"cat": "programming_language", "aliases": ["golang"], "related": [], "hours": 25},
    "Rust": {"cat": "programming_language", "aliases": [], "related": ["C++"], "hours": 45},
    "Ruby": {"cat": "programming_language", "aliases": [], "related": ["Ruby on Rails"], "hours": 25},
    "PHP": {"cat": "programming_language", "aliases": [], "related": [], "hours": 25},
    "Scala": {"cat": "programming_language", "aliases": [], "related": ["Java", "Apache Spark"], "hours": 35},
    "R": {"cat": "programming_language", "aliases": ["r programming", "rstudio"], "related": ["Python"], "hours": 25},
    "Swift": {"cat": "programming_language", "aliases": [], "related": ["iOS Development"], "hours": 30},
    "SQL": {"cat": "database", "aliases": ["t-sql", "pl/sql", "ansi sql", "sql queries"], "related": ["PostgreSQL", "MySQL"], "hours": 20},
    "Bash": {"cat": "tools", "aliases": ["shell scripting", "bash scripting", "shell"], "related": ["Linux"], "hours": 10},
    # --- Backend ------------------------------------------------------------
    "FastAPI": {"cat": "backend", "aliases": ["fast api"], "related": ["Flask", "Django"], "hours": 12},
    "Django": {"cat": "backend", "aliases": ["django rest framework", "drf"], "related": ["Flask", "FastAPI"], "hours": 20},
    "Flask": {"cat": "backend", "aliases": [], "related": ["FastAPI", "Django"], "hours": 12},
    "Node.js": {"cat": "backend", "aliases": ["nodejs", "node"], "related": ["Express.js"], "hours": 20},
    "Express.js": {"cat": "backend", "aliases": ["express", "expressjs"], "related": ["Node.js"], "hours": 10},
    "Spring Boot": {"cat": "backend", "aliases": ["spring", "spring framework"], "related": ["Java"], "hours": 30},
    ".NET": {"cat": "backend", "aliases": ["dotnet", "asp.net", ".net core", "asp.net core"], "related": ["C#"], "hours": 30},
    "Ruby on Rails": {"cat": "backend", "aliases": ["rails", "ror"], "related": ["Ruby"], "hours": 25},
    "REST APIs": {"cat": "backend", "aliases": ["rest", "restful", "restful apis", "rest api", "api design"], "related": ["GraphQL"], "hours": 12},
    "GraphQL": {"cat": "backend", "aliases": [], "related": ["REST APIs"], "hours": 12},
    "gRPC": {"cat": "backend", "aliases": [], "related": ["REST APIs"], "hours": 10},
    "Microservices": {"cat": "architecture", "aliases": ["microservice architecture", "micro-services"], "related": ["System Design"], "hours": 25},
    "System Design": {"cat": "architecture", "aliases": ["distributed systems", "software architecture", "scalable systems"], "related": ["Microservices"], "hours": 40},
    "Message Queues": {"cat": "backend", "aliases": ["rabbitmq", "message broker", "celery"], "related": ["Apache Kafka"], "hours": 12},
    "Apache Kafka": {"cat": "data", "aliases": ["kafka"], "related": ["Message Queues"], "hours": 20},
    # --- Frontend -----------------------------------------------------------
    "React": {"cat": "frontend", "aliases": ["react.js", "reactjs"], "related": ["Vue.js", "Angular", "Next.js"], "hours": 30},
    "Next.js": {"cat": "frontend", "aliases": ["nextjs"], "related": ["React"], "hours": 15},
    "Vue.js": {"cat": "frontend", "aliases": ["vue", "vuejs"], "related": ["React", "Angular"], "hours": 25},
    "Angular": {"cat": "frontend", "aliases": ["angularjs"], "related": ["React", "Vue.js"], "hours": 30},
    "HTML": {"cat": "frontend", "aliases": ["html5"], "related": ["CSS"], "hours": 8},
    "CSS": {"cat": "frontend", "aliases": ["css3", "sass", "scss", "tailwind", "tailwind css"], "related": ["HTML"], "hours": 12},
    "Redux": {"cat": "frontend", "aliases": [], "related": ["React"], "hours": 8},
    # --- Mobile -------------------------------------------------------------
    "iOS Development": {"cat": "mobile", "aliases": ["ios", "swiftui"], "related": ["Swift"], "hours": 40},
    "Android Development": {"cat": "mobile", "aliases": ["android"], "related": ["Kotlin"], "hours": 40},
    "React Native": {"cat": "mobile", "aliases": [], "related": ["React"], "hours": 25},
    "Flutter": {"cat": "mobile", "aliases": ["dart"], "related": [], "hours": 30},
    # --- Databases ----------------------------------------------------------
    "PostgreSQL": {"cat": "database", "aliases": ["postgres", "psql", "postgre"], "related": ["MySQL", "SQL"], "hours": 15},
    "MySQL": {"cat": "database", "aliases": ["mariadb"], "related": ["PostgreSQL", "SQL"], "hours": 12},
    "MongoDB": {"cat": "database", "aliases": ["mongo"], "related": ["NoSQL"], "hours": 12},
    "Redis": {"cat": "database", "aliases": [], "related": ["NoSQL"], "hours": 8},
    "NoSQL": {"cat": "database", "aliases": ["dynamodb", "cassandra", "nosql databases"], "related": ["MongoDB"], "hours": 12},
    "Elasticsearch": {"cat": "database", "aliases": ["elastic search", "opensearch"], "related": [], "hours": 12},
    "Data Modeling": {"cat": "data", "aliases": ["database design", "schema design", "dimensional modeling"], "related": ["SQL"], "hours": 15},
    "SQLAlchemy": {"cat": "backend", "aliases": [], "related": ["SQL", "Python"], "hours": 8},
    "Vector Databases": {"cat": "ml_ai", "aliases": ["pgvector", "pinecone", "weaviate", "faiss", "chroma", "vector database", "vector search"], "related": ["Embeddings"], "hours": 8},
    # --- Data ---------------------------------------------------------------
    "Pandas": {"cat": "data", "aliases": [], "related": ["NumPy", "Python"], "hours": 15},
    "NumPy": {"cat": "data", "aliases": ["numpy"], "related": ["Pandas"], "hours": 10},
    "Data Analysis": {"cat": "data", "aliases": ["data analytics", "exploratory data analysis", "eda"], "related": ["Statistics", "Pandas"], "hours": 25},
    "Data Visualization": {"cat": "data", "aliases": ["matplotlib", "seaborn", "plotly", "data viz"], "related": ["Tableau", "Power BI"], "hours": 12},
    "Tableau": {"cat": "data", "aliases": [], "related": ["Power BI", "Data Visualization"], "hours": 15},
    "Power BI": {"cat": "data", "aliases": ["powerbi"], "related": ["Tableau", "Data Visualization"], "hours": 15},
    "Excel": {"cat": "data", "aliases": ["microsoft excel", "spreadsheets", "ms excel"], "related": ["Data Analysis"], "hours": 10},
    "Statistics": {"cat": "data", "aliases": ["statistical analysis", "hypothesis testing", "a/b testing", "probability"], "related": ["Data Analysis"], "hours": 30},
    "ETL": {"cat": "data", "aliases": ["data pipelines", "elt", "data pipeline"], "related": ["Apache Airflow", "Data Modeling"], "hours": 20},
    "Apache Airflow": {"cat": "data", "aliases": ["airflow"], "related": ["ETL"], "hours": 12},
    "Apache Spark": {"cat": "data", "aliases": ["spark", "pyspark"], "related": ["ETL", "Scala"], "hours": 25},
    "dbt": {"cat": "data", "aliases": ["data build tool"], "related": ["SQL", "ETL"], "hours": 10},
    "Data Warehousing": {"cat": "data", "aliases": ["snowflake", "bigquery", "redshift", "data warehouse"], "related": ["Data Modeling", "SQL"], "hours": 20},
    # --- ML / AI ------------------------------------------------------------
    "Machine Learning": {"cat": "ml_ai", "aliases": ["ml", "machine-learning", "predictive modeling"], "related": ["Statistics", "Deep Learning"], "hours": 60},
    "Deep Learning": {"cat": "ml_ai", "aliases": ["neural networks", "dl"], "related": ["Machine Learning", "PyTorch"], "hours": 50},
    "scikit-learn": {"cat": "ml_ai", "aliases": ["sklearn", "scikit learn"], "related": ["Machine Learning"], "hours": 15},
    "PyTorch": {"cat": "ml_ai", "aliases": ["torch"], "related": ["TensorFlow", "Deep Learning"], "hours": 30},
    "TensorFlow": {"cat": "ml_ai", "aliases": ["keras", "tf"], "related": ["PyTorch", "Deep Learning"], "hours": 30},
    "NLP": {"cat": "ml_ai", "aliases": ["natural language processing", "text mining"], "related": ["Machine Learning", "LLMs"], "hours": 35},
    "Computer Vision": {"cat": "ml_ai", "aliases": ["opencv", "image processing"], "related": ["Deep Learning"], "hours": 35},
    "LLMs": {"cat": "ml_ai", "aliases": ["large language models", "llm", "generative ai", "genai", "gpt", "openai api", "gemini api"], "related": ["Prompt Engineering", "NLP"], "hours": 20},
    "Prompt Engineering": {"cat": "ml_ai", "aliases": ["prompting", "prompt design"], "related": ["LLMs"], "hours": 8},
    "RAG": {"cat": "ml_ai", "aliases": ["retrieval augmented generation", "retrieval-augmented generation"], "related": ["LLMs", "Vector Databases", "Embeddings"], "hours": 15},
    "Embeddings": {"cat": "ml_ai", "aliases": ["text embeddings", "semantic search"], "related": ["Vector Databases", "NLP"], "hours": 8},
    "LangChain": {"cat": "ml_ai", "aliases": ["llamaindex", "llama index"], "related": ["LLMs", "RAG"], "hours": 10},
    "MLOps": {"cat": "ml_ai", "aliases": ["mlflow", "model deployment", "kubeflow", "model serving"], "related": ["Machine Learning", "Docker"], "hours": 30},
    "Feature Engineering": {"cat": "ml_ai", "aliases": [], "related": ["Machine Learning", "Pandas"], "hours": 15},
    # --- Cloud / DevOps -----------------------------------------------------
    "AWS": {"cat": "cloud", "aliases": ["amazon web services", "ec2", "s3", "aws lambda", "lambda"], "related": ["GCP", "Azure"], "hours": 35},
    "GCP": {"cat": "cloud", "aliases": ["google cloud", "google cloud platform"], "related": ["AWS", "Azure"], "hours": 35},
    "Azure": {"cat": "cloud", "aliases": ["microsoft azure"], "related": ["AWS", "GCP"], "hours": 35},
    "Docker": {"cat": "devops", "aliases": ["containers", "containerization", "dockerfile"], "related": ["Kubernetes"], "hours": 12},
    "Kubernetes": {"cat": "devops", "aliases": ["k8s", "helm", "eks", "gke", "aks"], "related": ["Docker"], "hours": 30},
    "Terraform": {"cat": "devops", "aliases": ["infrastructure as code", "iac", "cloudformation", "pulumi"], "related": ["AWS"], "hours": 15},
    "CI/CD": {"cat": "devops", "aliases": ["ci cd", "continuous integration", "continuous deployment", "github actions", "jenkins", "gitlab ci"], "related": ["Git", "Docker"], "hours": 12},
    "Linux": {"cat": "devops", "aliases": ["unix", "ubuntu"], "related": ["Bash"], "hours": 15},
    "Monitoring": {"cat": "devops", "aliases": ["observability", "prometheus", "grafana", "datadog", "logging"], "related": [], "hours": 12},
    "Serverless": {"cat": "cloud", "aliases": ["serverless architecture", "cloud functions"], "related": ["AWS"], "hours": 10},
    # --- Tools / practices ----------------------------------------------------
    "Git": {"cat": "tools", "aliases": ["github", "gitlab", "version control", "bitbucket"], "related": [], "hours": 6},
    "Unit Testing": {"cat": "testing", "aliases": ["pytest", "jest", "junit", "testing", "automated testing", "tdd", "test-driven development"], "related": [], "hours": 10},
    "Agile": {"cat": "practice", "aliases": ["scrum", "kanban", "agile methodologies"], "related": [], "hours": 6},
    "Jira": {"cat": "tools", "aliases": [], "related": ["Agile"], "hours": 3},
    "Data Structures & Algorithms": {"cat": "fundamentals", "aliases": ["data structures", "algorithms", "dsa", "data structures and algorithms"], "related": [], "hours": 50},
    "Object-Oriented Programming": {"cat": "fundamentals", "aliases": ["oop", "object oriented programming", "design patterns"], "related": [], "hours": 15},
    "Web Security": {"cat": "security", "aliases": ["owasp", "application security", "appsec", "authentication", "oauth", "jwt"], "related": [], "hours": 15},
    "Product Management": {"cat": "product", "aliases": ["product roadmap", "roadmapping", "product strategy"], "related": ["Agile"], "hours": 30},
    "User Research": {"cat": "product", "aliases": ["ux research", "user interviews", "usability testing"], "related": ["Figma"], "hours": 20},
    "Figma": {"cat": "design", "aliases": ["wireframing", "prototyping"], "related": ["User Research"], "hours": 12},
    "Google Analytics": {"cat": "data", "aliases": ["ga4", "web analytics", "mixpanel", "amplitude", "product analytics"], "related": ["Data Analysis"], "hours": 8},
    # --- Soft skills ----------------------------------------------------------
    "Communication": {"cat": "soft_skill", "aliases": ["written communication", "verbal communication", "presentation skills", "communication skills"], "related": [], "hours": 10},
    "Leadership": {"cat": "soft_skill", "aliases": ["team leadership", "people management", "mentoring", "mentorship"], "related": [], "hours": 15},
    "Stakeholder Management": {"cat": "soft_skill", "aliases": ["stakeholder communication", "cross-functional collaboration"], "related": ["Communication"], "hours": 10},
    "Problem Solving": {"cat": "soft_skill", "aliases": ["analytical thinking", "critical thinking", "problem-solving"], "related": [], "hours": 10},
    "Teamwork": {"cat": "soft_skill", "aliases": ["collaboration", "team player"], "related": [], "hours": 5},
    "Project Management": {"cat": "soft_skill", "aliases": ["project planning", "pmp"], "related": ["Agile"], "hours": 15},
}

SOFT_SKILL_CATEGORY = "soft_skill"

# Topic templates per category, used by the rule-based planner/interviewer fallbacks.
CATEGORY_TOPICS: dict[str, list[str]] = {
    "programming_language": ["{s} syntax, types and control flow", "{s} standard library and idioms", "Error handling and debugging in {s}", "Writing tested, idiomatic {s} code"],
    "backend": ["Core concepts and request lifecycle in {s}", "Routing, validation and persistence with {s}", "Authentication and error handling with {s}", "Testing and deploying a {s} service"],
    "frontend": ["{s} fundamentals and component model", "State management and data fetching with {s}", "Styling, accessibility and performance in {s}", "Testing and shipping a {s} app"],
    "database": ["{s} data model and core queries", "Indexes, joins and query performance in {s}", "Transactions and integrity in {s}", "Using {s} from application code"],
    "data": ["{s} fundamentals", "Working with real datasets using {s}", "Common pitfalls and best practices in {s}", "End-to-end mini analysis/pipeline with {s}"],
    "ml_ai": ["Core concepts behind {s}", "Hands-on implementation of {s}", "Evaluating and debugging {s} solutions", "Deploying or integrating {s} in an application"],
    "cloud": ["{s} core services and pricing model", "Identity, networking and security on {s}", "Deploying an application to {s}", "Monitoring and cost control on {s}"],
    "devops": ["{s} fundamentals", "Using {s} in a real project workflow", "Troubleshooting {s}", "{s} best practices for production"],
    "architecture": ["Key principles of {s}", "Trade-offs: consistency, availability, latency", "Case studies of {s}", "Designing and documenting a system using {s}"],
    "fundamentals": ["Core concepts of {s}", "Practice problems on {s}", "Complexity and trade-offs in {s}", "Applying {s} in real code"],
    "soft_skill": ["Frameworks for {s}", "Practising {s} in realistic scenarios", "Getting feedback on {s}", "Demonstrating {s} in interviews"],
}
DEFAULT_TOPICS = ["Fundamentals of {s}", "Hands-on practice with {s}", "Applying {s} to a realistic problem", "Reviewing and consolidating {s}"]


@dataclass(frozen=True)
class NormalizedSkill:
    name: str
    category: str
    in_taxonomy: bool


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# alias (lowercase) -> canonical name
_ALIAS_MAP: dict[str, str] = {}
for _name, _info in _T.items():
    _ALIAS_MAP[_key(_name)] = _name
    for _alias in _info["aliases"]:
        _ALIAS_MAP[_key(_alias)] = _name

# Build symmetric "related" relationships.
_RELATED: dict[str, set[str]] = {name: set(info["related"]) for name, info in _T.items()}
for _name, _rels in list(_RELATED.items()):
    for _r in _rels:
        _RELATED.setdefault(_r, set()).add(_name)


def normalize_skill(raw: str) -> NormalizedSkill | None:
    """Map a free-text skill to its canonical form. Returns None for junk input."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip().strip(".,;:-•*")
    if not text or len(text) > 60:
        return None
    k = _key(text)
    candidates = [k, re.sub(r"\s*\d+(\.\d+)*\s*$", "", k)]  # drop trailing versions: "python 3.11"
    if k.endswith(" programming"):
        candidates.append(k.removesuffix(" programming"))
    for c in candidates:
        if c in _ALIAS_MAP:
            name = _ALIAS_MAP[c]
            return NormalizedSkill(name=name, category=_T[name]["cat"], in_taxonomy=True)
    # Unknown skill: keep the user's/JD's wording, tidy capitalisation of all-lowercase input.
    display = text if any(ch.isupper() for ch in text) else text.title()
    return NormalizedSkill(name=display, category="other", in_taxonomy=False)


def related_skills(name: str) -> set[str]:
    return _RELATED.get(name, set())


def learning_hours(name: str) -> int:
    return _T.get(name, {}).get("hours", 15)


def category_of(name: str) -> str:
    return _T.get(name, {}).get("cat", "other")


def topics_for(name: str) -> list[str]:
    templates = CATEGORY_TOPICS.get(category_of(name), DEFAULT_TOPICS)
    return [t.format(s=name) for t in templates]


def slugify(name: str) -> str:
    slug = name.lower().replace("+", "plus").replace("#", "sharp").replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "skill"


# --- Free-text scanning ------------------------------------------------------
def _scan_terms() -> list[tuple[re.Pattern, str]]:
    terms = []
    for alias, canonical in _ALIAS_MAP.items():
        # Skip very short purely alphabetic aliases ("go", "r", "ml", "ts") – too many false positives.
        if len(alias) <= 2 and alias.isalpha():
            continue
        if alias in {"node", "spring", "express", "shell", "testing", "logging", "lambda", "rest", "containers",
                     "collaboration", "prototyping", "authentication", "spark", "android", "ios", "dart", "torch",
                     "vue", "mongo", "rails", "prompting", "algorithms", "unix", "probability", "java 8"}:
            continue  # ambiguous as plain words; still normalised when explicitly listed as a skill
        pattern = re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(alias) + r"(?![A-Za-z0-9+#])", re.IGNORECASE)
        terms.append((pattern, canonical))
    # Longer aliases first so "react native" wins over "react".
    terms.sort(key=lambda t: -len(t[0].pattern))
    return terms


_SCAN_TERMS = _scan_terms()


def find_skills_in_text(text: str) -> dict[str, str]:
    """Return {canonical_skill: matched_snippet} for taxonomy skills explicitly mentioned in `text`."""
    found: dict[str, str] = {}
    consumed: list[tuple[int, int]] = []
    for pattern, canonical in _SCAN_TERMS:
        for m in pattern.finditer(text):
            span = m.span()
            if any(s <= span[0] < e or s < span[1] <= e for s, e in consumed):
                continue  # already part of a longer match
            consumed.append(span)
            if canonical not in found:
                start, end = max(0, span[0] - 60), min(len(text), span[1] + 60)
                found[canonical] = re.sub(r"\s+", " ", text[start:end]).strip()
    return found


def skill_mentioned_in(text: str, skill_name: str) -> bool:
    """True if the canonical skill (or any alias) literally appears in `text`.

    Used to reject LLM-extracted skills that are not actually in the resume.
    """
    low = text.lower()
    names = {_key(skill_name)} | {a for a, c in _ALIAS_MAP.items() if c == skill_name}
    for n in names:
        if re.search(r"(?<![a-z0-9+#])" + re.escape(n) + r"(?![a-z0-9+#])", low):
            return True
    return False
