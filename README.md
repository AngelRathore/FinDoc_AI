# FinDoc AI

FinDoc AI provides PDF, TXT, and URL ingestion plus document-grounded chat through the existing FastAPI and frontend APIs. The active chat pipeline uses FAISS semantic retrieval, an ingestion-built BM25 index, Reciprocal Rank Fusion, cross-encoder reranking, evidence-bounded prompts, and citations. The experimental AI agent is disabled; its old endpoint remains mounted and returns HTTP 410.

## Backend setup

Use Python 3.10 or newer. From `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Set `GROQ_API_KEY` in `backend/.env` before asking questions. `GROQ_MODEL` selects the Groq model and defaults to `openai/gpt-oss-20b`.

## Authentication (Phase 2)

Copy the settings from `backend/.env.example` into your ignored `backend/.env`. Generate your own `JWT_SECRET_KEY` with `openssl rand -hex 32` and keep it private. Auth uses 15-minute HS256 access tokens by default and 7-day rotating refresh tokens. Argon2 hashes passwords, and PostgreSQL stores only SHA-256 refresh-token digests. Refresh tokens are sent in an HttpOnly, SameSite=Strict cookie; the React client keeps the access token in session storage. Set `AUTH_COOKIE_SECURE=true` when serving over HTTPS. Registration assigns the `user` role; the API never accepts a client-selected role.

The versioned routes are `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, and `GET /api/v1/auth/me`. The existing `/api` route prefix is also kept for compatibility. Sign in through the React app or call the JSON auth endpoints; protected API requests require `Authorization: Bearer <access_token>`. Successful registration and login return an access token and set the refresh-token cookie.

After registering an account, a database operator can grant the admin role from `backend/` with `python -m scripts.set_user_role user@example.com admin`. Admin role is required for the legacy global clear action. Conversations and chat history are partitioned by authenticated user and persisted in PostgreSQL. Documents are owned by the authenticated user; client-supplied owner IDs are not accepted.

## Backend foundation and database

The backend is organized into `api/v1/`, `core/`, `db/`, `models/`, `schemas/`, `services/`, and `tests/`. Existing routes remain available under `/api` for the React frontend and are also available under `/api/v1`. `/health` checks that the process responds; `/ready` verifies that `DATABASE_URL` connects. Phase 1 added the SQLAlchemy session dependency and Alembic baseline; Phase 2 added `users` and `refresh_tokens`; Phase 3 adds owner-linked `documents` metadata. The FAISS/BM25 indexes and chat histories remain in memory.

Copy `backend/.env.example` to `backend/.env`, then set `GROQ_API_KEY` and your own `DATABASE_URL`. For PostgreSQL, use a URL such as `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`; do not commit the `.env` file. No database credentials are supplied by this project.

From `backend/`, after activating the virtual environment and installing requirements, run migrations and the API with:

```bash
alembic upgrade head
uvicorn main:app --reload
```

Use `pytest` or the existing stdlib test runner to run tests:

```bash
python -m unittest discover -s tests -v
```

A PostgreSQL server must be running and reachable before `/ready` succeeds or the Alembic migration can be applied to PostgreSQL.

## Owned document API (Phase 3)

Configure `DOCUMENT_STORAGE_DIR` (defaults to `backend/storage/documents`) and `MAX_UPLOAD_SIZE_BYTES` (defaults to 20 MiB) in `backend/.env`. Local document files are stored under that directory using server-generated names; it is ignored by Git. Apply the new schema with `alembic upgrade head` before starting the API.

Authenticated endpoints are `POST /api/v1/documents` (multipart field `file`, PDF/TXT), `GET /api/v1/documents?limit=20&offset=0`, `GET /api/v1/documents/{document_id}`, and `DELETE /api/v1/documents/{document_id}`. The existing URL/PDF/TXT ingestion routes remain available and now create owner-linked document records. Unauthorized and nonexistent document IDs both return 404. No private file-serving endpoint is exposed.

The React sidebar lists each user's uploaded documents, their processing status, and a delete control. Deletion is owner-scoped and removes the file/index artifact; past conversation citations become unavailable. Admins also see an **All User Uploads** metadata list with filename, owner email, type, size, status, and timestamps through `GET /api/v1/documents/admin`; it does not expose document contents or storage paths. Admin oversight does not grant deletion rights over another user's documents. The old admin global-clear API remains a legacy endpoint and is intentionally not shown as a UI action.

Each chat request resolves completed document IDs for the authenticated user from PostgreSQL. Each indexed chunk carries `owner_id`, `document_id`, `chunk_id`, and `source` plus page metadata when available. BM25 ranks only authorized chunks. Semantic retrieval creates an exact FAISS search index from only verified authorized vectors; this avoids the installed LangChain FAISS metadata filter behavior, which filters after a global top-`fetch_k`. Only authorized candidates reach RRF, reranking, evidence formatting, citations, or Groq. Missing or mismatched ownership metadata is excluded, and an inability to verify scoped FAISS candidates fails closed.

Deletion first changes the database row to `deleting`, immediately removing it from authorized scopes; then it removes the local file and per-document index artifact and deletes the row. Retrieval compares a signature of completed database rows with each API process's in-memory signature and rebuilds from verified artifacts when they differ, so a stale index cannot make a deleted document eligible.

## Pipeline settings

Typed settings are centralized in `backend/core/config.py` (legacy RAG modules read compatibility exports from `backend/config.py`) and can be overridden with environment variables:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `FINDOC_CHUNK_SIZE` | `1000` | Maximum chunk characters |
| `FINDOC_CHUNK_OVERLAP` | `150` | Chunk overlap characters |
| `FINDOC_RETRIEVAL_CANDIDATES` | `12` | Candidates per semantic and lexical retrieval |
| `FINDOC_FINAL_CHUNKS` | `4` | Evidence chunks sent to generation |
| `FINDOC_RERANK_THRESHOLD` | `0.0` | Minimum cross-encoder score for evidence |
| `FINDOC_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model name |
| `FINDOC_CONTEXT_CHAR_BUDGET` | `12000` | Approximate evidence context character limit |

The embedding model is `sentence-transformers/all-MiniLM-L6-v2`. Workers persist private per-document chunk and vector artifacts under `DOCUMENT_STORAGE_DIR/.indexes`; each API process rebuilds its own FAISS and BM25 indexes from completed records and matching artifacts on the next chat request. Clearing ingestion as admin deletes document records, their local files, and their artifacts.

PDF pages are extracted in pypdf layout mode to preserve table column spacing, then split into chunks while carrying page metadata. Text encoded as selectable PDF text (including table values and figure captions) can be indexed. Embedded charts/images are not OCR'd, so figures without text captions are not searchable.

## Tests and evaluation

From `backend/`:

```bash
python -m unittest discover -s tests -v
python evaluate.py --dataset evaluation/financial_qa.json -k 5
```

The evaluation dataset is a small, synthetic financial-document example. The evaluator reports Recall@K, MRR, and nDCG@K for semantic-only, BM25-only, hybrid RRF, and cross-encoder-reranked retrieval. For a real quality estimate, replace/extend it with manually judged chunks from representative financial PDFs.

## Current limitations

- FAISS and BM25 live in API-process memory; restarts rebuild indexes from local artifacts. Conversations and chat history are persisted in PostgreSQL. API processes refresh independently against PostgreSQL completed-document signatures. Workers and API processes must share the same local `DOCUMENT_STORAGE_DIR`; this is a single-machine development design, not a multi-host storage solution.
- Local files, index artifacts, and PostgreSQL metadata must be backed up together. Uploaded files remain outside PostgreSQL; private index artifacts contain extracted chunk text and vectors. This phase does not include virus scanning, encryption-at-rest, cloud storage, or distributed/shared durable vector storage.
- pypdf layout extraction improves text-based tables but does not recover all complex table structures, scanned pages, or figures. Scanned PDFs need OCR and image extraction needs a vision/OCR stage.
- Follow-up query rewriting and final answer generation require Groq access. Query rewriting falls back to the original question on errors. If reranking fails or returns non-finite scores, retrieval logs the error and returns no evidence so chat abstains.
- Citation validation removes unknown numeric citation markers and the API only returns source labels from retrieved passages. It cannot independently verify every factual statement generated by the LLM.
- The reranker threshold is model-score dependent; tune it against a representative labeled evaluation set.
- Reranker tensors are copied into owned memory at initialization to avoid non-finite CPU scores in the tested runtime. `transformers==4.44.2` is pinned alongside `sentence-transformers==3.0.0` for a reproducible inference stack.

## Background ingestion (Phase 4)

Install backend dependencies, start PostgreSQL and Redis, then apply the migration:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
python -m alembic upgrade head
```

Set `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` in `backend/.env` (local defaults are Redis databases 0 and 1). Start Redis with Homebrew using `brew services start redis` or run `redis-server` in another terminal. On macOS, run the worker with the `solo` pool to avoid multiprocessing task-trace failures, and run Beat separately with an explicit scheduler so the durable outbox can redispatch queued jobs:

```bash
cd backend
source .venv/bin/activate
celery -A celery_app:celery_app worker --pool=solo --loglevel=INFO
```

In a separate terminal, start Beat:

```bash
cd backend
source .venv/bin/activate
celery -A celery_app:celery_app beat --scheduler celery.beat:PersistentScheduler --loglevel=INFO
```

In another terminal, start FastAPI as before:

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --reload
```

Uploads and URLs return HTTP 202 with document/job IDs and a status URL. Poll `GET /api/v1/ingestion-jobs/{job_id}`; document status is available from `GET /api/v1/documents/{document_id}`. Failed jobs expose a sanitized message and can be retried with `POST /api/v1/ingestion-jobs/{job_id}/retry`. One job row is retained per document and deleted with its document; manual retry reuses the row and resets `attempt_count` for the new retry cycle, so prior attempt history is not retained. Redis is a dispatch transport, while PostgreSQL remains the source of truth. The job row acts as an outbox; a beat task retries undispatched rows. Redis and PostgreSQL do not share an atomic transaction, so dispatch can be duplicated after a crash; the worker is idempotent and validates the persisted task ID.

The worker parses/chunks documents, builds temporary FAISS and BM25 indexes to validate generated vectors, then atomically stores chunk/vector artifacts before marking the document complete. Each API process refreshes its own in-memory FAISS/BM25 indexes from completed artifact files. This requires worker and API to use the same local document directory. Deletion marks the document `deleting` before file/artifact cleanup, so retrieval excludes it while a worker is running. For local macOS development, run one worker with `--pool=solo` and one separate Beat process using the documented scheduler command.

For URL ingestion, the raw URL is stored in a mode-`0600` local `.url` file; the database/source label omits query strings and fragments, and URLs containing userinfo are rejected. The worker resolves DNS, rejects any non-public result, pins the HTTP request to the checked IP, preserves TLS hostname verification/SNI, restricts ports to 80/443, disables redirects, caps response size, and applies connect/read/overall time limits. This reduces DNS-rebinding risk in the application fetch path. It cannot replace network egress controls: resolver behavior, proxy/network configuration, and future transport changes remain trust boundaries. URL ingestion should be limited to trusted use until network-level egress restrictions exist.

## Persistent conversations (Phase 5)

Conversations, user/assistant messages, and evidence citation metadata are stored in PostgreSQL. Conversations are scoped to the authenticated user. Citations keep source name, page, chunk ID, and document ID metadata, but never provide a private-file URL. When a source document is deleted, its historical citation is retained as `Source unavailable` with the document/chunk identifiers cleared. Conversation deletion cascades to its messages and citations.

Before applying the new migration, make a valid backup of the PostgreSQL database used by `DATABASE_URL`. The migration is `0005_persistent_conversations` (after `0004_ingestion_jobs`) and is not applied automatically:

```bash
cd backend
source .venv/bin/activate
python -m alembic current
python -m alembic upgrade head
```

The new API is available at both `/api/v1` and the legacy `/api` prefix:

- `POST /conversations` creates a conversation; `GET /conversations` lists the caller's conversations.
- `GET /conversations/{id}?limit=50&offset=0` loads a conversation and a page of messages.
- `PATCH /conversations/{id}` renames it; `DELETE /conversations/{id}` deletes its history.
- `POST /conversations/{id}/messages` accepts `{"question":"...", "request_id":"client-generated-id"}`.
- `POST /chat/ask` remains compatible with prior clients; it accepts `question`, optional `conversation_id`, and the previous `session_id` field. If no conversation ID is supplied, the `session_id` is mapped to an owner-scoped persistent conversation.

`CHAT_HISTORY_MESSAGES` controls the bounded number of prior messages used for follow-up rewriting and answer context (default 8, maximum 40). Failed assistant attempts are recorded as failed and excluded from history; a retry with the same request ID can retry a failed attempt, while an already completed request returns its original answer. PostgreSQL commits the user message before retrieval/provider work so failures do not lose the user's prompt.

## Phase 6 hardening

This phase adds a durable database retry deadline (`ingestion_jobs.next_attempt_at`) so the outbox dispatcher honors exponential backoff instead of immediately redispatching transient failures. Migration `0006_durable_retry_schedule` follows `0005_persistent_conversations`; it has not been applied to your live database automatically. Back up the target database, confirm `DATABASE_URL` points to the intended database, then apply manually from `backend/`:

```bash
python -m alembic current
python -m alembic upgrade head
```

Chat idempotency now rejects reuse of an existing request ID with different message text (HTTP 409). The frontend blocks duplicate submissions and shows deleted citations as unavailable text. Production configuration validation requires a database URL, Groq key, at least 32-byte JWT secret, secure refresh cookie, and explicit CORS origins. Interactive API docs are enabled only when `ENVIRONMENT=development`. Logs include an allowlist of operational identifiers and timings; prompts, answers, credentials, and document text are not logged.

### Local diagnostics

Run these from `backend/`. They show service state without printing environment values:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/ready
python -m alembic current
redis-cli ping
celery -A celery_app.celery_app inspect ping
test -w "${DOCUMENT_STORAGE_DIR:-storage/documents}" && echo "storage writable"
```

`/health` checks API liveness; `/ready` checks PostgreSQL. Redis is optional to API readiness because PostgreSQL outbox rows remain authoritative and can be dispatched when Redis returns. A worker and API process must share `DOCUMENT_STORAGE_DIR`. Run exactly one Beat scheduler process. `inspect ping` requires a running worker.

### Tests and deterministic retrieval evaluation

```bash
python -m unittest discover -s tests -v
python -m evaluation.phase6_eval
```

The Phase 6 benchmark uses eight synthetic cases covering direct and follow-up questions, numeric/table and figure evidence, absent answers, deleted chunks, and cross-user scope. It prints Recall@3, MRR, nDCG@3, citation-evidence validity, deterministic text/numeric support, and abstention rate for semantic-only, BM25-only, RRF hybrid, and reranked retrieval. A deterministic embedding and token-overlap reranker make it repeatable; results are a correctness smoke baseline, not a claim about production model quality. External model evaluation remains optional:

```bash
python evaluate.py --dataset evaluation/financial_qa.json -k 5
```

### Live-service integration verification (opt-in)

The ordinary suite uses isolated SQLite databases, fake embeddings/rerankers/LLM, and mocked network calls. To verify PostgreSQL, Redis and Celery locally, configure a dedicated disposable test database in a separate shell environment, start Redis, one Celery worker, and one Beat process, then run the API. Check `/ready`, `python -m alembic current`, `redis-cli ping`, and `celery -A celery_app:celery_app inspect ping`. Register two test users, upload a synthetic TXT/PDF as user A, poll its job endpoint until completed, ask a question and inspect persisted conversation/citation history, then verify user B receives 404 for A's document/conversation. Delete A's test document and confirm its citation is marked unavailable and it is excluded from a later question. Retry a deliberately malformed test upload only after confirming the sanitized failed state. Remove only those test records after verification. Do not point the procedure at a database containing valuable data.

Before a local PostgreSQL upgrade, create a custom-format backup with `pg_dump -Fc -f findocai-before-phase6.dump DATABASE_NAME` and restore-test it into a separate database with `pg_restore -d findocai_restore_test findocai-before-phase6.dump`. Protect backup files because they contain account and application data. Uploaded files and `.indexes` artifacts need a separate filesystem backup under `DOCUMENT_STORAGE_DIR`; a database dump alone cannot restore documents.

### Remaining limitations

- This is still a local-storage architecture. Multiple hosts need shared durable file storage before they can safely run API and Celery processes.
- API workers keep independent in-memory FAISS/BM25 views and refresh from local artifacts when the completed-record signature changes. They must share the same storage directory; artifact loss prevents indexing until the source is reprocessed.
- No general API rate limiter was added: there is no existing shared limiter, and adding a Redis-required limiter would compromise local availability. Expensive endpoint abuse needs rate limits before internet exposure.
- No virus scanner or document sandbox is configured. Upload size, extension/content signature checks, generated storage names, and parser limits reduce risk but do not replace malware scanning.
- URL fetch restrictions and app-side IP pinning reduce SSRF exposure but do not replace outbound firewall/egress controls.
- The deterministic benchmark does not validate live Groq facts or real cross-encoder score calibration. Tune `FINDOC_RERANK_THRESHOLD` against a larger manually judged finance corpus before relying on abstention rates.
- No live PostgreSQL/Redis/Celery/Groq integration checks were run as part of local unit verification, and the migration remains unapplied until you run it manually.

## Author

Angel Rathore — Computer Science undergraduate focused on AI, machine learning, and backend development.
