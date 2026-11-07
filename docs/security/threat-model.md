# LENS Security Threat Model & Forensic Audit

**Document Version:** 1.0.0  
**Stage:** 18.0 — Security Forensic Audit & Multi-Tenancy  
**Target Baseline:** `a6fe649e4c26b464dea98331416195262be6ca9a`  
**Classification:** Internal Engineering & Security Audit  

---

## 1. System Component Inventory & Data Flow Map

LENS is a developer knowledge capture and retrieval engine composed of six core components:

```
+-----------------------------------------------------------------------------------+
|                                  TRUST BOUNDARY 0                                 |
|                                (Untrusted External)                               |
|                                                                                   |
|  +--------------------+        +--------------------+        +-----------------+  |
|  | Next.js Web Client |        | Flutter Android App|        | GitHub OAuth API|  |
|  +---------+----------+        +---------+----------+        +--------+--------+  |
+------------|-----------------------------|----------------------------|-----------+
             | HTTPS                       | HTTPS                      | OAuth2 Redirect
             v                             v                            v
+-----------------------------------------------------------------------------------+
|                                  TRUST BOUNDARY 1                                 |
|                         (Public API Ingress / Insecure Edge)                      |
|                                                                                   |
|                              FastAPI Gateway (Port 8000)                          |
|         - Auth Router (/auth/*)                                                   |
|         - Captures Router (/captures/*)                                           |
|         - Search Router (/search)                                                 |
|         - GitHub Integration Router (/integrations/github/*)                      |
|                                                                                   |
+------------+-----------------------------+----------------------------+-----------+
             |                             |                            |
             | Internal Protocol           | Redis Task Queue           | S3 / Storage API
             v                             v                            v
+-----------------------+     +------------------------+     +----------------------+
|    TRUST BOUNDARY 2   |     |    TRUST BOUNDARY 3    |     |   TRUST BOUNDARY 4   |
|   PostgreSQL 16 +     |     |   Redis 7 (Broker)     |     |   MinIO Object Store |
|       pgvector        |     |         +              |     |  (Raw uploads & PDFs)|
|                       |     |   Background Worker    |     |                      |
| - Users               |     |                        |     +----------------------+
| - Captures            |     | - Processor Subsystem  |
| - Content Chunks      |     | - Embedding Engine     |
| - GitHub Connections  |     | - Scraping & Chunking  |
| - GitHub Repos/Acts   |     +------------------------+
+-----------------------+
```

### Data Flows

1. **Capture Ingestion (Direct Text / URL):**
   - Client sends payload (`content`, `source_type="url" | "note"`).
   - Gateway validates payload, persists `Capture` record with `user_id`.
   - If asynchronous extraction is required (URL scraping, document parsing), gateway enqueues job `{ "capture_id": "<uuid>" }` into Redis.
2. **File & PDF Ingestion:**
   - Client sends multipart file upload to `/captures/upload`.
   - Gateway validates file size and MIME type, writes file to MinIO object store at `captures/{user_id}/{capture_id}/{filename}`.
   - Gateway creates `Capture` record owned by `user_id` and enqueues processing job into Redis.
3. **Background Worker Processing:**
   - Worker dequeues job from Redis `lens:jobs:captures`.
   - Worker queries `Capture` from PostgreSQL; verifies record exists and possesses a valid `user_id`.
   - Worker fetches binary content (or scrapes URL), extracts text, computes chunks and vector embeddings.
   - Worker writes `ContentChunk` records linked to `Capture`.
4. **Search & Knowledge Retrieval:**
   - Client issues query `GET /search?q={query}&mode=hybrid`.
   - Gateway authenticates caller, derives embedding for query.
   - Gateway executes SQL combining full-text search (`tsvector`) and cosine similarity (`pgvector <=>`).
   - Query strictly filters `c.user_id = :user_id` to prevent cross-tenant data exposure.
5. **GitHub Integration:**
   - Client initiates OAuth flow: Gateway issues signed state parameter bound to `user_id`.
   - Callback validates state signature and extracts `user_id`.
   - OAuth access token is encrypted with AES-256-GCM and stored in `github_connections` linked to `user_id`.
   - Discovered repositories and ingested GitHub activities are strictly bound through `connection_id` to the owning user.

---

## 2. Threat Actors & Threat Profiles

| Threat Actor | Capabilities & Location | Motivation & Objective |
|---|---|---|
| **TA-1: Anonymous Internet Attacker** | External, unauthenticated network requests to API Gateway. | Bulk data scraping, credential abuse, unauthorized file uploads, probing for exposed endpoints, denial of service. |
| **TA-2: Malicious Authenticated Tenant (User B)** | Legitimate authenticated user account. Can craft arbitrary HTTP requests, tamper with UUIDs, manipulate query parameters, forge headers. | Vertical or horizontal privilege escalation. Accessing User A's captures, notes, documents, search index, or GitHub repositories (IDOR). |
| **TA-3: Man-in-the-Middle (Network Intermediary)** | Observes or modifies transit network traffic between clients and gateway. | Token interception, session hijacking, replay attacks. |
| **TA-4: Rogue Worker / Compromised Internal Process** | Access to internal Redis queue and database. | Processing forged jobs, injecting cross-tenant data into chunks or search embeddings. |

---

## 3. Forensic Vulnerability Assessment & Ranking

Prior to Stage 18.0, the LENS backend operated in an unauthenticated, single-tenant prototype mode. The following vulnerabilities were audited in the baseline:

### VULN-01: Complete Absence of Authentication & Authorization (CRITICAL)
- **CWE:** CWE-306 (Missing Authentication for Critical Function), CWE-862 (Missing Authorization)
- **CVSS 4.0 Score:** 9.8 (Critical)
- **Description:** No identity verification existed on any API endpoint. Any anonymous actor could read, write, upload, and delete captures and integrations.
- **Remediation:** Introduce `User` model, cryptographic password hashing (Argon2id), stateless JWT Bearer authentication, and FastAPI dependency `get_current_user`.

### VULN-02: Global Cross-Tenant Search Index Leakage (CRITICAL)
- **CWE:** CWE-200 (Exposure of Sensitive Information to an Unauthorized Actor), CWE-284 (Improper Access Control)
- **CVSS 4.0 Score:** 9.1 (Critical)
- **Description:** `/search` executed lexical and vector similarity queries globally across `content_chunks` and `github_activities` without filtering by user identity. An attacker could retrieve confidential text and source code belonging to any user simply by searching common keywords.
- **Remediation:** Join `content_chunks` with `captures` and filter by `captures.user_id = :user_id`. Join `github_activities` with `github_repositories` and `github_connections` and filter by `github_connections.user_id = :user_id`.

### VULN-03: Insecure Direct Object Reference (IDOR) on Captures (HIGH)
- **CWE:** CWE-639 (Authorization Bypass Through User-Controlled Key)
- **CVSS 4.0 Score:** 8.5 (High)
- **Description:** `GET /captures/{id}` fetched records by primary key alone. User B could inspect User A's capture, metadata, and extracted chunks by supplying User A's UUID.
- **Remediation:** Scope all lookup queries to `where(Capture.id == capture_id, Capture.user_id == current_user.id)`. Return HTTP 404 (Not Found) rather than 403 (Forbidden) to prevent object enumeration.

### VULN-04: Global Singleton GitHub Connection & CSRF Exposure (HIGH)
- **CWE:** CWE-284 (Improper Access Control), CWE-352 (Cross-Site Request Forgery)
- **CVSS 4.0 Score:** 8.2 (High)
- **Description:** `GET /integrations/github` returned `select(GitHubConnection).limit(1)`. All users shared the same OAuth connection. Furthermore, the OAuth callback accepted an unverified state parameter, allowing CSRF and account connection confusion.
- **Remediation:** Add `user_id` to `GitHubConnection` with a unique constraint on `(user_id, provider)`. Sign the OAuth `state` token using HMAC with a secret and timestamp, encoding the originating `user_id`.

### VULN-05: Insecure CORS Configuration (HIGH)
- **CWE:** CWE-942 (Permissive Cross-Domain Policy with Untrusted Domains)
- **CVSS 4.0 Score:** 7.5 (High)
- **Description:** `main.py` configured `CORSMiddleware` with `allow_origins=["*"]` combined with `allow_credentials=True`. This is invalid per modern browser security specs and exposes authenticated sessions to cross-origin abuse.
- **Remediation:** Restrict origins to explicit, trusted whitelist configured via environment (`CORS_ORIGINS`).

### VULN-06: Unverified Asynchronous Worker Ingestion (MEDIUM)
- **CWE:** CWE-285 (Improper Authorization)
- **CVSS 4.0 Score:** 6.5 (Medium)
- **Description:** Background jobs on Redis queue `lens:jobs:captures` contained only `capture_id`. Worker processed payloads without validating whether the capture had a valid tenant owner.
- **Remediation:** Worker validates that the target `Capture` exists and has an assigned non-null `user_id` before processing, chunking, or embedding.

---

## 4. Endpoint Security & Authorization Matrix

| Method | Endpoint | Auth Required | Tenant Scoping Rule | Failure Mode |
|---|---|---|---|---|
| `POST` | `/auth/register` | No | Public registration; creates user record | 400 if email exists, 422 if invalid |
| `POST` | `/auth/login` | No | Authenticates credentials; returns Bearer JWT | 401 if invalid credentials |
| `GET` | `/auth/me` | Yes (Bearer) | Returns authenticated user profile | 401 if missing/invalid/expired token |
| `POST` | `/captures` | Yes (Bearer) | Assigns `capture.user_id = current_user.id` | 401 if unauthenticated |
| `POST` | `/captures/upload` | Yes (Bearer) | Assigns `capture.user_id = current_user.id`, isolates S3 path | 401 if unauthenticated, 400 if bad file |
| `GET` | `/captures` | Yes (Bearer) | `WHERE user_id = current_user.id` | 401 if unauthenticated |
| `GET` | `/captures/{id}` | Yes (Bearer) | `WHERE id = :id AND user_id = current_user.id` | 404 if not found or not owned |
| `GET` | `/search` | Yes (Bearer) | Chunks filtered by `captures.user_id = current_user.id`; activities filtered by `github_connections.user_id = current_user.id` | 401 if unauthenticated |
| `GET` | `/integrations/github` | Yes (Bearer) | `WHERE user_id = current_user.id AND provider = 'github'` | 401 if unauthenticated |
| `GET` | `/integrations/github/connect`| Yes (Bearer) | State parameter cryptographically signed with `current_user.id` | 401 if unauthenticated |
| `GET` | `/integrations/github/callback`| No (Direct OAuth redirect) | Verifies signed HMAC state, extracts and binds `user_id` | 400 if invalid state, 401 if token exchange fails |
| `POST` | `/integrations/github/sync` | Yes (Bearer) | Operates strictly on connection belonging to `current_user.id` | 401 unauth, 404 if connection not found |
| `GET` | `/integrations/github/repositories` | Yes (Bearer) | Returns repositories belonging to user's connection | 401 unauth, 404 if connection not found |
| `PUT` | `/integrations/github/repositories/select` | Yes (Bearer) | Updates selection for repositories owned by user's connection | 401 unauth, 404 if connection not found |
| `POST` | `/integrations/github/activities/sync` | Yes (Bearer) | Syncs activities for repositories owned by user's connection | 401 unauth, 404 if connection not found |
| `GET` | `/integrations/github/activities` | Yes (Bearer) | Returns activities joined to user's connection | 401 unauth, 404 if connection not found |
| `DELETE` | `/integrations/github` | Yes (Bearer) | Deletes connection owned by `current_user.id` | 401 unauth, 404 if connection not found |
| `GET` | `/health` | No | Public system liveness probe | None |
| `GET` | `/` | No | Public API root info | None |

---

## 5. Resource Ownership & Database Cascade Hierarchy

```
[ users ] (PK: id, UUID)
    |
    +---< [ captures ] (FK: user_id -> users.id, ON DELETE CASCADE)
    |         |
    |         +---< [ content_chunks ] (FK: capture_id -> captures.id, ON DELETE CASCADE)
    |         |
    |         +---< [ source_metadata ] (FK: capture_id -> captures.id, ON DELETE CASCADE)
    |
    +---< [ github_connections ] (FK: user_id -> users.id, ON DELETE CASCADE)
              |
              +---< [ github_repositories ] (FK: connection_id -> github_connections.id, ON DELETE CASCADE)
                        |
                        +---< [ github_activities ] (FK: repository_id -> github_repositories.id, ON DELETE CASCADE)
```

### Cascade & Isolation Guarantees
1. Deleting a `User` cascades to delete all associated `captures`, `content_chunks`, `source_metadata`, `github_connections`, `github_repositories`, and `github_activities`.
2. Deleting a `Capture` cascades to delete all its `content_chunks` and `source_metadata`.
3. Every protected resource either directly stores `user_id` or references an immutable parent that enforces `user_id`.
4. No cross-tenant joins are permitted under any query path.

