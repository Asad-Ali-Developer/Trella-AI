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
cd backend
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux/macOS:
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 3. Run Development Server
```bash
python -m uvicorn app.main:app --reload --port 8000
```
API Docs available at: [http://localhost:8000/docs](http://localhost:8000/docs)
Health check: [http://localhost:8000/health](http://localhost:8000/health)

### Trello authorization
Create a Trello Power-Up, copy its API key into `TRELLO_API_KEY` in the project-root `.env`,
and add `http://localhost:3000` to the key's allowed origins in the Power-Up's **Trello Auth**
settings. When running the API directly, put these settings in `backend/.env`; when using
Docker Compose, put them in the project-root `.env`. The app requests read-only access and
stores the returned user token encrypted. Set `TRELLO_TOKEN_RETURN_URL` to the frontend
callback URL when using a different local or deployed frontend origin.

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
