# LENS

> A personal information capture and retrieval system: anything you encounter and want to find again should be easy to capture, understand, connect, and retrieve.

---

## Current Status: Capture Ingestion API / Stage 5

> [!NOTE]
> This repository is currently in **Stage 5 (Capture Ingestion API)**. The first core product capability—Capture Ingestion—is implemented and active. Clients can ingest URL and text captures via `POST /captures`, retrieve paginated captures via `GET /captures`, and fetch individual captures with metadata via `GET /captures/{capture_id}`. Background workers, automatic URL crawling, vector embeddings, file uploads, and authentication remain planned for upcoming stages.

---

## Core Problem

Modern knowledge work suffers from severe information fragmentation:
- Articles, documentation, code snippets, GitHub repositories, and thoughts are scattered across dozens of disconnected tools and browser tabs.
- Bookmarks and traditional note-taking apps turn into "write-only" archives where saved content is rarely discovered when needed.
- Keyword-based search breaks down when users remember concepts, context, or visual cues rather than exact strings.

---

## Core Product Loop

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   CAPTURE    │ ──> │  UNDERSTAND  │ ──> │   CONNECT    │ ──> │   RETRIEVE   │
│ Web / Mobile │     │ Extract/Meta │     │ Graph/Vector │     │ Hybrid Search│
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

1. **Capture**: Seamless, low-friction entry point across web (browser extension / web dashboard) and mobile (share sheet / quick capture) for links, text, media, and integrations.
2. **Understand**: Automated extraction of content, summaries, metadata, and structural representations.
3. **Connect**: Link inference, topic clustering, and semantic vector embedding generation.
4. **Retrieve**: High-precision hybrid search (combining exact keyword matching and semantic similarity) resurfacing the right context at the right time.

---

## Main Capabilities Planned for V1

* **Omni-Capture Interface**: Unified ingestion for URLs, raw notes, GitHub repositories, and media.
* **Intelligent Processing Pipeline**: Asynchronous background jobs handling metadata extraction, text chunking, and embedding generation.
* **Hybrid Search Engine**: Combined lexical (PostgreSQL full-text) and semantic (pgvector) query execution.
* **Multi-Platform Access**: Responsive Next.js web application and cross-platform Flutter mobile application.
* **GitHub Integration**: Ingest starred repositories, releases, and issue notes via OAuth and webhooks.
* **Secure Storage**: Encrypted JWT authentication with private S3-compatible object storage for captured media and raw payloads.

---

## High-Level Architecture (Planned)

```mermaid
graph TD
    subgraph Clients [Clients]
        Web["Web Application (Next.js + TypeScript)"]
        Mobile["Mobile Application (Flutter)"]
    end

    subgraph API_Gateway [Services]
        API["FastAPI Backend (REST API)"]
        Worker["Background Worker (Python)"]
    end

    subgraph Infrastructure [Data & Infrastructure]
        PG[("PostgreSQL + pgvector")]
        Redis[("Redis (Cache & Task Queue)")]
        S3[("S3-Compatible Object Storage")]
    end

    Web -->|HTTP / REST| API
    Mobile -->|HTTP / REST| API
    API -->|Read / Write Metadata & Vectors| PG
    API -->|Enqueue Jobs / Cache| Redis
    API -->|Store Raw Files / Media| S3
    Worker -->|Consume Tasks| Redis
    Worker -->|Update Embeddings & Status| PG
    Worker -->|Access Artifacts| S3
```

---

## Repository Structure

```
lens/
├── apps/
│   ├── web/          # Next.js web application [PLANNED]
│   └── mobile/       # Flutter mobile application [PLANNED]
├── services/
│   ├── api/          # FastAPI REST API service [PLANNED]
│   └── worker/       # Python background processing worker [PLANNED]
├── packages/         # Shared libraries and configurations [PLANNED]
├── infra/            # Docker, local development, and deployment specs [PLANNED]
├── docs/             # Engineering and architectural documentation
│   └── architecture.md
├── .editorconfig     # Consistent cross-editor formatting rules
├── .gitignore        # Comprehensive ignore rules for all tech stacks
└── README.md         # Repository overview and development guide
```

---

## Technology Stack

| Layer | Technology | Status |
| :--- | :--- | :--- |
| **Web Frontend** | Next.js (React), TypeScript | *Planned* |
| **Mobile Frontend** | Flutter, Dart | *Planned* |
| **Backend API** | FastAPI, Python 3.11+ | **Active Core & Capture Ingestion API** (`services/api/`) |
| **Background Worker** | Python | *Planned* |
| **Primary Database** | PostgreSQL 16 + `pgvector` extension | **Active Models & Migrations** (`services/api/alembic/`) |
| **Cache & Queue** | Redis 7.4 | **Infra Configured** (`infra/docker-compose.yml`) |
| **Object Storage** | S3-Compatible (MinIO) | **Infra Configured** (`infra/docker-compose.yml`) |
| **Authentication** | JWT (Initial) | *Planned* |
| **Integrations** | GitHub OAuth & Webhooks | *Planned* |
| **Local Containerization** | Docker & Docker Compose | **Active / Tested** |

---

## Local Development Prerequisites

Before setting up application components in subsequent stages, verify that your workstation has the following tooling installed:

- **Node.js**: v20+ LTS recommended (v26.5.0 verified)
- **Node Package Manager**: `pnpm` / `npm` / `bun`
- **Python**: v3.11.9+ with `pip`
- **Flutter SDK**: v3.20+ (v3.41.7 verified) & **Dart SDK** (v3.11.5 verified)
- **Android SDK / ADB**: For mobile device emulation and debugging
- **Docker & Docker Compose**: For running local databases, caches, and object storage
- **Git**: v2.40+ (v2.55.0 verified)

---

## Local Development & Infrastructure

### 1. Backing Services Quickstart

To run the local backing services (PostgreSQL with pgvector, Redis, and MinIO), follow these steps:

1. **Start Docker Desktop**:
   Ensure the Docker daemon is running on your host machine.

2. **Copy `.env.example` to `.env`**:
   ```bash
   cp .env.example .env
   ```
   > [!CAUTION]
   > **CRITICAL RULE**: The `.env` file contains local secrets and must **NEVER** be committed to version control. The repository's `.gitignore` explicitly prevents tracking this file.

3. **Fill Only Required Values for Local Development**:
   For local development of infrastructure, the default values provided in `.env.example` for PostgreSQL (`lens_user`, `lens_password`, `lens`), Redis (`localhost:6379`), and MinIO (`minioadmin`/`minioadmin`) are functional defaults for local usage.

   **Credentials NOT required at this stage** (features are planned and not yet implemented):
   - `JWT_SECRET`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS` — Authentication service is not yet built.
   - `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET` — GitHub integration is not yet implemented.
   - `AI_PROVIDER`, `AI_API_KEY` — Embedding and LLM pipelines are not yet implemented.

4. **Start Infrastructure with Docker Compose**:
   ```bash
   docker compose -f infra/docker-compose.yml up -d
   ```

5. **Check Service Health**:
   ```bash
   docker compose -f infra/docker-compose.yml ps
   ```
   All three services should report healthy:
   - `lens-postgres` (PostgreSQL 16 with pgvector on port `5432`)
   - `lens-redis` (Redis 7.4 on port `6379`)
   - `lens-minio` (MinIO S3 API on port `9000`, Web Console on port `9001`)

6. **Stop Infrastructure When Finished**:
   ```bash
   docker compose -f infra/docker-compose.yml down
   ```
   *Note: Named volumes (`lens_postgres_data`, `lens_redis_data`, `lens_minio_data`) are preserved across stops. Add `-v` only if you explicitly intend to delete local data.*

### 2. FastAPI Backend Service (`services/api/`)

The core API service provides the backend foundation for LENS:

* **Location**: `services/api/`
* **Python Environment Setup**:
  ```bash
  cd services/api
  python -m venv .venv
  # Windows PowerShell
  .\.venv\Scripts\Activate.ps1
  # Linux / macOS
  source .venv/bin/activate
  ```
* **Dependency Installation**:
  ```bash
  pip install -r requirements.txt
  ```
* **Prerequisites**: Ensure local infrastructure (PostgreSQL and Redis) is running via Docker Compose (`docker compose -f infra/docker-compose.yml up -d`).
* **Start API Locally**:
  ```bash
  # From services/api/
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
* **Verify Health**:
  ```bash
  curl http://localhost:8000/health
  ```
  Expected response when all dependencies are healthy:
  ```json
  {"status":"ok","api":"ok","database":"ok","redis":"ok"}
  ```
  If PostgreSQL or Redis is unreachable, the endpoint returns `503 Service Unavailable` with `status: "degraded"` and identifies the failing component without exposing internal credentials or tracebacks.
* **Current API Scope**:
  - Foundational application structure (`app/core`, `app/db`, `app/health`, `app/captures`).
  - Configuration loader (`pydantic-settings`).
  - Asynchronous SQLAlchemy engine (`asyncpg`) and Redis client.
  - Active connectivity health checks (`GET /health`).
  - Core capture ingestion endpoints (`POST /captures`, `GET /captures`, `GET /captures/{capture_id}`).
  - *NOT YET IMPLEMENTED*: Authentication, user management, search endpoints, embeddings, file ingestion, or external integrations.

### 3. Database Domain Models & Migrations (`alembic/`)

The database layer utilizes modern SQLAlchemy 2.x declarative models and Alembic for asynchronous PostgreSQL schema evolution:

* **Core Domain Models (`services/api/app/db/models.py`)**:
  - `Capture`: The primary record representing any ingested item. Fields include UUID primary key, `source_type` enum (`url`, `text`, `image`, `pdf`, `file`, `github`), optional title, original URL, content text, mime type, external source ID, and timestamps.
  - `ContentChunk`: Searchable content chunks belonging to a Capture. Features foreign key with `CASCADE` deletion, `chunk_index`, text content, and a `Vector(1536)` column for future dense vector embeddings.
  - `SourceMetadata`: Flexible 1-to-1 extension table storing source-specific metadata as PostgreSQL `JSONB` with foreign key `CASCADE` deletion.
* **Running Migrations**:
  From `services/api/` with the virtual environment activated:
  ```bash
  # Upgrade database to latest migration
  alembic upgrade head

  # Roll back the most recent migration
  alembic downgrade -1

  # Create a new autogenerated revision
  alembic revision --autogenerate -m "migration_description"
  ```
* **Current Schema Scope**:
  - Foundational data structures and storage capability for captures, chunks, vectors, and metadata.
  - Embeddings column is a storage-only placeholder; AI embedding calculation is not yet implemented.
  - User accounts, authentication schemas, queue persistence, and search APIs remain planned for upcoming stages.

### 4. Capture Ingestion API (`POST /captures`, `GET /captures`, `GET /captures/{capture_id}`)

Stage 5 implements the first core product capability of LENS: ingesting URLs and raw notes/text payloads into durable storage with optional source metadata.

#### Ingestion Endpoints

| Method | Path | Description | Success Status |
| :--- | :--- | :--- | :--- |
| `POST` | `/captures` | Ingest and persist a new URL or text capture atomically | `201 Created` |
| `GET` | `/captures` | Retrieve paginated captures ordered newest first (`created_at` DESC) | `200 OK` |
| `GET` | `/captures/{capture_id}` | Retrieve a single capture by UUID along with source metadata | `200 OK` |

#### Endpoint Details & Examples

##### 1. `POST /captures`
Ingests a new capture item. Validation strictly enforces:
- `source_type`: Must be `"url"` or `"text"`. Unsupported types (`"image"`, `"pdf"`, `"file"`, `"github"`) are rejected until dedicated ingestion flows are built.
- **URL Captures**:
  - `original_url`: Required, must be a valid absolute HTTP or HTTPS URL (schemes like `file://` or `javascript:` are rejected).
  - `title`, `content`, `mime_type`, `source_id`, `metadata`: Optional.
- **Text Captures**:
  - `content`: Required, must not be empty or whitespace-only.
  - `title`, `metadata`: Optional.
- **Atomicity**: If `metadata` is provided, `Capture` and `SourceMetadata` are persisted in a single atomic database transaction. If metadata persistence fails, the entire transaction rolls back.

**Example Request — URL Capture**:
```bash
curl -X POST http://localhost:8000/captures \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "url",
    "original_url": "https://fastapi.tiangolo.com",
    "title": "FastAPI Documentation",
    "metadata": {"tags": ["python", "api"], "reading_priority": "high"}
  }'
```

**Example Request — Text Capture**:
```bash
curl -X POST http://localhost:8000/captures \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "text",
    "title": "Architecture Thoughts",
    "content": "Decoupling ingestion from chunking ensures fast capture response times."
  }'
```

**Example Response (`201 Created`)**:
```json
{
  "id": "1804f326-fa42-4916-834c-687f8f9024f0",
  "source_type": "url",
  "title": "FastAPI Documentation",
  "original_url": "https://fastapi.tiangolo.com",
  "content": null,
  "mime_type": null,
  "source_id": null,
  "created_at": "2026-10-02T10:30:00Z",
  "updated_at": "2026-10-02T10:30:00Z"
}
```

##### 2. `GET /captures`
Lists captures using deterministic pagination ordered newest-first (`created_at DESC, id DESC`). Does not load unneeded relationships.

**Query Parameters**:
- `limit`: Integer, default `20`, minimum `1`, maximum `100`.
- `offset`: Integer, default `0`, minimum `0`.

**Example Request**:
```bash
curl "http://localhost:8000/captures?limit=10&offset=0"
```

**Example Response (`200 OK`)**:
```json
{
  "items": [
    {
      "id": "1804f326-fa42-4916-834c-687f8f9024f0",
      "source_type": "url",
      "title": "FastAPI Documentation",
      "original_url": "https://fastapi.tiangolo.com",
      "content": null,
      "mime_type": null,
      "source_id": null,
      "created_at": "2026-10-02T10:30:00Z",
      "updated_at": "2026-10-02T10:30:00Z"
    }
  ],
  "limit": 10,
  "offset": 0,
  "total": 1
}
```

##### 3. `GET /captures/{capture_id}`
Retrieves a specific capture by UUID. If source metadata exists for the capture, it is included in the response.

**Behavior**:
- Returns `200 OK` with capture details and `metadata: dict | null`.
- Returns `404 Not Found` if the UUID is valid but does not exist.
- Returns `422 Unprocessable Entity` if the `capture_id` is not a valid UUID.

**Example Request**:
```bash
curl http://localhost:8000/captures/1804f326-fa42-4916-834c-687f8f9024f0
```

**Example Response (`200 OK`)**:
```json
{
  "id": "1804f326-fa42-4916-834c-687f8f9024f0",
  "source_type": "url",
  "title": "FastAPI Documentation",
  "original_url": "https://fastapi.tiangolo.com",
  "content": null,
  "mime_type": null,
  "source_id": null,
  "created_at": "2026-10-02T10:30:00Z",
  "updated_at": "2026-10-02T10:30:00Z",
  "metadata": {
    "tags": ["python", "api"],
    "reading_priority": "high"
  }
}
```

#### Current Scope Limitations

> [!IMPORTANT]
> Stage 5 focuses strictly on reliable ingestion and persistence:
> - **URL content is NOT fetched yet**: The API stores the URL and user-supplied fields. No HTTP crawling or scraping is executed.
> - **Files and media are NOT uploaded yet**: Binary upload handlers and S3 bucket synchronization are not active.
> - **Embeddings and chunks are NOT generated yet**: Background processing pipelines and pgvector population are planned for worker stages.
> - **Authentication is NOT implemented yet**: Endpoints are currently unauthenticated; JWT and tenant isolation will be integrated in upcoming auth stages.
> - **No background queues**: Redis tasks are not yet dispatched on capture creation.

---

## Development Principles

1. **Separation of Concerns**: Client applications (Web, Mobile) consume standard API contracts; backend services (API, Worker) decouple ingestion from processing.
2. **Asynchronous by Default**: Heavy tasks (embedding calculations, OCR, large link scraping) must never block API responses; they are handled via worker queues.
3. **Reproducible Environments**: Local development dependencies and databases run in containerized environments with pinned versions.
4. **Resilient Data Capture**: Ingestion endpoints must acknowledge receipt quickly, persist raw payloads first, and process transformations idempotently.

---

## Security & Secrets Management

> [!CAUTION]
> **CRITICAL RULE**: Secrets, API keys, private tokens, certificates, and `.env*` files **MUST NEVER** be committed to version control.

* All environment configurations must be supplied via local uncommitted `.env` files or system environment variables.
* Reference templates must be provided exclusively as `.env.example` or `.env.*.example`.
* The root `.gitignore` enforces strict ignoring of credential and environment files.