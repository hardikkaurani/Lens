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

  let targetUrlObj: URL;
  try {
    targetUrlObj = new URL(`${backendBase}/${subPath}${urlObj.search}`);
  } catch {
    return NextResponse.json({ detail: "Invalid backend target URL." }, { status: 400 });
  }

  // Ensure target URL stays within the configured backend origin
  const backendBaseObj = new URL(backendBase);
  if (targetUrlObj.origin.toLowerCase() !== backendBaseObj.origin.toLowerCase()) {
    return NextResponse.json(
      { detail: "Target URL host mismatch." },
      { status: 403 }
    );
  }

  // Ensure normalized target pathname begins with an allowed prefix relative to configured backend base path
  const backendBasePath = backendBaseObj.pathname.replace(/^\/+|\/+$/g, "");
  const normalizedPath = targetUrlObj.pathname.replace(/^\/+/, "");
  const relativePath =
    backendBasePath.length > 0 && normalizedPath.startsWith(backendBasePath)
      ? normalizedPath.slice(backendBasePath.length).replace(/^\/+/, "")
      : normalizedPath;

  const hasAllowedPrefix = ALLOWED_PATH_PREFIXES.some(
    (prefix) => relativePath === prefix || relativePath.startsWith(`${prefix}/`)
  );
  if (!hasAllowedPrefix) {
    return NextResponse.json(
      { detail: "Access to the requested resource path is forbidden." },
      { status: 403 }
    );
  }

  const targetUrl = targetUrlObj.toString();

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

    // Rewrite backend-local Location headers on redirects to route through the proxy
    const location = backendRes.headers.get("location");
    if (location) {
      try {
        const backendBaseObj = new URL(backendBase);
        const locUrl = new URL(location, backendBase);
        if (locUrl.origin.toLowerCase() === backendBaseObj.origin.toLowerCase()) {
          const locPath = locUrl.pathname.replace(/^\/+/, "");
          responseHeaders.set("Location", `/api/proxy/${locPath}${locUrl.search}`);
        } else if (location.startsWith("/")) {
          responseHeaders.set("Location", `/api/proxy${location}`);
        }
      } catch {
        // Retain original Location if not parseable
      }
    }

    // If backend reports 401 Unauthorized, automatically purge the invalid session cookie
    // ONLY IF the rejected token has not already been superseded by a newer session
    if (backendRes.status === 401) {
      const cleared = await clearAuthCookie(token);
      if (cleared) {
        const isProd = process.env.NODE_ENV === "production";
        responseHeaders.set(
          "Set-Cookie",
          `${LENS_TOKEN_COOKIE}=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax${isProd ? "; Secure" : ""}`
        );
      }
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
