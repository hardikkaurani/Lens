import { NextRequest, NextResponse } from "next/server";
import { getBackendApiUrl, setAuthCookie, verifyCsrfOrigin } from "@/lib/server-auth";
import type { User } from "@/types/api";

const MAX_EXPIRY_SECONDS = 30 * 24 * 60 * 60; // 30 days upper sanity bound

interface BackendTokenResponse {
  access_token?: unknown;
  token_type?: unknown;
  expires_in?: unknown;
}

function isValidUserProfile(data: unknown): data is User {
  if (!data || typeof data !== "object") return false;
  const user = data as Record<string, unknown>;
  return (
    typeof user.id === "string" &&
    user.id.trim().length > 0 &&
    typeof user.email === "string" &&
    user.email.trim().length > 0
  );
}

export async function POST(request: NextRequest) {
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON payload." }, { status: 400 });
  }

  const backendUrl = getBackendApiUrl();
  try {
    // 1. Authenticate credentials against backend
    const loginRes = await fetch(`${backendUrl}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!loginRes.ok) {
      const errData = await loginRes.json().catch(() => ({ detail: "Authentication failed." }));
      return NextResponse.json(
        { detail: errData.detail || "Invalid email or password." },
        { status: loginRes.status }
      );
    }

    const tokenData = (await loginRes.json().catch(() => null)) as BackendTokenResponse | null;
    if (!tokenData || typeof tokenData !== "object") {
      return NextResponse.json(
        { detail: "Invalid token response format from authentication service." },
        { status: 502 }
      );
    }

    // Validate access_token is a non-empty string
    if (typeof tokenData.access_token !== "string" || tokenData.access_token.trim().length === 0) {
      return NextResponse.json(
        { detail: "Missing or malformed access token received from authentication service." },
        { status: 502 }
      );
    }

    // Validate token_type is supported (bearer)
    if (
      typeof tokenData.token_type !== "string" ||
      tokenData.token_type.trim().toLowerCase() !== "bearer"
    ) {
      return NextResponse.json(
        { detail: "Unsupported token type received from authentication service." },
        { status: 502 }
      );
    }

    // Validate expiry is a positive finite number bounded by backend contract
    if (
      typeof tokenData.expires_in !== "number" ||
      !Number.isFinite(tokenData.expires_in) ||
      tokenData.expires_in <= 0 ||
      tokenData.expires_in > MAX_EXPIRY_SECONDS
    ) {
      return NextResponse.json(
        { detail: "Invalid token expiry received from authentication service." },
        { status: 502 }
      );
    }

    const accessToken = tokenData.access_token.trim();
    const expiresIn = Math.floor(tokenData.expires_in);

    // 2. Fetch authenticated user profile using token before setting any cookie
    const meRes = await fetch(`${backendUrl}/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json",
      },
    });

    if (!meRes.ok) {
      return NextResponse.json(
        { detail: "Failed to retrieve user profile after authentication." },
        { status: 502 }
      );
    }

    const userData: unknown = await meRes.json().catch(() => null);
    if (!isValidUserProfile(userData)) {
      return NextResponse.json(
        { detail: "Invalid user profile data received from authentication service." },
        { status: 502 }
      );
    }

    // 3. Persist JWT in HttpOnly cookie ONLY AFTER all checks and profile verification succeed
    await setAuthCookie(accessToken, expiresIn);

    return NextResponse.json(
      {
        success: true,
        user: userData,
      },
      { status: 200 }
    );
  } catch {
    return NextResponse.json(
      { detail: "Unable to connect to LENS authentication service." },
      { status: 503 }
    );
  }
}
