import { NextRequest, NextResponse } from "next/server";
import { clearAuthCookie, getStoredToken, verifyCsrfOrigin } from "@/lib/server-auth";

export async function POST(request: NextRequest) {
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  try {
    const token = await getStoredToken();
    if (token) {
      // Conditionally clear only if this token has not already been superseded by a concurrent login
      await clearAuthCookie(token);
    } else {
      await clearAuthCookie();
    }
  } catch {
    return NextResponse.json(
      { detail: "Failed to clear session authentication cookie." },
      { status: 500 }
    );
  }

  return NextResponse.json({ success: true, message: "Logged out successfully." }, { status: 200 });
}
