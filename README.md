# JANICE

**Just-in-time Analytics for Network Improvement and Clinical Evaluation**

A chat assistant that helps clinical teams and hospital administrators explore
quality improvement data from the Clinical Information Network (CIN).

> Status: Sprint 0, foundations. Not yet usable.

## Documentation

- [System design](docs/design/system-design.md)
- [Architecture decision records](docs/adr/)
- [Contributing and git workflow](CONTRIBUTING.md)

## Run the whole stack

```bash
cp .env.example .env        # once; fill in the secrets
docker compose up -d --build
```

Open http://localhost:8088: nginx serves the app and forwards `/api/` to Django.

## Repository layout (planned)

| Folder | Contents |
| --- | --- |
| `backend/` | Django API, chat loop, MCP server |
| `frontend/` | Vue 3 app |
| `pipeline/` | Data pipeline: data dictionary reader and synthetic data (Dagster, R extract and dbt to follow) |
| `deploy/` | Docker Compose, nginx, Ansible |
| `docs/` | Design doc, ADRs, runbooks |

Folders are added as each component is built.

## Data handling

This repository must never contain patient data, REDCap exports, API tokens
or hashing keys. Development uses synthetic data only.
