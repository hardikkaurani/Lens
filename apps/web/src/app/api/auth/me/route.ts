import { NextRequest, NextResponse } from "next/server";
import { clearAuthCookie, getBackendApiUrl, getStoredToken } from "@/lib/server-auth";

export async function GET(_request: NextRequest) {
  const token = await getStoredToken();
  if (!token) {
    return NextResponse.json(
      { detail: "Authentication credentials were not provided." },
      { status: 401 }
    );
  }

  const backendUrl = getBackendApiUrl();
  try {
    const res = await fetch(`${backendUrl}/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });

    if (res.status === 401) {
      // Token is invalid or expired: purge invalid cookie
      await clearAuthCookie();
      return NextResponse.json(
        { detail: "Session expired or invalid credentials." },
        { status: 401 }
      );
    }

    const data = await res.json().catch(() => ({ detail: "Invalid server response." }));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { detail: "Unable to connect to LENS authentication service." },
      { status: 503 }
    );
  }
}
