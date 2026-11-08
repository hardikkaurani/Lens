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
