import { NextRequest, NextResponse } from "next/server";
import { getBackendApiUrl, setAuthCookie, verifyCsrfOrigin } from "@/lib/server-auth";

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
      return NextResponse.json(errData, { status: loginRes.status });
    }

    const tokenData = (await loginRes.json()) as {
      access_token: string;
      token_type: string;
      expires_in: number;
    };

    // 2. Fetch authenticated user profile using token
    const meRes = await fetch(`${backendUrl}/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${tokenData.access_token}`,
        Accept: "application/json",
      },
    });

    let userData: unknown = null;
    if (meRes.ok) {
      userData = await meRes.json();
    }

    // 3. Persist JWT in HttpOnly cookie and return user profile
    await setAuthCookie(tokenData.access_token, tokenData.expires_in);

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
