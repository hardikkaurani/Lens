# LENS Multi-Tenancy & Authorization Architecture

**Document Version:** 1.0.0  
**Stage:** 18.0 — Security Forensic Audit & Multi-Tenancy  
**Target Baseline:** `a6fe649e4c26b464dea98331416195262be6ca9a`  
**Classification:** Engineering Specification  

---

## 1. Architectural Strategy & Tenant Isolation Model

LENS adopts a **SaaS Row-Level Tenant Isolation** architecture within a unified PostgreSQL database and MinIO object store. 

### Why Row-Level Isolation?
- LENS requires efficient vector indexing across user collections using `pgvector` (`hnsw` / `ivfflat`), high-throughput async processing via worker workers, and lean operational overhead.
- Schema-per-tenant or database-per-tenant approaches add prohibitive connection pool, migration, and memory overhead for developer personal knowledge bases.
- Instead, every tenant-scoped entity strictly contains a non-nullable foreign key `user_id` pointing to `users(id)` with `ON DELETE CASCADE`.
- All database queries, whether via SQLAlchemy ORM or raw SQL execution for vector search, enforce an explicit `user_id` predicate at the data access layer.

---

## 2. Identity, Authentication & JWT Specification

### 2.1 User Entity Schema
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_users_email ON users(email);
```

### 2.2 Password Hashing Standard
- Algorithm: **Argon2id** (via `argon2-cffi`).
  - Memory cost: 65,536 KiB (64 MiB)
  - Time cost: 3 iterations
  - Parallelism: 4 threads
- Fallback: Cryptographically salted **PBKDF2-HMAC-SHA256** or **scrypt** with minimum 600,000 iterations / OWASP recommended parameters if running in environments without compiled Argon2 C-extensions.

### 2.3 JWT Token Structure & Claims
Tokens are stateless, signed using `HS256` (HMAC with SHA-256) with a high-entropy secret (`JWT_SECRET` >= 256 bits):

```json
{
  "sub": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "developer@example.com",
  "iat": 1730995200,
  "exp": 1731600000,
  "type": "access"
}
```

- **`sub`**: Subject identifier, representing the user's UUID.
- **`email`**: User email for non-sensitive presentation.
- **`iat`**: Issued-at Unix timestamp.
- **`exp`**: Expiration Unix timestamp (default: 7 days / configurable via `JWT_EXPIRE_MINUTES`).
- **`type`**: Token type discriminator (`access`). Prevents token reuse across different scopes (e.g., refresh vs access vs email verification).

---

## 3. API Authorization & FastAPI Dependency

All tenant-protected endpoints rely on the dependency `get_current_user`:

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db_session)
) -> User:
    ...
```

1. **Header Extraction:** Extracts Bearer token from `Authorization: Bearer <token>`.
2. **Signature & Expiration Verification:** Validates signature using `JWT_SECRET` and checks `exp > now()`. Rejects expired or malformed tokens with HTTP 401 Unauthorized (`WWW-Authenticate: Bearer error="invalid_token"`).
3. **Claim Extraction:** Extracts `sub` (UUID). Rejects tokens with invalid subject format.
4. **Active User Lookup:** Fetches `User` record from PostgreSQL where `id = sub` and `is_active = True`. If user was deleted or deactivated after token issuance, raises HTTP 401.

---

## 4. Search Isolation Architecture

Knowledge retrieval in LENS combines full-text lexical search and semantic vector embeddings over chunks and GitHub activities. Cross-tenant leakage in vector similarity is prevented through mandatory user-scoped joins:

### Capture Chunks Query (Lexical + Vector)
```sql
SELECT
    cc.id,
    cc.capture_id,
    cc.content,
    cc.chunk_index,
    1 - (cc.embedding <=> :query_vector) AS similarity,
    ts_rank(cc.search_vector, websearch_to_tsquery('english', :query_text)) AS rank
FROM content_chunks cc
JOIN captures c ON cc.capture_id = c.id
WHERE c.user_id = :user_id
  AND c.processing_status = 'completed'
ORDER BY similarity DESC
LIMIT :limit;
```

### GitHub Activity Query
```sql
SELECT
    ga.id,
    ga.repository_id,
    ga.activity_type,
    ga.title,
    ga.body,
    ga.html_url
FROM github_activities ga
JOIN github_repositories gr ON ga.repository_id = gr.id
JOIN github_connections gc ON gr.connection_id = gc.id
WHERE gc.user_id = :user_id
  AND (
      ga.title ILIKE :term
      OR ga.body ILIKE :term
  )
ORDER BY ga.activity_created_at DESC
LIMIT :limit;
```

Under no circumstances can an unauthenticated or cross-tenant query bypass the `c.user_id = :user_id` or `gc.user_id = :user_id` filter.

---

## 5. Storage (MinIO) Multi-Tenancy

Raw file uploads and documents are partitioned by tenant within the S3 bucket:

```
s3://lens-captures/
    ├── {user_id}/
    │   └── {capture_id}/
    │       ├── raw_document.pdf
    │       └── thumbnail.png
```

- When storing files, the API prefixes the object path with the authenticated `current_user.id`.
- When reading or downloading files, the API verifies that the associated `Capture` record is owned by `current_user.id`.

---

## 6. GitHub Integration Multi-Tenancy & CSRF Defense

1. **User Scoping:** `GitHubConnection` possesses a foreign key `user_id` referencing `users(id)`. A unique constraint enforces at most one GitHub connection per provider per user:
   ```sql
   CONSTRAINT uq_github_connections_user_provider UNIQUE (user_id, provider)
   ```
2. **Cryptographic State Parameter:** To initiate OAuth, the backend signs a state token:
   ```
   state = HMAC_SHA256(secret, f"{user_id}:{nonce}:{timestamp}") + "." + base64(payload)
   ```
   Upon callback:
   - State is verified with constant-time HMAC comparison.
   - Timestamp is verified within a 10-minute validity window.
   - The connection is strictly bound to the `user_id` encoded in the verified state, defeating CSRF and cross-account binding attacks.
3. **Encrypted Tokens:** GitHub access tokens remain encrypted at rest via AES-256-GCM using `ENCRYPTION_KEY`.

---

## 7. Operator Migration & Legacy Data Handling

### Strict Policy: No Silent Default User Creation
In accordance with production security standards, unowned legacy records created during prototype/testing phases **must not** be silently attributed to an arbitrary or auto-generated "default" user. 

### Migration Mechanics
1. **Schema Evolution:**
   - The Alembic migration creates the `users` table.
   - Adds `user_id` column to `captures` and `github_connections` as nullable during phase 1 of migration.
   - In environments with legacy development rows:
     - An operator CLI script (`scripts/assign_legacy_tenant.py`) is provided.
     - The script requires the operator to explicitly pass `--target-user-email <email>` or `--purge-unowned` to resolve unowned records.
     - Once resolved, or in fresh/empty databases, `user_id` is made `NOT NULL` with a foreign key constraint to `users(id)`.
2. **Safe Fail-Open vs Fail-Close:**
   - The API code treats any row without a matching valid `user_id` as non-existent (fails closed).
   - Unowned legacy rows are completely invisible to all authenticated users.

