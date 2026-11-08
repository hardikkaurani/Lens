import { NextRequest, NextResponse } from "next/server";
import {
  clearAuthCookie,
  getBackendApiUrl,
  getStoredToken,
  LENS_TOKEN_COOKIE,
  verifyCsrfOrigin,
} from "@/lib/server-auth";

/**
 * Strict allowlist of allowed top-level API prefixes to prevent open-proxy abuse.
 */
const ALLOWED_PATH_PREFIXES = ["captures", "search", "integrations", "health"] as const;

/**
 * Hop-by-hop and sensitive headers that must NEVER be forwarded from browser to backend.
 */
const BLOCKED_FORWARD_HEADERS = new Set([
  "host",
  "connection",
  "cookie",
  "content-length",
  "authorization",
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

async function handleProxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  if (!path || path.length === 0) {
    return NextResponse.json({ detail: "Missing proxy path." }, { status: 400 });
  }

  // Validate path segments to prevent path traversal and encoding bypass attacks
  for (const segment of path) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      return NextResponse.json({ detail: "Malformed path segment encoding." }, { status: 400 });
    }

    if (
      decoded === ".." ||
      decoded === "." ||
      decoded.includes("/") ||
      decoded.includes("\\") ||
      decoded.includes("\0")
    ) {
      return NextResponse.json({ detail: "Invalid path traversal attempt." }, { status: 400 });
    }
  }

  const rootPrefix = path[0];
  if (!ALLOWED_PATH_PREFIXES.includes(rootPrefix as (typeof ALLOWED_PATH_PREFIXES)[number])) {
    return NextResponse.json(
      { detail: "Access to the requested resource path is forbidden." },
      { status: 403 }
    );
  }

  // Enforce CSRF origin checks on state-changing mutations
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  const backendBase = getBackendApiUrl();
  const subPath = path.map((s) => encodeURIComponent(decodeURIComponent(s))).join("/");
  const urlObj = new URL(request.url);
  const targetUrl = `${backendBase}/${subPath}${urlObj.search}`;

  const token = await getStoredToken();
  const headers = new Headers();

  // Forward client request headers, explicitly stripping blocked headers and client Authorization
  for (const [key, value] of request.headers.entries()) {
    const lower = key.toLowerCase();
    if (!BLOCKED_FORWARD_HEADERS.has(lower)) {
      headers.set(key, value);
    }
  }

  // Inject Bearer token strictly from the server-managed HttpOnly cookie
  if (token && token.trim().length > 0) {
    headers.set("Authorization", `Bearer ${token.trim()}`);
  }

  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD", "OPTIONS"].includes(method);

  const fetchOptions: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual", // Prevent automatic external redirects from leaking credentials
  };

  if (hasBody && request.body) {
    fetchOptions.body = request.body;
    fetchOptions.duplex = "half";
  }

  try {
    const backendRes = await fetch(targetUrl, fetchOptions);

    // Build response headers to return to browser
    const responseHeaders = new Headers();
    for (const [key, value] of backendRes.headers.entries()) {
      const lower = key.toLowerCase();
      if (!["content-encoding", "content-length", "transfer-encoding"].includes(lower)) {
        responseHeaders.set(key, value);
      }
    }

    // If backend reports 401 Unauthorized, automatically purge the invalid session cookie
    if (backendRes.status === 401) {
      await clearAuthCookie();
      const isProd = process.env.NODE_ENV === "production";
      responseHeaders.set(
        "Set-Cookie",
        `${LENS_TOKEN_COOKIE}=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax${isProd ? "; Secure" : ""}`
      );
    }

    return new NextResponse(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      { detail: "Unable to connect to LENS backend services." },
      { status: 503 }
    );
  }
}

export const GET = handleProxy;
export const POST = handleProxy;
export const PUT = handleProxy;
export const PATCH = handleProxy;
export const DELETE = handleProxy;
export const HEAD = handleProxy;
export const OPTIONS = handleProxy;
