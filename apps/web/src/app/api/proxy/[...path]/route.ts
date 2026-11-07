import { NextRequest, NextResponse } from "next/server";
import { getBackendApiUrl, getStoredToken, verifyCsrfOrigin } from "@/lib/server-auth";

/**
 * Whitelist of allowed top-level API prefixes to prevent open-proxy abuse.
 */
const ALLOWED_PATH_PREFIXES = ["captures", "search", "integrations", "health"];

async function handleProxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (!path || path.length === 0) {
    return NextResponse.json({ detail: "Missing proxy path." }, { status: 400 });
  }

  const rootPrefix = path[0];
  if (!ALLOWED_PATH_PREFIXES.includes(rootPrefix)) {
    return NextResponse.json(
      { detail: "Access to the requested resource path is forbidden." },
      { status: 403 }
    );
  }

  // Enforce CSRF origin checks on mutations
  if (!verifyCsrfOrigin(request)) {
    return NextResponse.json(
      { detail: "CSRF origin validation failed." },
      { status: 403 }
    );
  }

  const backendBase = getBackendApiUrl();
  const subPath = path.join("/");
  const urlObj = new URL(request.url);
  const targetUrl = `${backendBase}/${subPath}${urlObj.search}`;

  const token = await getStoredToken();
  const headers = new Headers();

  // Forward client request headers, excluding host and hop-by-hop headers
  for (const [key, value] of request.headers.entries()) {
    const lower = key.toLowerCase();
    if (!["host", "connection", "cookie", "content-length"].includes(lower)) {
      headers.set(key, value);
    }
  }

  // Inject Bearer token from HttpOnly cookie
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD", "OPTIONS"].includes(method);

  let body: ReadableStream<Uint8Array> | null = null;
  const fetchOptions: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
  };

  if (hasBody && request.body) {
    body = request.body;
    fetchOptions.body = body;
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
