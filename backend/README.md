# Client Insights API

Backend service for the **Client Insights — Trello + AI Platform**, built with FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16 + pgvector, Redis, and Celery.

---

## Getting Started Locally

### 1. Start Database & Redis via Docker
From the project root:
```bash
docker compose up postgres redis -d
```

### 2. Set Up Virtual Environment & Dependencies
```bash
cd apps/api
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux/macOS:
# source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"
```

### 3. Run Development Server
```bash
uvicorn app.main:app --reload --port 8000
```
API Docs available at: [http://localhost:8000/docs](http://localhost:8000/docs)
Health check: [http://localhost:8000/health](http://localhost:8000/health)

### 4. Run Tests & Quality Checks
```bash
# Run test suite
pytest

# Code formatting and linting
ruff check .
ruff format --check .

# Static type verification
mypy app
```
