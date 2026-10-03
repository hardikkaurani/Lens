# LENS — Architecture Specification

> **Document Status**: Stage 9 Active Implementation (Flutter Mobile Client Foundation)  
> **Implementation State**: Core infrastructure, database domain models, capture ingestion API, asynchronous URL ingestion worker, embedding generation pipeline, PostgreSQL full-text search, pgvector similarity search, hybrid search endpoint, Next.js web workspace (`apps/web`), and Flutter mobile client (`apps/mobile`) are **ACTIVE**. Authentication, GitHub sync, offline SQLite storage, and advanced recommendation engines remain **PLANNED**.

---

## 1. Product Goal

The objective of **LENS** is to provide an effortless, personal information capture and retrieval system. Modern digital work leaves an overwhelming trail of research, documentation, code repositories, discussions, and quick ideas scattered across disjointed platforms.

LENS solves this fragmentation through a four-phase lifecycle:

1. **Capture**: Instant ingestion from any device with minimal cognitive load.
2. **Understand**: Deep extraction, automated chunking, and contextual enrichment.
3. **Connect**: Semantic indexing, tagging, and cross-reference association.
4. **Retrieve**: High-precision hybrid search that accurately resurfaces relevant information even when exact keywords are forgotten.

---

## 2. System Overview

```mermaid
flowchart TD
    subgraph Clients [Clients - PLANNED]
        Web["Web Application\n(Next.js + TypeScript)"]
        Mobile["Mobile Application\n(Flutter + Dart)"]
    end

    subgraph ServiceLayer [Service Layer - PLANNED]
        API["Core API Service\n(FastAPI / Python)"]
        Worker["Background Processing Worker\n(Python)"]
    end

    subgraph StorageLayer [Storage & Infrastructure - PLANNED]
        PG[("PostgreSQL\n+ pgvector")]
        Redis[("Redis\n(Task Queue & Cache)")]
        S3[("Object Storage\n(S3-Compatible / MinIO)")]
    end

    subgraph External [External Integrations - PLANNED]
        GitHub["GitHub API & Webhooks"]
    end

    Web -->|REST / JSON| API
    Mobile -->|REST / JSON| API
    GitHub -.->|Webhooks / OAuth| API

    API -->|Read / Write Metadata| PG
    API -->|Enqueue Jobs / Rate Limit| Redis
    API -->|Upload Raw Objects| S3

    Worker -->|Consume Queue| Redis
    Worker -->|Read Raw Payloads| S3
    Worker -->|Write Chunks & Embeddings| PG
```

---

## 3. Component Responsibilities

### 3.1 Web Application (`apps/web/`) — *ACTIVE IMPLEMENTATION (STAGE 8)*

* **Technology**: Next.js 16 (App Router, Turbopack), React 19, TypeScript 5, TailwindCSS v4, Vitest, Testing Library.
* **Responsibilities**:
  * Unified personal information workspace interface (`/captures`).
  * Capture ingestion interface for URLs and quick text notes (`/captures/new`).
  * Detailed capture inspector (`/captures/[id]`) rendering metadata, chunk extractions, and processing lifecycle states.
  * Real-time hybrid search explorer (`/search`) displaying rank scores, excerpts, and search diagnostics.
  * Centralized, strongly-typed API client with error normalization and zero credential exposure.
  * Responsive, accessible layout shell (`AppShell`) with live API health status monitoring.

### 3.2 Mobile Application (`apps/mobile/`) — *ACTIVE IMPLEMENTATION (STAGE 9)*

* **Technology**: Flutter 3.41+, Dart 3.11+, Material 3, Android SDK 36+.
* **Responsibilities**:
  * Cross-platform Android capture and retrieval client.
  * Instant capture creation interface for web URLs and text notes (`NewCaptureScreen`).
  * Paginated capture list with newest-first ordering, status indicators, and pull-to-refresh (`CapturesScreen`).
  * Capture detail inspector displaying processing status, chunks, and metadata with bounded polling (`CaptureDetailScreen`).
  * Hybrid search screen querying the FastAPI backend with relevance score breakdowns (`SearchScreen`).
  * In-app server configuration with health check ping and LAN IP switching (`ServerConfigDialog`).
  * Scoped cleartext development networking configuration strictly isolated to debug builds.

### 3.3 Backend API Service (`services/api/`) — *ACTIVE FOUNDATION, CAPTURES & SEARCH (STAGE 7)*

* **Technology**: FastAPI, Python 3.11+, Pydantic, Pydantic-Settings, SQLAlchemy (asyncio), AsyncPG, Redis (asyncio), pgvector.
* **Current Architectural Implementation (Stage 7)**:
  * **Core Application**: Minimal ASGI entrypoint (`app/main.py`) with lifespan management for graceful resource shutdown. Registers `health_router`, `captures_router`, and `search_router`.
  * **Configuration Layer (`app/core/config.py`)**: Centralized settings backed by `pydantic-settings`. Loads from root `.env` when present, normalizes PostgreSQL DSNs for `asyncpg`, and avoids hardcoded secrets. Includes embedding provider configuration, batch sizes, timeouts, and hybrid search weights ($W_{lex}, W_{sem}$).
  * **Async PostgreSQL Layer (`app/db/session.py`)**: `AsyncEngine` with connection pooling (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`) and active ping validation (`SELECT 1`).
  * **Redis Connectivity (`app/db/session.py`)**: Dedicated asynchronous Redis client providing connection reuse and active `PING` validation.
  * **Health Check Subsystem (`app/health/router.py`)**: Live `GET /health` endpoint verifying end-to-end connectivity to PostgreSQL and Redis. Emits `200 OK` when healthy and `503 Service Unavailable` with degraded status if any dependency fails, without leaking credentials or stack traces.
  * **Capture Ingestion Subsystem (`app/captures/`)**:
    * `POST /captures`: Atomic ingestion of URL or text captures. Validates schema inputs, handles optional metadata, and ensures atomic transaction rollback on failure. Returns `201 Created`.
    * `GET /captures`: Deterministic pagination (`limit`, `offset`) ordered by `created_at` descending.
    * `GET /captures/{capture_id}`: Single capture retrieval with attached source metadata, returning `404 Not Found` for nonexistent records and `422` for malformed UUIDs.
  * **Embedding Provider Subsystem (`app/embeddings/`)**:
    * Clean `EmbeddingProvider` protocol with async `embed_text(text)` and `embed_texts(texts)`.
    * Strict 1536-dimensional float vector validation: enforces exact dimension, rejects NaN/infinite values, and guards against malformed inputs.
    * `OpenAIEmbeddingProvider`: HTTPX-based client for `text-embedding-3-small` with configurable batch size, timeout, exponential backoff retries, and complete credential masking.
    * `DeterministicTestEmbeddingProvider`: SHA-256 token-hash based vector generator ensuring 100% deterministic test vectors for CI/test suites without external network calls.
    * Lazy provider factory (`app/embeddings/factory.py`) with test override support and safe development fallback.
  * **Search Subsystem (`app/search/`)**:
    * `GET /search`: Hybrid search endpoint combining PostgreSQL full-text search (`websearch_to_tsquery`) and pgvector cosine distance search (`<=>`).
    * Result grouping: Groups results by parent `capture_id`, preserving best matching chunks with excerpt snippets and signal breakdown (`lexical_score`, `semantic_score`, `hybrid_score`).
    * Degraded execution: Automatically falls back to lexical-only search if the embedding provider fails or is unconfigured, without failing client requests.
* **Planned Product Responsibilities (*NOT YET IMPLEMENTED*)**:
  * Authentication & user management: JWT generation, verification, and tenant isolation.
  * External webhook receipt and validation (e.g., GitHub webhooks).

### 3.4 Background Worker (`services/worker/`) — *ACTIVE INGESTION, EXTRACTION & EMBEDDING WORKER (STAGE 7)*

* **Technology**: Python 3.11+, BeautifulSoup4, HTTPX, SQLAlchemy (asyncio), AsyncPG, Redis (asyncio), pgvector.
* **Current Architectural Implementation (Stage 7)**:
  * **Worker Core (`worker/main.py`)**: Asynchronous worker process supporting continuous loop execution and single-job test execution (`--once`). Graceful shutdown on SIGINT/SIGTERM.
  * **Job Transport (`app/queue/job.py`)**: Redis list queue (`lens:jobs:url_ingest`) using atomic `BLMOVE` to an in-progress queue (`lens:jobs:url_ingest:processing`) for at-least-once delivery without destructive pops.
  * **SSRF-Safe Fetcher (`worker/fetcher.py`)**: Hardened HTTP fetcher validating schemes, ports, credentials, resolved IPs, and redirect destinations. Prevents DNS rebinding by connecting directly to the validated IP. Enforces 2MB streaming limit, timeouts, and HTML content types.
  * **HTML Extractor & Normalizer (`worker/extractor.py`)**: Strips scripts, styles, navigation, headers, footers, and noise tags via BeautifulSoup. Normalizes line breaks and whitespace. Rejects empty or unusable pages.
  * **Deterministic Chunker (`worker/chunker.py`)**: Partitions clean text into deterministic 1000-character sequential chunks with 150-character overlap, prioritizing structural sentence and paragraph breaks.
  * **Embedding Generation & Atomic Persistence (`worker/processor.py`)**: Batch-generates 1536-dimensional embeddings for all extracted chunks via `embed_texts()`. Idempotently replaces previous chunks for the capture and persists `ContentChunk` records with valid vectors atomically.
  * **Lifecycle & Error Sanitization**: Transitions `captures.processing_status` to `completed` only upon successful embedding persistence. If embedding or extraction fails, transitions to `failed` and records a sanitized, secret-free diagnostic message.
* **Planned Processing Responsibilities (*NOT YET IMPLEMENTED*)**:
  * PDF parsing, document extraction, and image OCR.
  * S3/MinIO binary payload storage.
  * Periodic synchronization of external data sources (e.g., GitHub starred repositories).

---

## 4. End-to-End Data Flow

### 4.1 Asynchronous URL Ingestion Pipeline (Stage 6 Implementation)

```text
Client
  ↓
POST /captures (source_type = "url")
  ↓
PostgreSQL (Capture record persisted, processing_status: "pending")
  ↓
Redis Job (Pushed to "lens:jobs:url_ingest")
  ↓ [API returns HTTP 201 immediately with processing_status="pending"]
Worker (BLMOVE atomically moves job to "lens:jobs:url_ingest:processing")
  ↓
SSRF-Safe Fetcher (validates scheme, host, resolved IPs, redirects, 2MB limit, timeouts)
  ↓
HTML Extraction (BeautifulSoup decomposes scripts/styles/noise)
  ↓
Normalization (standardizes line breaks, collapses excess whitespace)
  ↓
Chunking (deterministic character window with overlap)
  ↓
ContentChunk Records (PostgreSQL persistence; embedding remains NULL)
  ↓
completed (Capture status updated to "completed", processed_at populated; Redis job acked)
```

#### SSRF Security Model & Network Safeguards

The ingestion pipeline employs strict defense-in-depth protections against Server-Side Request Forgery (SSRF) and malicious remote targets:

1. **Protocol & Syntax Validation**:
   * Accepts exclusively `http://` and `https://` schemes. All other protocols (`file://`, `ftp://`, `javascript:`, `data:`) are rejected immediately.
   * Prohibits embedded credentials in URLs (`http://user:pass@host/`).
   * Restricts ports to standard HTTP/HTTPS ports (80, 443, 8080, 8443).
2. **DNS Resolution & IP Filtering**:
   * Hostnames are resolved to IP addresses via `getaddrinfo` prior to socket connection.
   * Every resolved IP address is validated against prohibited network blocks:
     * IPv4 loopback (`127.0.0.0/8`), `0.0.0.0`, and IPv6 loopback (`::1`).
     * RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
     * Link-local and cloud metadata addresses (`169.254.0.0/16`, `fe80::/10`).
     * Carrier-grade NAT (`100.64.0.0/10`), multicast (`224.0.0.0/4`, `ff00::/8`), reserved (`240.0.0.0/4`), and IPv4-mapped IPv6.
3. **Anti-DNS Rebinding Architecture**:
   * The fetcher utilizes a custom network backend (`SSRFSafeNetworkBackend`) that establishes the TCP socket directly to the validated IP address rather than allowing the HTTP client to perform an unvalidated re-resolution.
4. **Controlled Redirect Following**:
   * Redirects are processed manually up to a maximum limit of 5 hops.
   * Every redirect location is fully re-validated through the entire SSRF verification chain before following.
5. **Streaming & Size Bounds**:
   * Imposes strict connect timeout (5s), read timeout (10s), and total timeout (15s).
   * Responses are streamed in chunks and aborted immediately if the response body exceeds 2MB.
   * Validates `Content-Type` header: only `text/html` and `application/xhtml+xml` are accepted. Images, binaries, PDFs, and non-HTML media are safely rejected.

> [!IMPORTANT]
> **Stage 6 Embedding Boundary**:
> The `content_chunks.embedding` column is populated strictly as **NULL**. Vector embeddings, embedding model integrations (OpenAI / Gemini / Ollama), and pgvector similarity searches are **NOT** implemented in Stage 6.

### 4.2 Full Asynchronous Processing Pipeline (Planned)

```text
[Client]                [API]               [Storage / Queue]           [Worker]
   │                      │                         │                      │
   │── 1. Ingest item ───>│                         │                      │
   │                      │── 2. Save raw record ──>│ [PostgreSQL / S3]    │
   │                      │── 3. Enqueue job ──────>│ [Redis Queue]        │
   │<── 4. 202 Accepted ──│                         │                      │
   │                      │                         │                      │
   │                      │                         │<── 5. Pull job ──────│
   │                      │                         │── 6. Fetch raw ─────>│
   │                      │                         │                      │── 7. Chunk & Embed
   │                      │                         │<── 8. Store vectors ─│
```

1. **Ingestion**: Client sends a capture payload (URL, text, or file) to the API.
2. **Persistence**: API saves the base capture record in PostgreSQL and offloads any large binary payload directly to S3-compatible storage.
3. **Queueing**: A processing event is dispatched to Redis.
4. **Immediate Response**: API returns `202 Accepted` (or `201 Created` with a pending status) to ensure the client is never blocked.
5. **Worker Execution**: Worker pulls the job from Redis, extracts meaningful textual content, splits it into semantic chunks, and generates embeddings.
6. **Indexing**: Processed chunks and their vector representations are committed back to PostgreSQL (`pgvector`), updating the capture item status to `READY`.

---

## 5. Local Infrastructure & Storage Subsystems (Stage 2 Foundation)

> [!NOTE]
> The backing storage and caching services defined below are established as **local infrastructure foundations** via `infra/docker-compose.yml`. They represent running containerized infrastructure; application-level database schemas, ORM models, migrations, queue consumers, and bucket management remain **PLANNED** for upcoming stages.

### 5.1 PostgreSQL + `pgvector` (Active Domain Schema — Stage 4)

* **Infrastructure Implementation**: Container `lens-postgres` running `pgvector/pgvector:pg16` on host port `5432` with persisted named volume `lens_postgres_data`.
* **Core Domain Entities (`services/api/app/db/models.py`)**:
  * **`Capture`**: The central entity representing a captured artifact.
    * `id`: UUID (Primary Key)
    * `source_type`: `source_type` Enum (`url`, `text`, `image`, `pdf`, `file`, `github`)
    * `title`: String(512), nullable
    * `original_url`: Text, nullable
    * `content`: Text, nullable
    * `mime_type`: String(128), nullable
    * `source_id`: String(256), nullable (indexed for fast external lookups)
    * `created_at` / `updated_at`: Timezone-aware timestamps with automatic triggers
  * **`Capture`**: The central entity representing a captured artifact.
    * `id`: UUID (Primary Key)
    * `source_type`: `source_type` Enum (`url`, `text`, `image`, `pdf`, `file`, `github`)
    * `title`: String(512), nullable
    * `original_url`: Text, nullable
    * `content`: Text, nullable
    * `mime_type`: String(128), nullable
    * `source_id`: String(256), nullable (indexed for fast external lookups)
    * `tsv`: `TSVECTOR` generated column (`to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))`, indexed via GIN `ix_captures_tsv`)
    * `created_at` / `updated_at`: Timezone-aware timestamps with automatic triggers
  * **`ContentChunk`**: Searchable partitioned content units derived from a parent capture.
    * `id`: UUID (Primary Key)
    * `capture_id`: UUID, Foreign Key to `captures.id` (`ON DELETE CASCADE`)
    * `chunk_index`: Integer, required (composite unique constraint `uq_content_chunks_capture_chunk`)
    * `content`: Text, required
    * `embedding`: `Vector(1536)`, nullable (active pgvector storage populated by worker pipeline)
    * `tsv`: `TSVECTOR` generated column (`to_tsvector('english', coalesce(content, ''))`, indexed via GIN `ix_content_chunks_tsv`)
    * `created_at`: Timezone-aware timestamp
  * **`SourceMetadata`**: 1-to-1 extension table holding arbitrary source-specific attributes without schema bloating.
    * `id`: UUID (Primary Key)
    * `capture_id`: UUID, Unique Foreign Key to `captures.id` (`ON DELETE CASCADE`)
    * `metadata`: PostgreSQL `JSONB`, required (default `{}`)
    * `created_at` / `updated_at`: Timezone-aware timestamps

#### Entity Relationship Diagram

```mermaid
erDiagram
    CAPTURES ||--o{ CONTENT_CHUNKS : "has (1:N, cascade)"
    CAPTURES ||--o| SOURCE_METADATA : "has (1:1, cascade)"

    CAPTURES {
        uuid id PK
        source_type source_type "enum('url','text','image','pdf','file','github')"
        varchar title "nullable"
        text original_url "nullable"
        text content "nullable"
        varchar mime_type "nullable"
        varchar source_id "nullable, indexed"
        tsvector tsv "generated, GIN indexed"
        timestamptz created_at "indexed"
        timestamptz updated_at
    }

    CONTENT_CHUNKS {
        uuid id PK
        uuid capture_id FK "captures.id, cascade"
        int chunk_index "unique per capture"
        text content "chunk text"
        vector_1536 embedding "nullable, active pgvector"
        tsvector tsv "generated, GIN indexed"
        timestamptz created_at
    }

    SOURCE_METADATA {
        uuid id PK
        uuid capture_id FK "captures.id, unique, cascade"
        jsonb metadata "arbitrary structured attributes"
        timestamptz created_at
        timestamptz updated_at
    }
```

* **Vector Embeddings & Full-Text Search Columns (Stage 7)**:
  > [!NOTE]
  > At Stage 7, the `embedding` column on `content_chunks` is actively populated with 1536-dimensional unit float vectors generated during worker ingestion. In addition, PostgreSQL `TSVECTOR` stored generated columns and GIN indexes (`ix_captures_tsv`, `ix_content_chunks_tsv`) provide native full-text indexing across titles and content chunks.

### 5.2 Redis

* **Infrastructure Implementation**: Container `lens-redis` running `redis:7.4.7-alpine` on host port `6379` with persisted named volume `lens_redis_data` and append-only persistence enabled.
* **Background Job Queue (`app/queue/job.py`)**:
  * High-throughput asynchronous broker coordinating work between `services/api` and `services/worker`.
  * Reliable task distribution for link scraping, text extraction, chunking, and vector calculation via atomic `BLMOVE` and `LREM`.
* **Caching (*PLANNED*)**:
  * Low-latency caching for frequent search queries, resolved metadata, and user session state.
* **Rate Limiting (*PLANNED*)**:
  * Token bucket / sliding window rate limiting on public and ingestion API endpoints.

### 5.3 MinIO (S3-Compatible Object Storage) — *ACTIVE BASELINE (STAGE 11)*

* **Infrastructure Implementation**: Container `lens-minio` running `minio/minio:RELEASE.2025-09-07T16-13-09Z` on host port `9000` (S3 API) and `9001` (Web Console) with persisted named volume `lens_minio_data`.
* **Local S3-Compatible Storage**:
  * Drop-in replacement for AWS S3 / Cloudflare R2 in local development.
  * Standard S3 SDK (`minio` package) compatibility across API and worker services.
  * Encapsulated via `StorageClient` (`app.storage`) with unified operations: `put_object`, `get_object`, `stat_object`, `delete_object`, `ensure_bucket_exists`.
* **Secure Object Key Generation**:
  * Cryptographically safe internal object keys: `captures/<capture_id>/<object_uuid>.pdf`.
  * User-provided filenames are strictly excluded from storage paths to prevent path traversal.
* **File Upload & Validation**:
  * Dedicated endpoint: `POST /captures/upload` accepting `multipart/form-data`.
  * Bounded streaming read enforcing `MAX_UPLOAD_SIZE_BYTES` (default 10MB) and incremental SHA-256 calculation.
  * Strict validation: `application/pdf` MIME type and `%PDF-` magic bytes header check.
* **PDF Processing Pipeline**:
  * Job Queue: `lens:jobs:file_ingest` with reliable `BLMOVE` / `LMOVE` delivery.
  * Extraction: `pypdf`-based text extraction preserving page order, rejecting password-protected/encrypted PDFs, and enforcing memory bounds (max 500 pages, max 2M characters).
  * Ingestion: Extracted text is fed into the existing deterministic chunker (`chunk_text`) and embedding provider (`embed_texts`).
  * Atomic Persistence: Existing chunks replaced and new chunks persisted in `content_chunks` within a single database transaction.
* **Consistency & Cleanup Semantics**:
  * If database persistence fails after storage put, the orphaned S3 object is immediately cleaned up.
  * If Redis enqueue fails, capture status is set to `failed` while the object is preserved in S3 for safe retry.
* **Explicit Scope Boundary**:
  * OCR and image-to-text processing are explicitly deferred; scanned or image-only PDFs with no readable text fail with a clean user-facing error.


---

## 6. GitHub Integration Direction — *PLANNED*

* **OAuth Ingestion**: Secure authorization granting read access to public/private repositories, starred items, and gists.
* **Webhook Receiver**: Webhook listeners to capture new stars, issue updates, and pull requests in near real-time.
* **Sync Engine**: Periodic background reconciliation ensuring external updates are continuously indexed.

---

## 7. Search & Retrieval Architecture — *ACTIVE BASELINE (STAGE 7)*

> [!IMPORTANT]
> Stage 7 establishes a **production-quality baseline search foundation**. It is deliberately designed as a transparent, deterministic retrieval system rather than a complex, opaque machine learning ranking or recommendation engine.

LENS implements a deterministic **Hybrid Retrieval** pipeline combining lexical precision with semantic understanding:

```text
Search Query ("python fastapi")
         │
         ├─── Lexical Search (PostgreSQL GIN tsvector) ───────────────> Lexical Score S_lex
         │
         └─── Semantic Search (pgvector cosine distance <=>) ─────────> Semantic Score S_sem
                                                                               │
                                                                               ▼
                                                                     Hybrid Ranking Formula
                                                            S_hybrid = W_lex*S_lex + W_sem*S_sem
                                                                               │
                                                                               ▼
                                                                     Group by Capture ID
                                                                               │
                                                                               ▼
                                                                       Search Response
```

### 7.1 Lexical Search Engine

* **PostgreSQL Native Full-Text Search**: Uses `websearch_to_tsquery('english', :query)` against `tsvector` columns on `captures` and `content_chunks`.
* **Safe User Input Handling**: `websearch_to_tsquery` natively handles natural search phrases, quotes, and `-` exclusions while preventing syntax errors from raw symbols, unbalanced quotes, or punctuation.
* **Ranking**: Lexical relevance is computed via `ts_rank_cd(content_chunks.tsv, query)` using cover density ranking.
* **Indexes**: GIN indexes (`ix_captures_tsv` and `ix_content_chunks_tsv`) ensure fast lookups without unindexed table scans.

### 7.2 Semantic Vector Search Engine

* **pgvector Cosine Distance**: Evaluated using PostgreSQL's native vector distance operator:
  $$\text{distance} = \text{embedding} \Leftrightarrow \text{query\_vector}$$
* **Dimension Contract**: Enforces strict 1536-dimensional floating point vectors. Queries with mismatched or non-finite vector dimensions are rejected before hitting PostgreSQL.
* **Filtering & Thresholding**: Queries only evaluate valid, non-null embeddings. A configurable similarity threshold (`VECTOR_SIMILARITY_THRESHOLD = 0.2`, corresponding to maximum cosine distance of 0.8) ensures completely unrelated queries do not return arbitrary nearest neighbors.

### 7.3 Deterministic Hybrid Ranking Formula

To combine lexical and semantic signals without arbitrary score inflation, scores are individually normalized to the range $[0.0, 1.0]$:

1. **Normalized Lexical Score**:
   $$S_{lex} = \min\left(1.0, \frac{\text{ts\_rank\_cd}}{0.5}\right)$$
2. **Normalized Semantic Score**:
   $$S_{sem} = \max(0.0, 1.0 - \text{cosine\_distance})$$
3. **Combined Hybrid Score**:
   $$S_{hybrid} = W_{lex} \cdot S_{lex} + W_{sem} \cdot S_{sem}$$
   * Configurable weights: `HYBRID_LEXICAL_WEIGHT` (default `0.5`), `HYBRID_SEMANTIC_WEIGHT` (default `0.5`).
   * When both signals match, the document receives a boosted score reflecting both exact token presence and semantic relevance.
4. **Stable Deterministic Tie-Breaking**:
   $$\text{ORDER BY } S_{hybrid} \text{ DESC}, \text{chunk\_index ASC}, \text{id ASC}$$

### 7.4 Result Grouping & Excerpts

* **Capture-Level Grouping**: Multiple matching chunks from the same capture are grouped under that capture's entry in the response to prevent result duplication.
* **Ordering Semantics**: Captures are ordered by the highest hybrid score among their constituent matching chunks. Within each capture, chunks are ordered by individual chunk hybrid score descending.
* **Contextual Excerpts**: Text excerpts are cleanly truncated (up to 200 characters) with trailing ellipses.

### 7.5 Degraded & Failure Behavior

* **Search Fallback**: If the embedding provider is unavailable or unconfigured, the search endpoint gracefully falls back to lexical-only search ($S_{hybrid} = S_{lex}$) without crashing, logging a warning, and setting `semantic_score = None`.
* **Worker Resilience**: If embedding generation fails during ingestion, the capture transitions to `failed` and records a sanitized diagnostic message in `processing_error`. It is never prematurely marked `completed`.

### 7.6 Future Vector Index Upgrade Path

* **Current Scale**: In Stage 7, pgvector uses exact flat scan (`ORDER BY embedding <=> :query_vector`). At initial corpus sizes (<10,000 chunks), flat scans provide 100% recall with sub-millisecond query execution.
* **Future Upgrade**: As corpus size scales, an Alembic migration can add an HNSW index without application code changes:

  ```sql
  CREATE INDEX ix_content_chunks_embedding_hnsw 
  ON content_chunks USING hnsw (embedding vector_cosine_ops);
  ```

---

## 8. Authentication & Authorization Direction — *PLANNED*

* **Phase 1 (Initial)**: Stateless JSON Web Tokens (JWT) signed with HMAC-SHA256 / RS256.
  * Short-lived access tokens accompanied by securely stored refresh tokens.
  * Password hashing utilizing Argon2id or bcrypt.
* **Phase 2 (Extensible)**: Social authentication providers (GitHub OAuth first-class integration, followed by Google).
* **Multi-Tenancy**: Strict tenant isolation across all database queries ensuring private data is never exposed across users.

---

## 9. Web Workspace Architecture & Integration (Stage 8)

The LENS web workspace (`apps/web/`) is built with Next.js 16 (App Router), React 19, TypeScript 5, and TailwindCSS v4. It acts as the user's primary desktop knowledge workbench.

```mermaid
flowchart LR
    subgraph Browser ["Web Browser (apps/web)"]
        Shell["AppShell & Nav"]
        CapturesView["/captures (List)"]
        NewView["/captures/new (Create)"]
        DetailView["/captures/[id] (Inspect)"]
        SearchView["/search (Hybrid Search)"]
        Client["apiClient (Typed Client)"]
    end

    subgraph Backend ["FastAPI Service (services/api)"]
        APIEndpoints["/captures\n/search\n/health"]
    end

    Shell --> Client
    CapturesView --> Client
    NewView --> Client
    DetailView --> Client
    SearchView --> Client
    Client -->|HTTP / JSON via NEXT_PUBLIC_API_BASE_URL| APIEndpoints
```

### 9.1 Core Responsibilities & Boundaries

* **Personal Workspace Philosophy**: The interface is intentionally structured as a high-density, focused personal knowledge workspace rather than a public marketing landing page.
* **Backend Authoritative State**: The web application maintains zero redundant business logic. All validation, ingestion states, chunk extractions, search rankings, and processing error diagnoses originate from the FastAPI backend.
* **Mobile Client Deferral**: The mobile application (`apps/mobile/`) is strictly deferred to **Stage 9** (Flutter). The web application provides a responsive layout that scales down to narrow mobile viewports without horizontal overflow, but is not a mobile app substitute.

### 9.2 Centralized Typed API Client (`src/lib/api-client.ts`)

* **Endpoint Centralization**: All HTTP interactions are encapsulated in `apiClient`. Direct `fetch()` calls inside React UI components are strictly prohibited.
* **Environment Configuration**: `NEXT_PUBLIC_API_BASE_URL` specifies the backend root (defaulting safely to `http://localhost:8000` for local development).
* **Credential Isolation**: Client configuration never receives server-side secrets, database passwords, Redis credentials, or OpenAI API keys.
* **Error Normalization**: Maps HTTP status codes, network disconnects, timeouts, and Pydantic 422 validation structures into user-friendly `ApiClientError` objects without exposing internal Python tracebacks or database connection URIs.
* **Timeout & Abort**: Built-in 15-second request timeout and support for caller `AbortSignal` instances.

### 9.3 Ingestion Workflow

1. **Creation**:
   * **URL Ingestion**: User inputs target URL and optional title. Client-side regex verifies supported `http:` / `https:` schemes.
   * **Text Ingestion**: User submits a title and multi-line text note. Client ensures non-whitespace content.
2. **Persistence**:
   * Submits `POST /captures`. The API creates the capture record atomically.
   * For URLs, the backend enqueues a background extraction job in Redis and returns `201 Created` with `processing_status="pending"`. The frontend immediately updates without waiting for background fetching.
3. **Detail & Monitoring**:
   * Redirects immediately to `/captures/[id]`.
   * For `pending` and `processing` captures, the view initiates bounded polling (maximum 10 attempts at 3-second intervals). Polling halts immediately once the capture reaches `completed` or `failed`, or when the user navigates away.

### 9.4 Hybrid Search Workflow

1. **Search Submission**:
   * User enters a query into `/search`. Search triggers on Enter or button click (not on every keystroke to avoid request floods).
   * Synchronizes search term to URL parameters (`/search?q=...`) for bookmarkable search queries.
2. **Race-Condition Safety**:
   * Tracks an incremental `latestRequestIdRef` and aborts preceding in-flight searches via `AbortController`.
   * Stale asynchronous responses arriving out of order are discarded deterministically.
3. **Signal Visualization**:
   * Displays aggregated results by capture, with matching chunks, contextual excerpt snippets, and visual score breakdown (`Hybrid`, `Semantic`, `Lexical`).
   * Indicates when the backend operates in lexical-only degraded mode if vector embedding providers are unconfigured.

### 9.5 Security Audit Controls

* **XSS Defense**: Captured webpage content and text notes are rendered strictly through standard React string interpolation as text nodes; `dangerouslySetInnerHTML` is prohibited.
* **URL Injection Defense**: External URLs pass through `sanitizeUrl()`, which parses URLs via `new URL()` and rejects `javascript:`, `data:`, `vbscript:`, or relative links.
* **Error Sanitization**: Server-side 500 errors and tracebacks are intercepted and replaced with user-safe status summaries.

---

## 10. Flutter Mobile Client Architecture & Device Connectivity (Stage 9)

The LENS mobile application (`apps/mobile/`) is a Flutter Android application designed as an on-the-go capture and search tool.

```mermaid
flowchart TD
    subgraph MobileDevice ["Android Mobile Phone (apps/mobile)"]
        Nav["MainNavigationShell\n(Captures / Search / New)"]
        CapturesUI["CapturesScreen\n(Paginated List)"]
        NewUI["NewCaptureScreen\n(URL & Text Ingestion)"]
        DetailUI["CaptureDetailScreen\n(Chunks & Bounded Polling)"]
        SearchUI["SearchScreen\n(Hybrid Query UI)"]
        MobileClient["ApiClient\n(HTTP / JSON Client)"]
        Config["ApiConfig\n(Runtime & Env Base URL)"]
    end

    subgraph LaptopHost ["Laptop Host (Local Development)"]
        FastAPI["FastAPI Server\n(services/api on :8000)"]
    end

    Nav --> CapturesUI
    Nav --> SearchUI
    Nav --> NewUI
    CapturesUI --> DetailUI
    SearchUI --> DetailUI
    CapturesUI --> MobileClient
    NewUI --> MobileClient
    DetailUI --> MobileClient
    SearchUI --> MobileClient
    MobileClient --> Config
    MobileClient -->|HTTP / JSON via Wi-Fi LAN or adb reverse| FastAPI
```

### 10.1 Architecture & Component Boundaries

* **State & Networking**: Clean, lightweight architecture using pure Flutter/Dart primitives and the official `http` package. No heavy, unnecessary state frameworks are introduced.
* **Error Normalization**: `ApiException` catches all HTTP status errors, socket disconnects, timeouts, and JSON errors, stripping internal server tracebacks or database URIs.
* **Bounded Polling**: While on `CaptureDetailScreen`, pending or processing captures poll the backend at 3-second intervals for at most 10 attempts (30 seconds max). Polling cancels immediately when completed or failed, or when the screen is popped.

### 10.2 API Base URL Configuration & Networking

* **Physical Device vs. Localhost**:
  * On a physical phone, `http://localhost:8000` refers to the phone itself.
  * To connect to the laptop backend, the phone connects via the laptop's LAN IP (e.g. `http://10.50.109.63:8000`) or via `adb reverse tcp:8000 tcp:8000` (`http://127.0.0.1:8000`).
* **Multi-Tier Configuration**:
  1. **Build-time Environment**: Set via `--dart-define=API_BASE_URL=http://<LAPTOP_LAN_IP>:8000`.
  2. **In-App Runtime Setting**: `ServerConfigDialog` accessible via the AppBar allows the developer or tester to view, test (`GET /health`), and switch between presets (LAN IP, Android Emulator `10.0.2.2`, or `adb reverse`) without recompiling.
  3. **Local Development Cleartext Boundary**: Cleartext (HTTP) traffic is strictly scoped to `android/app/src/debug/AndroidManifest.xml` via `android:usesCleartextTraffic="true"`. Release builds enforce secure HTTPS traffic by default.

### 10.3 Wireless Debugging & Real Device Setup

1. **Developer Options**: Enable *Developer options* and *Wireless debugging* on the Android device.
2. **Pairing (First time)**:

   ```bash
   adb pair <PHONE_IP>:<PAIRING_PORT> <PAIRING_CODE>
   ```

3. **Connecting**:

   ```bash
   adb connect <PHONE_IP>:<CONNECT_PORT>
   adb devices
   ```

4. **ADB Reverse Port Forwarding (Recommended for enterprise / isolated Wi-Fi)**:

   ```bash
   adb reverse tcp:8000 tcp:8000
   ```

   This routes `http://localhost:8000` on the phone directly to the laptop's FastAPI server, completely bypassing router client isolation.

### 10.4 Stage 10 Roadmap

* **Native Share Sheet**: Android `IntentFilter` (`ACTION_SEND`) to receive URLs and text shared from mobile browsers directly into LENS.
* **Offline Capture Queue**: SQLite storage for captures created while disconnected, syncing automatically upon network restoration.
