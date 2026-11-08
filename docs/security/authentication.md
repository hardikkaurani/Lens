# LENS Client Authentication & Session Lifecycle Architecture

## 1. Overview & Threat Model

LENS implements a unified, defense-in-depth authentication architecture across both the Next.js web application (`apps/web`) and Flutter mobile application (`apps/mobile`), connecting to the FastAPI backend service (`services/api`).

### Security Principles & Threat Boundaries

1. **No Token Exposure in Browser JavaScript**:
   - Web browser `localStorage` and `sessionStorage` are vulnerable to Cross-Site Scripting (XSS).
   - In `apps/web`, JWT access tokens are never accessible to client-side JavaScript. Instead, the application uses a **Backend-for-Frontend (BFF)** proxy pattern with `HttpOnly`, `SameSite=Lax`, and `Secure` cookies.
2. **Hardware-Backed Keystore on Mobile**:
   - In `apps/mobile`, authentication tokens are persisted in hardware-backed secure storage (Android Keystore / iOS Keychain) via `FlutterSecureStorage`.
   - Tokens are never written to unencrypted preferences, logs, crash dumps, or memory dumps.
3. **Fail-Closed by Default**:
   - Absence of an active session immediately halts protected requests.
   - Missing context providers, absent cookies, or missing secure storage tokens fail closed with explicit errors rather than falling back to default or mock identities.

---

## 2. Web Authentication (Next.js BFF Architecture)

### 2.1 Route Handler BFF Architecture

```
Browser Client (React)
    │
    │  Fetch /api/proxy/captures
    │  Cookie: lens_access_token=... (HttpOnly, Secure)
    ▼
Next.js BFF API Routes
    │
    │  1. Validate CSRF origin / sec-fetch-site
    │  2. Sanitize path against directory traversal
    │  3. Strip client-supplied Authorization header
    │  4. Extract cookie and inject `Authorization: Bearer <token>`
    │  5. Forward to backend with `redirect: "manual"`
    ▼
FastAPI Backend (services/api)
```

### 2.2 Profile Validation Before Cookie Issuance (`/api/auth/login`)

When authenticating via `/api/auth/login`:
1. Validates incoming email and password syntax.
2. Forwards login request to the backend `POST /auth/login`.
3. Validates backend response structure:
   - `access_token` is present, non-empty, and conforms to JWT format (3 dot-separated segments).
   - `token_type` is case-insensitively verified as `"bearer"`.
   - `expires_in` is verified to be a positive integer bounded within safe limits.
4. **Mandatory Identity Verification (`/auth/me`)**:
   - Prior to setting any cookie, the route handler calls `GET /auth/me` with the new token.
   - If profile verification fails (e.g., inactive account, backend validation error, network glitch), the handler fails closed with `HTTP 502 Bad Gateway` and sets **no cookies**.
5. Only upon verified identity is the cookie written:
   ```
   Set-Cookie: lens_access_token=<jwt>; Path=/; HttpOnly; SameSite=Lax; Max-Age=<expires_in>; [Secure in production]
   ```

### 2.3 Reverse Proxy Security & Session Lifecycle (`/api/proxy/[...path]`)

The reverse proxy enforces:
- **Path Traversal Defense**: All segments are URL-decoded and checked against `..`, `%2e%2e`, `/`, `\`, and null bytes (`\0`). Rejection returns `HTTP 400 Bad Request`.
- **Prefix Allowlist**: Restricts proxied requests to allowlisted endpoints (`captures`, `search`, `auth/me`, `github`). Non-allowlisted paths return `HTTP 403 Forbidden`.
- **Credential Injection & Header Stripping**:
  - Any client-sent `Authorization` header is stripped to eliminate client token spoofing.
  - The server extracts `lens_access_token` from the HttpOnly cookie and attaches it as `Authorization: Bearer <token>`.
  - If the cookie is absent for protected routes, it immediately returns `HTTP 401 Unauthorized` without dispatching upstream network traffic.
- **Redirect Isolation**: Uses `redirect: "manual"` on upstream `fetch` to prevent the runtime from forwarding credentials to external third-party redirect locations.
- **Automatic Session Purging on 401**: When the upstream backend responds with `HTTP 401 Unauthorized`, the proxy automatically sets `Max-Age=0` on `lens_access_token`, instantly clearing the expired or invalidated session cookie from the browser.

### 2.4 Fail-Closed AuthContext Guarantees

In `apps/web/src/lib/auth-context.tsx`:
- `defaultAuthValue` with mock users has been completely eliminated.
- If `useAuth()` is called outside `<AuthProvider>`, it immediately throws:
  ```ts
  throw new Error("useAuth must be used within an AuthProvider");
  ```
- Unauthenticated states initialize with `user: null`, `isAuthenticated: false`, and `isLoading: true` until verified by `/api/auth/me`.

---

## 3. Mobile Authentication (Flutter Architecture)

### 3.1 Token Storage & Hardware Protection

- Implemented in `apps/mobile/lib/core/auth/auth_token_storage.dart`.
- `SecureAuthTokenStorage` delegates to `FlutterSecureStorage` with:
  - Android: `resetOnError: true` using Android Keystore.
  - iOS: `KeychainAccessibility.first_unlock` using iOS Keychain.
- An `InMemoryAuthTokenStorage` interface is provided for deterministic, hermetic unit and widget testing.

### 3.2 ApiClient Fail-Fast Guarantees

In `apps/mobile/lib/core/network/api_client.dart`:
- Protected endpoints (`listCaptures`, `getCapture`, `createCapture`, `search`) inspect token storage before making any HTTP connection.
- If no token exists in storage, `ApiClient` fails fast immediately:
  ```dart
  throw const ApiException(
    statusCode: 401,
    message: 'Authentication required. No access token available.',
  );
  ```
- Public endpoints (`/health`, `/auth/login`, `/auth/register`) do not require tokens and remain callable.

### 3.3 Offline Resilience & State Machine

`AuthService` models an explicit 5-state authentication lifecycle:

```
                  ┌──────────────┐
                  │   initial    │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  restoring   │
                  └──────┬───────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
 ┌───────────────┐ ┌───────────┐ ┌───────────────────┐
 │ unauthenticated│ │authenticated│ │ restorationFailed │
 └───────┬───────┘ └─────┬─────┘ └─────────┬─────────┘
         │               │                 │
         │ (login)       │ (401/logout)    │ (retry)
         └───────────────┴─────────────────┘
```

#### Network Failure Distinction:
- **Confirmed 401 Unauthorized**: Token is revoked or expired. `AuthService` purges the secure storage and transitions to `AuthStatus.unauthenticated`.
- **Network / Timeout / 5xx Server Error**: Storage is **NOT** cleared. The persisted token is preserved in hardware storage, and `AuthService` transitions to `AuthStatus.restorationFailed`.
- Users are presented with a clean offline screen offering:
  - **Retry Connection**: Executes `retryRestoreSession()` once connectivity returns.
  - **Sign In with Another Account**: Calls `clearSessionAndLogin()`, safely discarding the old token and presenting the `LoginScreen`.

### 3.4 Startup Auth Gate & Android Share Continuation

In `apps/mobile/lib/main.dart`:
- **Splash Screen**: During `initial` and `restoring` states, the app displays a branded loading screen (`LensLogo` + spinner) rather than flashing an unauthenticated `LoginScreen`.
- **Share Sheet Continuation**: Incoming Android Share Sheet intents arriving during `initial`, `restoring`, `restorationFailed`, or `unauthenticated` states are held in memory as `_pendingShare`. As soon as authentication transitions to `AuthStatus.authenticated`, the app automatically presents `ShareReviewScreen` with the preserved shared URL and metadata.

---

## 4. Logout Semantics & Invalidation

| Platform | Invalidation Mechanism | Storage Action | State Action |
| :--- | :--- | :--- | :--- |
| **Web** (`apps/web`) | `POST /api/auth/logout` or Proxy 401 Auto-Clear | Sets `lens_access_token` cookie `Max-Age=0` | Sets `user: null`, redirects to `/login` |
| **Mobile** (`apps/mobile`) | `AuthService.logout()` or ApiClient 401 trigger | Calls `storage.clearToken()` (Keystore/Keychain deletion) | Sets `currentUser: null`, `status: unauthenticated` |

### Stateless Token Lifespan & Future Revocation Roadmap

- **Current Implementation**: Access tokens are stateless HMAC-SHA256 JWTs with a 7-day expiration (`ACCESS_TOKEN_EXPIRE_MINUTES = 10080`).
- **Future Invalidation Requirement (Phase 2)**:
  - Implement a centralized Redis token revocation blocklist (`jti` claim tracking) to enable immediate server-side revocation on explicit user logout or password change prior to natural JWT expiration.

---

## 5. Stage 19.3.1 Hardening & Resilience Enhancements

### 5.1 Mobile Secure Storage & Keystore Reset Policy

- **`AndroidOptions(resetOnError: false)` Rationale**:
  Previously, `resetOnError: true` was enabled in `FlutterSecureStorage`. Under Android Keystore security semantics, transient hardware lockouts (such as device lock, biometric failure, or system reboot) triggered a total wipe of all persisted tokens. Setting `resetOnError: false` prevents silent credential loss.
- **`AuthStorageException` Propagation**:
  Hardware storage read, write, and deletion failures are encapsulated in a typed `AuthStorageException`.
  - On **read** failure during session restoration: credentials are preserved and the application transitions to `AuthStatus.restorationFailed`.
  - On **delete** failure during logout: the exception is propagated to the caller, preventing the UI from falsely indicating that the session was purged while tokens remain on disk.

### 5.2 Mobile Session Concurrency & Generation Tracking

- **Generation Counter (`_sessionId`)**:
  `AuthService` tracks an incrementing integer `_sessionId` updated on every login, session restoration, and logout.
- **Race Condition Prevention**:
  - Slow background startup restorations (`restoreSession`) capture the initial `requestSessionId`. If the user logs in before restoration finishes, the stale response is safely discarded.
  - Stale `401 Unauthorized` responses from earlier requests do not wipe newer active sessions.

### 5.3 Mobile Backend Authority Isolation & Transport Security

- **Authority-Scoped Storage**:
  Tokens are stored with backend authority keys (`lens_access_token_<sanitized_authority>`). Tokens issued by one backend (e.g., `https://api-a.lens.app`) cannot be read by or sent to another backend (e.g., `https://api-b.lens.app`).
- **Transport Security Assertion (`_assertSecureTransport`)**:
  All credentials endpoints (`/auth/login`, `/auth/register`) and requests injecting Bearer tokens reject cleartext `http://` transport across remote networks, allowing plain HTTP only for local loopback addresses (`127.0.0.1`, `localhost`, `10.0.2.2`).

### 5.4 Web CSRF Hardening, Host Header Enforcement & Proxy Redirects

- **Fail-Closed CSRF on Missing Host**:
  `verifyCsrfOrigin` strictly rejects mutating HTTP requests (`POST`, `PUT`, `PATCH`, `DELETE`) if the `Host` header is missing or empty.
- **Trusted Origin Validation**:
  In addition to same-host origin matching, `verifyCsrfOrigin` verifies origins against configured reverse-proxy environments (`TRUSTED_ORIGIN`, `NEXT_PUBLIC_APP_URL`, `ALLOWED_ORIGIN`).
- **Target URL Path Normalization & Prefix Allowlist**:
  The Next.js reverse proxy (`/api/proxy/[...path]`) validates that normalized target URLs resolve within the configured backend origin and match allowed path prefixes (`captures`, `search`, `integrations`, `health`).
- **Backend-Local Location Rewriting**:
  When the backend responds with a redirect (`3xx`) containing an internal `Location` header, the proxy rewrites the header to `/api/proxy/...` so browsers route through the proxy rather than attempting direct connections to internal backend ports.

---

## 6. CodeRabbit Review Audit & Resolution Matrix

The following table documents the verification, status, and resolution evidence for all 26 CodeRabbit review comments on PR #13:

| # | Comment ID | Subsystem & File | Reviewer Finding / Concern | Verification Status | Implemented Action / Resolution | Regression Test |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `4505000215` | Mobile: `auth_service.dart` | Token restoration catch cleared tokens on all errors, wiping credentials on network failures. | **Valid Defect** | Updated catch block to clear tokens strictly on `ApiException(401)`; network, timeout, and server errors preserve token with `AuthStatus.restorationFailed`. | `restoreSession preserves token and sets restorationFailed on network failure` |
| **2** | `4505000219` | Mobile: `auth_token_storage.dart` | Token deletion flow swallowed errors from `_storage.delete`, falsely indicating successful sign-out. | **Valid Defect** | Introduced `AuthStorageException` and propagated delete errors to caller in `logout()`. | `AuthStorageException on clear during logout propagates and preserves session` |
| **3** | `4505000221` | Mobile: `api_client.dart` | Tokens were not scoped by backend authority, risking cross-backend token leakage. | **Valid Defect** | Implemented authority-keyed storage in `AuthTokenStorage` and attached tokens only matching current authority. | `tokens are isolated by backend authority preventing cross-backend token reuse` |
| **4** | `4505000222` | Mobile: `api_client.dart` | Credentials and Bearer tokens could be transmitted over cleartext HTTP. | **Valid Defect** | Added `_assertSecureTransport` requiring HTTPS for sensitive requests (permitting loopback for tests). | `ApiClient rejects plain HTTP for remote sensitive endpoints and accepts HTTPS or loopback` |
| **5** | `4505000224` | Mobile: `api_client.dart` | 401 session expiration wiped active session even if a newer session was established. | **Valid Defect** | Added `_sessionId` generation tracking; stale 401 responses with older session IDs are discarded. | `stale 401 response from older session does not clear replacement session` |
| **6** | `4505000228` | Mobile: `main.dart` | When transitioning to unauthenticated, navigation stack was not reset to login screen. | **Valid Defect** | Updated `_handleAuthStateChanged` to call `_navigatorKey.currentState?.popUntil((r) => r.isFirst)`. | Verified in `main.dart` auth state transition handler. |
| **7** | `4505000231` | Mobile: `login_screen.dart` | Repeated taps on submit triggered multiple concurrent authentication requests. | **Valid Defect** | Added `if (_isLoading) return;` at entry of `_submit()` in `LoginScreen` and `RegisterScreen`. | `LoginScreen ignores repeated submit taps while request is in-flight` |
| **8** | `4505000234` | Mobile: `register_screen.dart` | Registration failure and post-registration auto-login failure were conflated. | **Valid Defect** | Differentiated account creation state (`accountCreated`); prompts user to log in if auto-login fails. | `RegisterScreen displays clear notice when auto-login fails after account creation` |
| **9** | `4505000240` | Web: `/api/auth/login` | Session cookie was issued without validating profile via `/auth/me`. | **Already Resolved** | Route handler validates backend response structure and calls `GET /auth/me` before writing cookie. | `fails closed (502) and sets no cookie when /auth/me fails after login` |
| **10** | `4505000242` | Web: `/api/proxy` | `transfer-encoding` was forwarded to backend. | **Already Resolved** | Added to `BLOCKED_FORWARD_HEADERS` in proxy route handler. | `strips client-provided Authorization header and uses cookie token` |
| **11** | `4505000249` | Web: `ProtectedRoute.tsx` | `usePathname` was called inside try/catch block violating Rules of Hooks. | **Valid Defect** | Moved `usePathname` and `useSearchParams` unconditionally into top-level component wrapped in `<Suspense>`. | Next.js static prerender build + Vitest route protection suite. |
| **12** | `4505000253` | Web: `ProtectedRoute.tsx` | Query parameters were dropped when constructing `redirectUrl`. | **Valid Defect** | Appended `searchParams` to `pathname` when building continuation redirect URL. | `login preserves safe same-origin path with search query` |
| **13** | `4505002530` | Web: `/api/proxy` | Target URL was not validated against whitelist before dispatch. | **Valid Defect** | Added URL construction and validated normalized path against `ALLOWED_PATH_PREFIXES`. | `rejects non-allowlisted prefix with 403` |
| **14** | `4505002537` | Web: `/api/proxy` | Upstream redirect `Location` header leaked internal backend URLs. | **Valid Defect** | Rewrote backend-local `Location` headers to `/api/proxy/...`. | `rewrites backend-local Location headers on redirects to /api/proxy` |
| **15** | `4505002540` | Web: Data-fetching pages | Data-fetching pages ran effects before authentication checks completed. | **Valid Defect** | Wrapped `CapturesPage`, `CaptureDetailPage`, and `SearchPage` with `<ProtectedRoute>`. | Search & Captures test suites rendering under `renderWithAuth`. |
| **16** | `4505002542` | Web: `login/page.tsx` | Login redirect destination was vulnerable to open redirect (`//evil.com`). | **Valid Defect** | Added `getSafeRedirect()` strictly validating destination is a same-origin path starting with `/`. | `login rejects open redirect attempts to external protocols or domains` |
| **17** | `4505002545` | Web: `register/page.tsx` | Auto-login failure after registration displayed account creation error. | **Valid Defect** | Tracked `accountCreated` state; displays success notification and direct sign-in button. | `register handles auto-login failure separately from account creation` |
| **18** | `4505002547` | Web: `api-client.ts` | Browser API client bypassed BFF proxy when `NEXT_PUBLIC_API_BASE_URL` was set. | **Valid Defect** | Updated `getApiBaseUrl()` so browser environments always route through `/api/proxy`. | Web API client tests verifying `/api/proxy` routing. |
| **19** | `4505002551` | Web: `api-client.ts` | Protected 401 API responses did not trigger session refresh in `AuthProvider`. | **Valid Defect** | Wired `unauthorizedHandler` in `api-client` to trigger `refreshUser()` in `AuthProvider`. | AuthContext 401 callback listener tests. |
| **20** | `4505002553` | Web: `auth-context.tsx` | In-flight `refreshUser` could overwrite a newer successful `login` response. | **Valid Defect** | Added `activeSeqRef` sequence counter; stale `refreshUser` responses are ignored. | `race condition: slow refreshUser does not overwrite newer login` |
| **21** | `4505002555` | Web: `auth-context.tsx` | Transient 503 errors were treated as missing sessions and logged out users. | **Valid Defect** | Distinguished 401 from transient errors; exposed `verificationError` and `retryVerification()`. | `503 / network error sets verificationError and preserves session without redirecting` |
| **22** | `4505002557` | Web: `auth-context.tsx` | `logout` cleared state and redirected even when backend logout failed. | **Valid Defect** | Moved state clear and navigation to execute strictly after successful `apiClient.logout()`. | `logout failure preserves user session and does not redirect to login` |
| **23** | `4505002558` | Web: Test types | Test mocks missed required fields (`success: true`). | **Valid Defect** | Updated mocks across `auth.test.tsx` to conform to `AuthSessionResponse`. | `npx tsc --noEmit` + `npm run build` static type check. |
| **24** | `4505002559` | Web: `auth-context.tsx` | `useAuth()` returned fake user outside `AuthProvider`. | **Already Resolved** | `defaultAuthValue` removed; `useAuth()` throws error outside `AuthProvider`. | `throws explicit error when useAuth is called outside AuthProvider` |
| **25** | `4505002560` | Web: `server-auth.ts` | CSRF origin validation failed behind reverse proxies with trusted hosts. | **Valid Defect** | Added `getTrustedHosts()` supporting `TRUSTED_ORIGIN`, `NEXT_PUBLIC_APP_URL`, and `ALLOWED_ORIGIN`. | `accepts mutating request when origin matches configured TRUSTED_ORIGIN` |
| **26** | `4505002562` | Web: `server-auth.ts` | Missing `Host` header on mutating requests evaluated `!host` to true, bypassing CSRF check. | **Valid Defect** | Enforced that mutating requests without `Host` fail closed and return `false`. | `rejects mutating request when Host header is missing` |

---

### 5.4 Stage 19.3.1 Follow-up Hardening Details

1. **Mobile Authority Isolation & Collision Resistance**:
   - `SecureAuthTokenStorage` and `InMemoryAuthTokenStorage` strictly isolate tokens by backend authority.
   - When `backendAuthority` is explicitly supplied, `getToken()` looks up only that authority's key and returns `null` if missing; it never falls back to the global/default token.
   - `clearToken({backendAuthority})` deletes only the specified authority's key and preserves the global token and other authorities.
   - `formatKey` uses lowercase normalization and Base64URL encoding (`utf8.encode`) to provide mathematical collision resistance against ambiguous delimiters (`:`, `_`, `/`).
2. **Mobile Session Restoration Lifecycle**:
   - In `AuthService.restoreSession`, `_isRestoring` is guaranteed to be set to `false` in the `finally` block even when a concurrent login or logout increments `_sessionId`.
   - `_isLoading` is unconditionally finalized, preventing stuck loading states or blocked future restoration invocations.
3. **Web Cookie Mutation Integrity**:
   - `setAuthCookie()` and `clearAuthCookie()` in `server-auth.ts` do not swallow cookie mutation failures.
   - Route handlers `/api/auth/login` and `/api/auth/logout` catch cookie mutation errors and return HTTP 500 fail-closed error responses rather than returning false `{ success: true }`.
4. **Web Auth `getMe()` Timeout & Abort Propagation**:
   - `apiClient.getMe()` implements a 15-second default timeout via an internal `AbortController`.
   - Propagates caller `AbortSignal` cancellation accurately without converting user cancellations into timeout errors (`isTimeout: false`).

### 5.5 Web Session Invalidation Correctness & Mobile FIFO Hardening

1. **Elimination of Proxy Cookie Mutation on 401 (RFC 6265 Browser Race Mitigation)**:
   - Data proxy routes (`/api/proxy/[...path]`) forward upstream 401 Unauthorized responses directly to the client **without mutating or clearing cookies**. Data proxy never emits `Set-Cookie: Max-Age=0`.
   - In HTTP, browsers process `Set-Cookie: Max-Age=0` unconditionally without inspecting token content. Because background or out-of-order data requests (e.g. `/api/proxy/captures`) can be delayed, proxy cookie deletion introduced an unavoidable race where a stale request could wipe the cookie jar of a newer replacement login.
   - Session validation is driven by client lifecycle handlers intercepting 401s and querying `/api/auth/me`, which verifies the current cookie snapshot.
2. **Concurrent Logout & Replacement Login Protection**:
   - `POST /api/auth/logout` retrieves the request's token snapshot and supplies it to `clearAuthCookie(token)`.
   - In `clearAuthCookie(expectedToken)`, token currency (`isLatestToken`) is validated both before and after `await cookies()`. If a replacement login completed concurrently (e.g., in another browser tab), `clearAuthCookie` aborts deletion and returns `false`, preventing in-flight logouts from destroying new session cookies.
3. **Architectural Boundaries of Process-Local `SessionTokenRegistry`**:
   - `SessionTokenRegistry` provides in-memory advisory coordination to mitigate local event-loop concurrency races on a single Node.js runtime.
   - It is explicitly **not** a distributed session store or distributed lock across multi-instance or serverless deployments.
   - The upstream FastAPI backend (`services/api`) remains the authoritative cryptographic source of truth: HMAC-SHA256 signatures, 7-day expiration timestamps, token types, and tenant isolation are verified on every backend request.
   - Distributed instant token revocation across horizontal BFF workers is architected for Phase 2 (via a centralized Redis blacklist / session store).
4. **Fail-Closed Multi-Instance & Cold Start Resilience**:
   - In uncoordinated multi-instance or serverless environments (or following a process restart), `isTokenCurrent()` fails closed (`false`) when a token has no registry entry on that worker, preventing uncoordinated instances from wiping active cookies.
5. **Untrusted Claim Demarcation**:
   - `parseJwtClaims()` performs structural decoding only; claims including `sub` are untrusted hints used solely for local routing and isolation.
6. **Mobile FIFO Keystore Serialization & Delayed Restoration Cleanup Resilience**:
   - `AuthService._runStorageMutation` reserves queue tail gates synchronously before yielding to `await previous`, guaranteeing strict FIFO execution and preventing concurrent waiters from racing.
   - Delayed 401 token cleanup failure during `restoreSession` records `storageCleanupError` and transitions to `restorationFailed` with UI retry; if a replacement login arrives while cleanup is pending, the replacement session is preserved without corruption.
