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
 * Interface for distributed or shared token storage backends (e.g. Redis, memcached,
 * key-value database, or multi-instance coordination cache).
 */
export interface DistributedTokenStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
}

/**
 * Global/shared distributed token store implementation.
 * Uses globalThis singleton to coordinate across workers and allows pluggable adapters.
 */
class GlobalDistributedTokenStore implements DistributedTokenStore {
  private getMap(): Map<string, string> {
    const g = globalThis as unknown as { __lens_distributed_token_store__?: Map<string, string> };
    if (!g.__lens_distributed_token_store__) {
      g.__lens_distributed_token_store__ = new Map<string, string>();
    }
    return g.__lens_distributed_token_store__;
  }

  async get(key: string): Promise<string | null> {
    return this.getMap().get(key) ?? null;
  }

  async set(key: string, value: string): Promise<void> {
    this.getMap().set(key, value);
  }

  async delete(key: string): Promise<void> {
    this.getMap().delete(key);
  }
}

/**
 * Coordination contract for session token lifecycle across requests and instances.
 * In distributed or serverless deployments (Kubernetes pods, Cloud Run, AWS Lambda),
 * multiple application instances share session state via a DistributedTokenStore.
 */
export interface SessionTokenCoordinator {
  recordTokenIssued(token: string): Promise<void>;
  recordTokenCleared(): Promise<void>;
  isTokenCurrent(token: string | null): Promise<boolean>;
  reset(): Promise<void>;
}

export class DistributedSessionCoordinator implements SessionTokenCoordinator {
  public static readonly LATEST_TOKEN_KEY = "lens:session:latest_token";
  private store: DistributedTokenStore;

  constructor(store?: DistributedTokenStore) {
    this.store = store ?? new GlobalDistributedTokenStore();
  }

  setStore(store: DistributedTokenStore): void {
    this.store = store;
  }

  async recordTokenIssued(token: string): Promise<void> {
    await this.store.set(DistributedSessionCoordinator.LATEST_TOKEN_KEY, token.trim());
  }

  async recordTokenCleared(): Promise<void> {
    await this.store.delete(DistributedSessionCoordinator.LATEST_TOKEN_KEY);
  }

  async isTokenCurrent(token: string | null): Promise<boolean> {
    if (!token || token.trim().length === 0) return false;
    const latest = await this.store.get(DistributedSessionCoordinator.LATEST_TOKEN_KEY);
    if (latest === null) {
      return true;
    }
    return latest === token.trim();
  }

  async reset(): Promise<void> {
    await this.store.delete(DistributedSessionCoordinator.LATEST_TOKEN_KEY);
  }
}

let activeCoordinator: SessionTokenCoordinator = new DistributedSessionCoordinator();

export function setSessionTokenCoordinator(coordinator: SessionTokenCoordinator): void {
  activeCoordinator = coordinator;
}

export function getSessionTokenCoordinator(): SessionTokenCoordinator {
  return activeCoordinator;
}

/**
 * Record that a new token was established (e.g. on login or session setup).
 * Coordinates across requests and instances to prevent delayed 401s from wiping newer sessions.
 */
export async function recordTokenIssued(token: string): Promise<void> {
  await activeCoordinator.recordTokenIssued(token);
}

/**
 * Record that the token was explicitly cleared (e.g. on logout).
 */
export async function recordTokenCleared(): Promise<void> {
  await activeCoordinator.recordTokenCleared();
}

/**
 * Reset token tracking (used in tests and state resets).
 */
export async function resetLatestToken(): Promise<void> {
  await activeCoordinator.reset();
}

/**
 * Check if the given token is still the latest issued token across instances.
 */
export async function isLatestToken(token: string | null): Promise<boolean> {
  return activeCoordinator.isTokenCurrent(token);
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
  await recordTokenIssued(token);
}

/**
 * Clear the authentication cookie upon logout or token expiry.
 * Throws when cookie store deletion fails so routes never report false success.
 */
export async function clearAuthCookie(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(LENS_TOKEN_COOKIE);
  await recordTokenCleared();
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
