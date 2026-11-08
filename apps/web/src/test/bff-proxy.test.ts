import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";
import { POST as loginHandler } from "@/app/api/auth/login/route";
import { POST as logoutHandler } from "@/app/api/auth/logout/route";
import { GET as proxyGet, POST as proxyPost } from "@/app/api/proxy/[...path]/route";
import * as serverAuth from "@/lib/server-auth";

const mockCookieStore = {
  get: vi.fn(),
  set: vi.fn(),
  delete: vi.fn(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(() => Promise.resolve(mockCookieStore)),
}));

describe("BFF Auth & Proxy Hardening Security Tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    serverAuth.resetLatestToken();
  });

  describe("1. Login Route Validation & Fail-Closed Behavior", () => {
    it("rejects login request failing CSRF origin check with 403", async () => {
      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "https://evil-attacker.com",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(403);
      const data = await res.json();
      expect(data.detail).toContain("CSRF");
    });

    it("rejects malformed JSON payload with 400", async () => {
      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: "invalid-not-json",
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(400);
    });

    it("fails closed (502) and sets no cookie when token response is missing access_token", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie");

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({ token_type: "bearer", expires_in: 3600 }), // missing access_token
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(502);
      expect(setAuthCookieSpy).not.toHaveBeenCalled();
    });

    it("fails closed (502) and sets no cookie when token_type is not bearer", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie");

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "xyz", token_type: "mac", expires_in: 3600 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(502);
      expect(setAuthCookieSpy).not.toHaveBeenCalled();
    });

    it("fails closed (502) and sets no cookie when expires_in is negative or invalid", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie");

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "xyz", token_type: "bearer", expires_in: -100 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(502);
      expect(setAuthCookieSpy).not.toHaveBeenCalled();
    });

    it("accepts backend token whose lifetime exceeds 30-day cookie cap and caps cookie independently", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie");
      const seventyDays = 70 * 24 * 60 * 60; // 70 days > 30 days
      const thirtyDays = 30 * 24 * 60 * 60;

      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ access_token: "long_lived_jwt", token_type: "bearer", expires_in: seventyDays }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ id: "u-123", email: "user@example.com" }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.success).toBe(true);
      expect(setAuthCookieSpy).toHaveBeenCalledWith("long_lived_jwt", thirtyDays);
    });

    it("fails closed (502) and sets no cookie when /auth/me fails after login", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie");

      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ access_token: "valid_jwt_token", token_type: "bearer", expires_in: 3600 }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ detail: "Database connection failed" }),
            { status: 500, headers: { "Content-Type": "application/json" } }
          )
        );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(502);
      const data = await res.json();
      expect(data.detail).toContain("Failed to retrieve user profile");
      expect(setAuthCookieSpy).not.toHaveBeenCalled();
    });

    it("sets cookie and returns user profile when all validations succeed", async () => {
      const setAuthCookieSpy = vi.spyOn(serverAuth, "setAuthCookie").mockResolvedValueOnce();

      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ access_token: "valid_jwt_token", token_type: "bearer", expires_in: 3600 }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ id: "user-123", email: "user@example.com", is_active: true }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.success).toBe(true);
      expect(data.user.email).toBe("user@example.com");
      expect(setAuthCookieSpy).toHaveBeenCalledWith("valid_jwt_token", 3600);
    });
  });

  describe("2. BFF Reverse Proxy Security & Session Lifecycle", () => {
    it("rejects path traversal attempts with 400", async () => {
      const req = new NextRequest("http://localhost:3000/api/proxy/captures/../admin", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures", "..", "admin"] }),
      });
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.detail).toContain("Invalid path traversal");
    });

    it("rejects non-allowlisted prefix with 403", async () => {
      const req = new NextRequest("http://localhost:3000/api/proxy/internal_metrics", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["internal_metrics"] }),
      });
      expect(res.status).toBe(403);
    });

    it("strips client-provided Authorization header and uses cookie token", async () => {
      vi.spyOn(serverAuth, "getStoredToken").mockResolvedValueOnce("cookie_stored_token");

      let recordedAuthHeader: string | null = null;
      vi.spyOn(globalThis, "fetch").mockImplementationOnce(async (_url, options) => {
        const headers = options?.headers as Headers;
        recordedAuthHeader = headers.get("Authorization");
        return new Response(JSON.stringify({ captures: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      });

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: {
          host: "localhost:3000",
          Authorization: "Bearer forged_client_token", // Malicious header from browser
        },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(200);
      expect(recordedAuthHeader).toBe("Bearer cookie_stored_token");
    });

    it("clears session cookie on backend 401 response", async () => {
      vi.spyOn(serverAuth, "getStoredToken").mockResolvedValue("expired_token");
      const clearAuthCookieSpy = vi.spyOn(serverAuth, "clearAuthCookie").mockResolvedValueOnce(true);

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Token expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(401);
      expect(clearAuthCookieSpy).toHaveBeenCalled();
      const setCookie = res.headers.get("Set-Cookie");
      expect(setCookie).toContain("lens_access_token=");
      expect(setCookie).toContain("Max-Age=0");
    });

    it("preserves replacement session cookie when 401 returns for stale token", async () => {
      serverAuth.recordTokenIssued("newer_token_from_login");
      vi.spyOn(serverAuth, "getStoredToken").mockResolvedValue("stale_token");

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Token expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(401);
      expect(mockCookieStore.delete).not.toHaveBeenCalled();
      expect(res.headers.get("Set-Cookie")).toBeNull();
    });

    it("13. Delayed 401 response cannot remove a replacement login cookie (real proxy response and cookie mutation)", async () => {
      // Helper creating structurally valid test JWTs with placeholder signatures
      function makeTestJwt(sub: string, seq: number): string {
        const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({ sub, seq, exp: 9999999999 })).toString("base64url");
        return `${header}.${payload}.test_sig_${sub}_${seq}`;
      }

      const tokenA = makeTestJwt("user_alice", 1);
      const tokenB = makeTestJwt("user_alice", 2);

      // Alice initially logs in with tokenA
      serverAuth.recordTokenIssued(tokenA);
      mockCookieStore.get.mockReturnValue({ value: tokenA });

      // Request 1 arrives at the proxy carrying tokenA
      let finishBackendRes!: (res: Response) => void;
      const delayedBackendFetch = new Promise<Response>((resolve) => {
        finishBackendRes = resolve;
      });
      vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => delayedBackendFetch);

      const req1 = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });
      const proxyPromise = proxyGet(req1, {
        params: Promise.resolve({ path: ["captures"] }),
      });

      // While Request 1's upstream fetch is delayed, Alice completes a replacement login with tokenB
      // This sets the new cookie in mockCookieStore and updates the registry
      await serverAuth.setAuthCookie(tokenB, 3600);
      mockCookieStore.get.mockReturnValue({ value: tokenB });

      // Request 1's upstream backend fetch returns 401 Unauthorized for tokenA
      finishBackendRes(
        new Response(JSON.stringify({ detail: "Token A expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      const res1 = await proxyPromise;
      expect(res1.status).toBe(401);

      // REAL ROUTE ASSERTIONS:
      // 1. The proxy response must NOT set Set-Cookie: Max-Age=0 because tokenA was superseded!
      expect(res1.headers.get("Set-Cookie")).toBeNull();

      // 2. The cookieStore.delete must NEVER have been called for the superseded token
      expect(mockCookieStore.delete).not.toHaveBeenCalled();

      // 3. The replacement tokenB is affirmatively verified as active
      expect(serverAuth.isLatestToken(tokenB)).toBe(true);
      expect(serverAuth.isLatestToken(tokenA)).toBe(false);
    });

    it("14. Per-user session isolation: Alice replacement login does not supersede Bob active session", async () => {
      // Helper creating structurally valid test JWTs with placeholder signatures
      // (BFF tracks identity by sub; backend cryptographically verifies HMAC signatures)
      function makeTestJwt(sub: string, seq: number): string {
        const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({ sub, seq, exp: 9999999999 })).toString("base64url");
        return `${header}.${payload}.test_sig_${sub}_${seq}`;
      }

      const tokenAlice1 = makeTestJwt("user_alice", 1);
      const tokenBob1 = makeTestJwt("user_bob", 1);

      // Both users establish independent sessions
      serverAuth.recordTokenIssued(tokenAlice1);
      serverAuth.recordTokenIssued(tokenBob1);

      expect(serverAuth.isLatestToken(tokenAlice1)).toBe(true);
      expect(serverAuth.isLatestToken(tokenBob1)).toBe(true);

      // Alice receives a replacement session (e.g. from relogin or token refresh)
      const tokenAlice2 = makeTestJwt("user_alice", 2);
      serverAuth.recordTokenIssued(tokenAlice2);

      // Alice's old token is superseded, while her new token is active
      expect(serverAuth.isLatestToken(tokenAlice1)).toBe(false);
      expect(serverAuth.isLatestToken(tokenAlice2)).toBe(true);

      // Bob's session remains completely valid and un-superseded
      expect(serverAuth.isLatestToken(tokenBob1)).toBe(true);

      // Verify proxy behavior for Alice's superseded token: does not clear cookies
      mockCookieStore.get.mockReturnValue({ value: tokenAlice1 });
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Token Alice 1 expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });

      expect(res.status).toBe(401);
      expect(mockCookieStore.delete).not.toHaveBeenCalled();
      expect(res.headers.get("Set-Cookie")).toBeNull();
      // Bob's token is STILL valid
      expect(serverAuth.isLatestToken(tokenBob1)).toBe(true);
    });

    it("15. Check-then-delete async boundary race: clearAuthCookie aborts if replacement login completes while awaiting cookieStore", async () => {
      function makeTestJwt(sub: string, seq: number): string {
        const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({ sub, seq, exp: 9999999999 })).toString("base64url");
        return `${header}.${payload}.test_sig_${sub}_${seq}`;
      }

      const tokenOld = makeTestJwt("user_race", 1);
      const tokenNew = makeTestJwt("user_race", 2);

      serverAuth.recordTokenIssued(tokenOld);
      expect(serverAuth.isLatestToken(tokenOld)).toBe(true);

      // Simulate async boundary inside clearAuthCookie: cookies() takes a microtask turn
      let resolveCookies!: () => void;
      const delayedCookiesPromise = new Promise<typeof mockCookieStore>((resolve) => {
        resolveCookies = () => resolve(mockCookieStore);
      });

      const { cookies } = await import("next/headers");
      vi.mocked(cookies).mockImplementationOnce(() => delayedCookiesPromise as any);

      // Start clearAuthCookie for tokenOld
      const clearPromise = serverAuth.clearAuthCookie(tokenOld);

      // While clearAuthCookie is awaiting cookies(), a replacement login arrives and establishes tokenNew!
      serverAuth.recordTokenIssued(tokenNew);
      expect(serverAuth.isLatestToken(tokenNew)).toBe(true);
      expect(serverAuth.isLatestToken(tokenOld)).toBe(false);

      // Now cookies() resolves
      resolveCookies();
      const cleared = await clearPromise;

      // Assert: clearAuthCookie detected the concurrent replacement and aborted deletion!
      expect(cleared).toBe(false);
      expect(mockCookieStore.delete).not.toHaveBeenCalled();
      // New token remains registered and protected
      expect(serverAuth.isLatestToken(tokenNew)).toBe(true);
    });

    it("16. Cold start / process restart fails closed: unknown token cannot clear cookies", async () => {
      serverAuth.resetLatestToken(); // Simulates fresh instance or restarted process

      const unknownToken = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url") +
        "." +
        Buffer.from(JSON.stringify({ sub: "user_restart", exp: 9999999999 })).toString("base64url") +
        ".sig";

      // Registry has no record for this user
      expect(serverAuth.isLatestToken(unknownToken)).toBe(false);

      // clearAuthCookie with unknown token must fail closed and return false
      const cleared = await serverAuth.clearAuthCookie(unknownToken);
      expect(cleared).toBe(false);
      expect(mockCookieStore.delete).not.toHaveBeenCalled();

      // Proxy handling 401 with unknown token returns 401 without Set-Cookie
      mockCookieStore.get.mockReturnValue({ value: unknownToken });
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Token invalid" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });
      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });

      expect(res.status).toBe(401);
      expect(res.headers.get("Set-Cookie")).toBeNull();
      expect(mockCookieStore.delete).not.toHaveBeenCalled();
    });

    it("17. Multi-instance isolation: separate worker instances without shared state fail closed safely", async () => {
      function makeTestJwt(sub: string, seq: number): string {
        const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({ sub, seq, exp: 9999999999 })).toString("base64url");
        return `${header}.${payload}.sig_${sub}_${seq}`;
      }

      const tokenAlice1 = makeTestJwt("user_alice", 1);
      const tokenAlice2 = makeTestJwt("user_alice", 2);

      // Worker A (instanceA) and Worker B (instanceB) have independent registries
      const registryInstanceA = new serverAuth.SessionTokenRegistry();
      const registryInstanceB = new serverAuth.SessionTokenRegistry();

      // Worker A handled Alice's replacement login
      registryInstanceA.recordIssued(tokenAlice2);
      expect(registryInstanceA.isTokenCurrent(tokenAlice1)).toBe(false);
      expect(registryInstanceA.isTokenCurrent(tokenAlice2)).toBe(true);

      // Worker B receives a delayed request with tokenAlice1.
      // Worker B has no record of tokenAlice2, but MUST fail closed:
      // It does NOT assume tokenAlice1 is current just because its registry is empty!
      expect(registryInstanceB.isTokenCurrent(tokenAlice1)).toBe(false);
      expect(registryInstanceB.isTokenCurrent(tokenAlice2)).toBe(false);
    });

    it("18. Invalidation semantics and compare-and-clear (CAS) registry deletion", async () => {
      function makeTestJwt(sub: string, seq: number): string {
        const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({ sub, seq, exp: 9999999999 })).toString("base64url");
        return `${header}.${payload}.sig_${sub}_${seq}`;
      }

      const token1 = makeTestJwt("user_cas", 1);
      const token2 = makeTestJwt("user_cas", 2);

      serverAuth.recordTokenIssued(token1);
      serverAuth.recordTokenIssued(token2); // Superseded token1

      // Stale clearing attempt for token1: must NOT delete token2 from registry!
      serverAuth.recordTokenCleared(token1);
      expect(serverAuth.isLatestToken(token2)).toBe(true);
      expect(serverAuth.isLatestToken(token1)).toBe(false);

      // Clearing active token2: successfully clears user entry
      serverAuth.recordTokenCleared(token2);
      expect(serverAuth.isLatestToken(token2)).toBe(false);

      // Explicit logout route: unconditionally clears cookie and cleans registry
      mockCookieStore.get.mockReturnValue({ value: token2 });
      const logoutReq = new NextRequest("http://localhost:3000/api/auth/logout", {
        method: "POST",
        headers: { host: "localhost:3000", origin: "http://localhost:3000" },
      });
      const logoutRes = await logoutHandler(logoutReq);
      expect(logoutRes.status).toBe(200);
      expect(mockCookieStore.delete).toHaveBeenCalledWith(serverAuth.LENS_TOKEN_COOKIE);
    });

    it("19. parseJwtClaims strictly decodes claims and safely rejects malformed or untrusted inputs", () => {
      // Valid JWT format
      const validPayload = { sub: "usr_42", email: "alice@lens.app", iat: 1000, exp: 2000 };
      const validJwt = "eyJhbGciOiJIUzI1NiJ9." +
        Buffer.from(JSON.stringify(validPayload)).toString("base64url") +
        ".signature_placeholder";

      const claims = serverAuth.parseJwtClaims(validJwt);
      expect(claims).not.toBeNull();
      expect(claims?.sub).toBe("usr_42");
      expect(claims?.email).toBe("alice@lens.app");

      // Malformed: Not 3 dot-separated parts
      expect(serverAuth.parseJwtClaims("only-one-part")).toBeNull();
      expect(serverAuth.parseJwtClaims("two.parts")).toBeNull();
      expect(serverAuth.parseJwtClaims("four.parts.here.extra")).toBeNull();

      // Malformed: Invalid base64url characters
      expect(serverAuth.parseJwtClaims("header.invalid!@#$base64.sig")).toBeNull();

      // Malformed: Non-JSON payload
      const nonJsonJwt = "header." + Buffer.from("this is not json").toString("base64url") + ".sig";
      expect(serverAuth.parseJwtClaims(nonJsonJwt)).toBeNull();

      // Malformed: Missing sub claim
      const noSubJwt = "header." + Buffer.from(JSON.stringify({ email: "no-sub@lens.app" })).toString("base64url") + ".sig";
      expect(serverAuth.parseJwtClaims(noSubJwt)).toBeNull();

      // Malformed: Non-string sub claim
      const numericSubJwt = "header." + Buffer.from(JSON.stringify({ sub: 12345 })).toString("base64url") + ".sig";
      expect(serverAuth.parseJwtClaims(numericSubJwt)).toBeNull();

      // Malformed: Empty or whitespace sub claim
      const emptySubJwt = "header." + Buffer.from(JSON.stringify({ sub: "   " })).toString("base64url") + ".sig";
      expect(serverAuth.parseJwtClaims(emptySubJwt)).toBeNull();

      // Null, empty string, non-string token
      expect(serverAuth.parseJwtClaims("")).toBeNull();
      expect(serverAuth.parseJwtClaims(null as any)).toBeNull();
      expect(serverAuth.parseJwtClaims(undefined as any)).toBeNull();
    });

    it("allows /captures when backend base URL contains /v1 prefix", async () => {
      vi.spyOn(serverAuth, "getBackendApiUrl").mockReturnValueOnce("http://127.0.0.1:8000/v1");
      vi.spyOn(serverAuth, "getStoredToken").mockResolvedValue("mock_token");

      let calledUrl = "";
      vi.spyOn(globalThis, "fetch").mockImplementationOnce((url) => {
        calledUrl = url.toString();
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], total: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );
      });

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(200);
      expect(calledUrl).toContain("http://127.0.0.1:8000/v1/captures");
    });

    it("rejects mutating request when Host header is missing", async () => {
      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        method: "POST",
        headers: {
          origin: "http://localhost:3000",
          // Host header intentionally missing
        },
        body: JSON.stringify({ url: "https://example.com" }),
      });

      const res = await proxyPost(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(403);
      const data = await res.json();
      expect(data.detail).toContain("CSRF");
    });

    it("accepts mutating request when origin matches configured TRUSTED_ORIGIN", async () => {
      const originalEnv = process.env.TRUSTED_ORIGIN;
      process.env.TRUSTED_ORIGIN = "https://app.lens.domain";

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ success: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

      const req = new NextRequest("https://proxy.internal/api/proxy/captures", {
        method: "POST",
        headers: {
          host: "proxy.internal",
          origin: "https://app.lens.domain",
        },
        body: JSON.stringify({ url: "https://example.com" }),
      });

      const res = await proxyPost(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(200);

      process.env.TRUSTED_ORIGIN = originalEnv;
    });

    it("rewrites backend-local Location headers on redirects to /api/proxy", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, {
          status: 302,
          headers: {
            Location: "http://localhost:8000/captures/cap-123?view=detail",
          },
        })
      );

      const req = new NextRequest("http://localhost:3000/api/proxy/captures", {
        headers: { host: "localhost:3000" },
      });

      const res = await proxyGet(req, {
        params: Promise.resolve({ path: ["captures"] }),
      });
      expect(res.status).toBe(302);
      expect(res.headers.get("Location")).toBe("/api/proxy/captures/cap-123?view=detail");
    });
  });

  describe("4. Cookie Mutation Integrity & Fail-Closed Behavior (Stage 19.3.1)", () => {
    it("setAuthCookie throws when cookie store set fails and clearAuthCookie throws when delete fails", async () => {
      mockCookieStore.set.mockImplementationOnce(() => {
        throw new Error("Cookie storage unavailable");
      });
      await expect(serverAuth.setAuthCookie("token123", 3600)).rejects.toThrow("Cookie storage unavailable");

      mockCookieStore.delete.mockImplementationOnce(() => {
        throw new Error("Cookie storage deletion failed");
      });
      await expect(serverAuth.clearAuthCookie()).rejects.toThrow("Cookie storage deletion failed");
    });

    it("login route fails closed (500) and does not return false success when setAuthCookie throws", async () => {
      vi.spyOn(serverAuth, "setAuthCookie").mockRejectedValueOnce(
        new Error("Keystore unavailable")
      );

      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ access_token: "jwt-token-abc", token_type: "bearer", expires_in: 3600 }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ id: "u-123", email: "user@example.com", is_active: true }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );

      const req = new NextRequest("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
      });

      const res = await loginHandler(req);
      expect(res.status).toBe(500);
      const data = await res.json();
      expect(data.detail).toContain("Failed to establish secure session cookie");
      expect(data.success).toBeUndefined();
    });

    it("logout route fails closed (500) and does not return false success when clearAuthCookie throws", async () => {
      vi.spyOn(serverAuth, "clearAuthCookie").mockRejectedValueOnce(
        new Error("Cookie store write error")
      );

      const req = new NextRequest("http://localhost:3000/api/auth/logout", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
      });

      const res = await logoutHandler(req);
      expect(res.status).toBe(500);
      const data = await res.json();
      expect(data.detail).toContain("Failed to clear session authentication cookie");
      expect(data.success).toBeUndefined();
    });
  });
});
