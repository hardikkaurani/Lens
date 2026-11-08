import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";
import { POST as loginHandler } from "@/app/api/auth/login/route";
import { GET as proxyGet, POST as proxyPost } from "@/app/api/proxy/[...path]/route";
import * as serverAuth from "@/lib/server-auth";

describe("BFF Auth & Proxy Hardening Security Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
      vi.spyOn(serverAuth, "getStoredToken").mockResolvedValueOnce("expired_token");
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
  });
});
