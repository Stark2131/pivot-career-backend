"""Write docs/openapi.json and docs/API.md from the live FastAPI app (keeps docs in sync with code)."""
import json
from pathlib import Path

from app.main import app

spec = app.openapi()
docs = Path(__file__).resolve().parent.parent / "docs"
docs.mkdir(exist_ok=True)
(docs / "openapi.json").write_text(json.dumps(spec, indent=2))

lines = ["# API Endpoints", "", "Generated from the OpenAPI spec (`python -m scripts.export_openapi`). "
         "Interactive docs: `http://localhost:8000/docs`.", "",
         "All `/api/*` endpoints except register/login require `Authorization: Bearer <token>`.", ""]
by_tag: dict[str, list[str]] = {}
for path, methods in spec["paths"].items():
    for method, op in methods.items():
        tag = (op.get("tags") or ["Other"])[0]
        codes = ", ".join(sorted(op.get("responses", {})))
        by_tag.setdefault(tag, []).append(f"| `{method.upper()}` | `{path}` | {op.get('summary', '')} | {codes} |")
for tag, rows in by_tag.items():
    lines += [f"## {tag}", "", "| Method | Path | Summary | Responses |", "|---|---|---|---|", *rows, ""]
(docs / "API.md").write_text("\n".join(lines))
print(f"Wrote {docs / 'openapi.json'} and {docs / 'API.md'}")
