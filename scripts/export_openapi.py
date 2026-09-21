"""Export the FastAPI schema used by the independent frontend repository."""

import json
from copy import deepcopy
from pathlib import Path

from novel_agent.api.server import app


def export_openapi(destination: str | Path = "openapi/novel-agent-v1.json") -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    versioned_paths = {}
    for route, operations in schema.get("paths", {}).items():
        if route.startswith("/api/") and not route.startswith("/api/v1/"):
            alias = "/api/v1" + route[len("/api"):]
            copied = deepcopy(operations)
            for operation in copied.values():
                if isinstance(operation, dict) and isinstance(operation.get("operationId"), str):
                    operation["operationId"] += "V1"
            versioned_paths[alias] = copied
    schema["paths"].update(versioned_paths)
    schema["info"] = {**schema.get("info", {}), "version": "1.0.0-v1"}
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(export_openapi())
