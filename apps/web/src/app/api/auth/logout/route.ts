import { NextRequest, NextResponse } from "next/server";
import { clearAuthCookie, getStoredToken, recordTokenCleared, verifyCsrfOrigin } from "@/lib/server-auth";

export async function POST(request: NextRequest) {
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  try {
    const token = await getStoredToken();
    await clearAuthCookie();
    if (token) {
      recordTokenCleared(token);
    }
  } catch {
    return NextResponse.json(
      { detail: "Failed to clear session authentication cookie." },
      { status: 500 }
    );
  }

  return NextResponse.json({ success: true, message: "Logged out successfully." }, { status: 200 });
}
