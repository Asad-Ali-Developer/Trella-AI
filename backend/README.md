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
An authorized Trello account can be linked to multiple workspaces the user belongs to. The account
credentials are stored once; board selections and synchronized data stay scoped to each workspace.
To use a different Trello account in a workspace, disconnect its current account first. Disconnecting
one workspace removes only that workspace's linked data; credentials remain available while another
workspace still uses the account.

### Trello board sync and webhooks
Included boards sync through the Celery worker. Start it with `docker compose up -d api worker`
when using Compose, or run the Celery command shown in `docker-compose.yml` with the same
database, Redis, encryption, and Trello settings as the API.

To receive near-real-time board updates, expose the API through a public HTTPS URL (for local
development, use Cloudflare Tunnel or ngrok) and set `TRELLO_WEBHOOK_CALLBACK_URL` to that exact
public URL ending in `/api/v1/connections/trello/webhooks`. Set `TRELLO_WEBHOOK_SECRET` to the
Trello App Secret from Trello App Admin > Trello Auth. The app registers a board webhook during
sync and verifies each `X-Trello-Webhook` HMAC before queueing a refresh. Without these settings,
manual sync still works but automatic webhook updates are not enabled.

The Redis limiter enforces Trello's published limits per API key (300 requests per 10 seconds),
per token (100 per 10 seconds), and `/members` routes (100 per 900 seconds). Requests wait for
capacity; Redis availability is required for Trello API calls.

### Workspace context
`GET /api/v1/context` builds a workspace-specific context snapshot using the `X-Workspace-Id`
header. It includes active accounts linked to that workspace, included Trello boards, and their
synced cards, comments, and people. A single connected account is sufficient; data from another
workspace is never included. Pass `client_id` to scope the snapshot to a workspace client and
`max_tokens` (256–12000, default 4000) to control chunk size. Token counts are estimates.

Set `GEMINI_API_KEY` to enable the Phase 3 AI features; `GEMINI_CONTEXT_MODEL` and
`GEMINI_EMBEDDING_MODEL` select their respective models. `POST /api/v1/context/summaries` generates
and caches summaries by card content hash, model, and prompt version. `POST /api/v1/context/index`
indexes cards in batches, and `POST /api/v1/context/search` finds similar cards only from the
selected workspace's active, included Trello sources. A sync that changes a card or its comments
changes the content hash, so the next summary or index operation refreshes derived data. Search
requires the workspace cards to be indexed first. `PATCH /api/v1/context/members/{member_id}` lets
workspace owners and admins classify a person as a client, internal, or unknown; this label is
stored per workspace.

### GitHub integration
Create a GitHub OAuth App and set its callback URL to
`http://localhost:3000/dashboard/github/callback`. Configure `GITHUB_CLIENT_ID`,
`GITHUB_CLIENT_SECRET`, and `GITHUB_CALLBACK_URL` in `backend/.env` for a direct local run or the
project-root `.env` for Docker Compose. The integration requests `read:user repo`; GitHub's `repo`
OAuth scope is needed for private repositories and allows repository access with that token. DeepClient
only makes read requests, encrypts tokens at rest, and stores them per user/account.

Connect the account from Connected Apps, select repositories for the active workspace, and optionally
associate each repository with one of that workspace's Trello clients. Repository selections are
workspace-specific and the same GitHub account can be reused in multiple workspaces. Included
repositories sync their 500 most recent commits initially and then check for new commits on subsequent
syncs. The context snapshot includes commits only from active, included repositories; when a client is
selected, it includes only repositories associated with that client. Start the Celery worker with
`docker compose up -d worker` for background synchronization.

### Transactional email
Docker Compose starts a Celery worker and local Mailpit SMTP inbox. Start the dependencies with
`docker compose up postgres redis mailpit -d`, then start the API and worker with Compose; inspect
captured email at [http://localhost:8025](http://localhost:8025). When running the API directly,
set `SMTP_HOST=localhost` and `SMTP_PORT=1025` and start Mailpit with Compose. For deployment,
configure the SMTP host, port, sender address, TLS mode, and credentials in both the API and worker
environment. Password reset requests use a one-time hashed token and expire after the configured
`PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`.

### Encryption key rotation
Back up the database, generate a new Fernet key with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`,
then configure that value as `ENCRYPTION_KEY` and the previous key in `ENCRYPTION_FALLBACK_KEYS`.
With the same configuration available to the API and worker, run
`python -m app.scripts.rotate_encryption_key` from `backend`. After it succeeds, remove the old
key from `ENCRYPTION_FALLBACK_KEYS` and restart all processes. Keep the backup until the rotated
credentials have been verified.

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
