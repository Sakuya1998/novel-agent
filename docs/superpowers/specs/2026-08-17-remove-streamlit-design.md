# Remove Streamlit Interface Design

## Goal

Remove the migration-only Streamlit interface now that the React workbench covers novel creation, deletion, generation, review, resume, and model settings.

## Scope

- Delete the `ui` package and its dedicated runtime test.
- Remove the `streamlit` dependency from Python dependency files and version checks.
- Remove Streamlit startup instructions and tree entries from the README.
- Remove `ui` from Docker copy steps, package discovery, Ruff first-party configuration, and CI lint targets.
- Keep FastAPI, React, CLI, SQLite novels, LangGraph checkpoints, Chroma memory, and encrypted model settings unchanged.

## Compatibility

Existing runtime data requires no migration. Checkpoints remain readable through FastAPI, React, and CLI because Streamlit's runtime wrapper is not shared by those entry points.

## Verification

- Confirm no production or test references to Streamlit or the `ui` package remain.
- Run the backend test suite and Ruff.
- Run frontend tests, TypeScript checks, and the production build.
- Confirm Docker configuration no longer copies the removed package.
