# Backend — ETERNAL PRODUCTION V3

Foundation only: FastAPI app, PostgreSQL session, health/ready endpoints, Alembic baseline, Pytest.

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pytest -q
```

Set `DATABASE_URL` / `DATABASE_URL_SYNC` from the repository `.env.example`.
