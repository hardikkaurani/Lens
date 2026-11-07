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

/**
 * Verify same-origin for state-changing HTTP mutations to defeat CSRF attacks.
 */
export function verifyCsrfOrigin(request: Request): boolean {
  const method = request.method.toUpperCase();
  // Safe HTTP methods do not mutate state
  if (["GET", "HEAD", "OPTIONS"].includes(method)) {
    return true;
  }

  const origin = request.headers.get("origin");
  const host = request.headers.get("host");

  if (!origin) {
    // Fall back to Referer check if Origin is absent
    const referer = request.headers.get("referer");
    if (!referer) {
      // In non-browser automated test environments without headers, permit if specified
      if (process.env.NODE_ENV === "test") return true;
      return false;
    }
    try {
      const refererUrl = new URL(referer);
      return !host || refererUrl.host === host;
    } catch {
      return false;
    }
  }

  try {
    const originUrl = new URL(origin);
    // Origin host must match the requested Host header
    return !host || originUrl.host === host;
  } catch {
    return false;
  }
}

/**
 * Extract the stored JWT access token from HttpOnly cookies.
 */
export async function getStoredToken(): Promise<string | null> {
  const cookieStore = await cookies();
  const cookie = cookieStore.get(LENS_TOKEN_COOKIE);
  return cookie?.value ?? null;
}

/**
 * Set the JWT access token in an HttpOnly, Secure, SameSite=Lax cookie.
 */
export async function setAuthCookie(token: string, expiresInSeconds: number): Promise<void> {
  const cookieStore = await cookies();
  const isProduction = process.env.NODE_ENV === "production";

  cookieStore.set(LENS_TOKEN_COOKIE, token, {
    httpOnly: true,
    secure: isProduction,
    sameSite: "lax",
    path: "/",
    maxAge: expiresInSeconds,
  });
}

/**
 * Clear the authentication cookie upon logout or token expiry.
 */
export async function clearAuthCookie(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(LENS_TOKEN_COOKIE);
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
