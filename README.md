# eternal-production-v3

Eternal Packaging - Production Management System V3

V3 is the future replacement for the Production module of ETERNAL ERP V2.
This repository currently contains **infrastructure and architecture only** — no production workflows yet.

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pytest
- Database: PostgreSQL 16 (`eternal_production_v3_dev`)
- Frontend: React + Vite (V49 live shell)
- Accurate read gateway: `accurate-gateway/` (fixture or live Accurate Online)
- CI: GitHub Actions with ephemeral PostgreSQL + gateway tests

See [`docs/phase32-accurate-gateway.md`](docs/phase32-accurate-gateway.md) for gateway contracts.

## Quick start (local)

```bash
cp .env.example .env
# edit passwords in .env

docker compose up -d postgres

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd ../frontend
npm ci
npm run dev
```

Health: `GET http://127.0.0.1:8000/api/v1/health`
Ready: `GET http://127.0.0.1:8000/api/v1/ready`

## Safety

- Never connect this project to ERP V2 production PostgreSQL.
- Never store V2 production credentials here.
- PostgreSQL in Compose binds to `127.0.0.1` only.
- `.env` is gitignored; use `.env.example` for placeholders.

## Docs

- ERP V2 integration contract: [`docs/integration-v2.md`](docs/integration-v2.md)
