/**
 * Server-side authentication and BFF security utilities for Next.js App Router.
 * Handles HttpOnly cookie management, CSRF origin verification, and backend URL resolution.
 */

import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

export const LENS_TOKEN_COOKIE = "lens_access_token";

/**
 * Resolve the internal/backend API base URL.
 * Server-to-backend communication can use INTERNAL_API_URL in containerized setups,
 * falling back to NEXT_PUBLIC_API_BASE_URL or local development port 8000.
 */
export function getBackendApiUrl(): string {
  const envUrl = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (envUrl && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  return "http://localhost:8000";
}

function getTrustedHosts(): Set<string> {
  const trusted = new Set<string>();
  const envOrigins = [
    process.env.TRUSTED_ORIGIN,
    process.env.NEXT_PUBLIC_APP_URL,
    process.env.ALLOWED_ORIGIN,
  ];
  for (const envVal of envOrigins) {
    if (envVal && envVal.trim()) {
      try {
        const u = new URL(envVal.trim());
        trusted.add(u.host.toLowerCase());
      } catch {
        trusted.add(envVal.trim().toLowerCase());
      }
    }
  }
  return trusted;
}

/**
 * Verify same-origin for state-changing HTTP mutations to defeat CSRF attacks.
 * Rejects mutating requests that omit Host or specify cross-origin sources.
 */
export function verifyCsrfOrigin(request: Request): boolean {
  const method = request.method.toUpperCase();
  // Safe HTTP methods do not mutate state
  if (["GET", "HEAD", "OPTIONS"].includes(method)) {
    return true;
  }

  const host = request.headers.get("host");
  if (!host || !host.trim()) {
    // Mutating requests without a Host header must fail closed
    return false;
  }

  const normalizedHost = host.trim().toLowerCase();
  const trustedHosts = getTrustedHosts();

  const isHostAllowed = (h: string) => {
    const cleanH = h.toLowerCase();
    return cleanH === normalizedHost || trustedHosts.has(cleanH);
  };

  const origin = request.headers.get("origin");
  if (origin && origin.trim()) {
    try {
      const originUrl = new URL(origin.trim());
      return isHostAllowed(originUrl.host);
    } catch {
      return false;
    }
  }

  // Fall back to Referer check if Origin is absent
  const referer = request.headers.get("referer");
  if (referer && referer.trim()) {
    try {
      const refererUrl = new URL(referer.trim());
      return isHostAllowed(refererUrl.host);
    } catch {
      return false;
    }
  }

  return false;
}

/**
 * Extract the stored JWT access token from HttpOnly cookies.
 */
export async function getStoredToken(): Promise<string | null> {
  try {
    const cookieStore = await cookies();
    const cookie = cookieStore.get(LENS_TOKEN_COOKIE);
    return cookie?.value ?? null;
  } catch {
    return null;
  }
}

/**
 * Decoded payload claims from a stateless JWT access token.
 */
export interface JwtSessionClaims {
  sub: string;
  email?: string;
  iat?: number;
  exp?: number;
  [key: string]: unknown;
}

/**
 * Extract claims from a JWT access token without cryptographic signature verification
 * (backend FastAPI handles cryptographic HMAC verification using its secret key).
 * Used strictly for client-side session identity routing and local race prevention.
 * Returns null if token is malformed, not 3 segments, non-JSON, or missing a non-empty sub.
 */
export function parseJwtClaims(token: string): JwtSessionClaims | null {
  try {
    if (!token || typeof token !== "string") return null;
    const parts = token.trim().split(".");
    if (parts.length !== 3) return null;
    const payloadBase64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padLength = (4 - (payloadBase64.length % 4)) % 4;
    const padded = payloadBase64 + "=".repeat(padLength);
    const json = Buffer.from(padded, "base64").toString("utf-8");
    const parsed = JSON.parse(json);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.sub === "string" &&
      parsed.sub.trim().length > 0
    ) {
      return parsed as JwtSessionClaims;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Per-user session tracking registry to prevent stale, delayed 401 responses
 * from clearing newer replacement sessions issued to the same user on this runtime instance.
 *
 * ARCHITECTURAL BOUNDARY & LIMITATIONS:
 * 1. This registry is an in-memory best-effort advisory coordination mechanism to mitigate local
 *    concurrency races on a single Node.js runtime. It does NOT claim to provide distributed locking,
 *    multi-instance synchronization, or persistence across worker restarts.
 * 2. True cryptographic security and token lifecycle enforcement are strictly the responsibility
 *    of the upstream FastAPI backend (services/api), which cryptographically verifies HMAC-SHA256
 *    signatures, expiration timestamps, token types, and subjects on every request.
 * 3. Session identity is tracked via the JWT 'sub' (User ID) claim hint. Different users operate
 *    in strict isolation: User A's login or expiry never interferes with User B's active session.
 * 4. Fail-closed semantics: If an instance or worker has no record of a token's issuance
 *    (e.g. after a process restart or on an uncoordinated serverless instance),
 *    isTokenCurrent() fails closed (returns false), preventing unverified tokens from
 *    unilaterally clearing cookies on other workers.
 */
export class SessionTokenRegistry {
  private activeUserTokens = new Map<string, string>();
  private fallbackLatestToken: string | null = null;

  recordIssued(token: string): void {
    const trimmed = token.trim();
    const claims = parseJwtClaims(trimmed);
    if (claims?.sub) {
      this.activeUserTokens.set(claims.sub, trimmed);
    } else {
      this.fallbackLatestToken = trimmed;
    }
  }

  recordCleared(token?: string | null): void {
    if (token) {
      const trimmed = token.trim();
      const claims = parseJwtClaims(trimmed);
      if (claims?.sub) {
        // Compare-and-clear (CAS): Only delete if the active token for this user
        // matches the token being cleared. If a replacement token was registered,
        // we MUST NOT delete the newer token's registration!
        if (this.activeUserTokens.get(claims.sub) === trimmed) {
          this.activeUserTokens.delete(claims.sub);
        }
        return;
      }
      if (this.fallbackLatestToken === trimmed) {
        this.fallbackLatestToken = null;
      }
      return;
    }
    // When called without a token (explicit global logout), clear fallback
    this.fallbackLatestToken = null;
  }

  isTokenCurrent(token: string | null): boolean {
    if (!token || token.trim().length === 0) return false;
    const trimmed = token.trim();
    const claims = parseJwtClaims(trimmed);
    if (claims?.sub) {
      const latestForUser = this.activeUserTokens.get(claims.sub);
      // FAIL-CLOSED: If not affirmatively registered as the active token for this user,
      // return false. This prevents uncoordinated instances, cold starts, and stale requests
      // from falsely assuming an unknown token is current and wiping newer browser sessions.
      return latestForUser === trimmed;
    }
    return this.fallbackLatestToken === trimmed;
  }

  reset(): void {
    this.activeUserTokens.clear();
    this.fallbackLatestToken = null;
  }
}

let activeRegistry = new SessionTokenRegistry();

export function getSessionTokenRegistry(): SessionTokenRegistry {
  return activeRegistry;
}

export function setSessionTokenRegistry(registry: SessionTokenRegistry): void {
  activeRegistry = registry;
}

/**
 * Record that a new token was established (e.g. on login or session setup).
 * Coordinates across requests and instances to prevent delayed 401s from wiping newer sessions.
 */
export function recordTokenIssued(token: string): void {
  activeRegistry.recordIssued(token);
}

/**
 * Record that the token was explicitly cleared (e.g. on logout).
 */
export function recordTokenCleared(token?: string | null): void {
  activeRegistry.recordCleared(token);
}

/**
 * Reset token tracking (used in tests and state resets).
 */
export function resetLatestToken(): void {
  activeRegistry.reset();
}

/**
 * Check if the given token is still the latest issued token for its session identity.
 */
export function isLatestToken(token: string | null): boolean {
  return activeRegistry.isTokenCurrent(token);
}

/**
 * Set the JWT access token in an HttpOnly, Secure, SameSite=Lax cookie.
 * Throws when cookie store mutation fails so routes never report false success.
 */
export async function setAuthCookie(token: string, expiresInSeconds: number): Promise<void> {
  const isProduction = process.env.NODE_ENV === "production";
  const cookieStore = await cookies();
  cookieStore.set(LENS_TOKEN_COOKIE, token, {
    httpOnly: true,
    secure: isProduction,
    sameSite: "lax",
    path: "/",
    maxAge: expiresInSeconds,
  });
  recordTokenIssued(token);
}

/**
 * Clear the authentication cookie upon logout or token expiry.
 * If expectedToken is provided, conditionally clears ONLY if the token is still the active token
 * for its identity, preventing stale 401s from invalidating newer replacement logins.
 * Re-checks before and after awaiting cookieStore to prevent async boundary races.
 * Throws when cookie store deletion fails so routes never report false success.
 *
 * @returns true if the cookie was cleared; false if skipped because expectedToken was superseded or unverified.
 */
export async function clearAuthCookie(expectedToken?: string | null): Promise<boolean> {
  if (expectedToken !== undefined && expectedToken !== null) {
    if (!isLatestToken(expectedToken)) {
      return false;
    }
  }

  const cookieStore = await cookies();

  // Re-check after awaiting cookieStore in case a concurrent login completed on the event loop
  if (expectedToken !== undefined && expectedToken !== null) {
    if (!isLatestToken(expectedToken)) {
      return false;
    }
  }

  cookieStore.delete(LENS_TOKEN_COOKIE);
  recordTokenCleared(expectedToken);
  return true;
}

/**
 * Forward an error response from FastAPI to the browser with standard JSON structure.
 */
export function createProxyErrorResponse(status: number, message: string): NextResponse {
  return NextResponse.json(
    { detail: message },
    { status }
  );
}
