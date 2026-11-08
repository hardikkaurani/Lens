import { NextRequest, NextResponse } from "next/server";
import { getStoredToken, verifyCsrfOrigin } from "@/lib/server-auth";
import * as serverAuth from "@/lib/server-auth";

export async function POST(request: NextRequest) {
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  try {
    const token = await getStoredToken();
    if (!token || typeof token !== "string" || !token.trim()) {
      // Safe fail-closed semantics:
      // A missing, absent, or whitespace-only token snapshot MUST NEVER trigger
      // unconditional cookie deletion. Return 200 indicating no active session
      // is present to clear, without performing destructive cookie mutations that
      // could wipe a newer replacement login or concurrent tab session.
      return NextResponse.json(
        { success: true, message: "No active session to clear." },
        { status: 200 }
      );
    }

    // Conditionally clear only if this specific token is active and not superseded
    await serverAuth.clearAuthCookie(token);
  } catch {
    return NextResponse.json(
      { detail: "Failed to clear session authentication cookie." },
      { status: 500 }
    );
  }

  return NextResponse.json({ success: true, message: "Logged out successfully." }, { status: 200 });
}
