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
      const clearAuthCookieSpy = vi.spyOn(serverAuth, "clearAuthCookie").mockResolvedValueOnce();

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
      vi.spyOn(serverAuth, "getStoredToken")
        .mockResolvedValueOnce("stale_token")
        .mockResolvedValueOnce("newer_token_from_login");
      const clearAuthCookieSpy = vi.spyOn(serverAuth, "clearAuthCookie");

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
      expect(clearAuthCookieSpy).not.toHaveBeenCalled();
      expect(res.headers.get("Set-Cookie")).toBeNull();
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
