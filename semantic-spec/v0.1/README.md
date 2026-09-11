# Semantic documents v0.1

JSON Schema is generated from the Pydantic models in `semaloom.compiler.document_schemas()`.

```bash
uv run python -c "import json; from semaloom.compiler import document_schemas; print(json.dumps(document_schemas(), indent=2))"
```
