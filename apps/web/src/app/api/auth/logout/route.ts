import { NextRequest, NextResponse } from "next/server";
import { clearAuthCookie, verifyCsrfOrigin } from "@/lib/server-auth";

export async function POST(request: NextRequest) {
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  await clearAuthCookie();
  return NextResponse.json({ success: true, message: "Logged out successfully." }, { status: 200 });
}
