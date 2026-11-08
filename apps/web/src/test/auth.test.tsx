import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import LoginPage from "@/app/login/page";
import RegisterPage from "@/app/register/page";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { verifyCsrfOrigin } from "@/lib/server-auth";

// Mock next/navigation
const mockPush = vi.fn();
const mockRefresh = vi.fn();
let mockPathname = "/captures";
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    refresh: mockRefresh,
  }),
  usePathname: () => mockPathname,
  useSearchParams: () => mockSearchParams,
}));

describe("Web Authentication & Client Integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/captures";
    mockSearchParams = new URLSearchParams();
  });

  describe("1. API Client Auth Methods", () => {
    it("register sends payload to /api/auth/register", async () => {
      const mockUser = { id: "u-123", email: "user@example.com", is_active: true };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(mockUser), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        })
      );

      const result = await apiClient.register({ email: "user@example.com", password: "Password123!" });
      expect(result).toEqual(mockUser);
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "Content-Type": "application/json" }),
          body: JSON.stringify({ email: "user@example.com", password: "Password123!" }),
        })
      );
    });

    it("login sends credentials to /api/auth/login", async () => {
      const mockSession = { user: { id: "u-123", email: "user@example.com", is_active: true } };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(mockSession), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

      const result = await apiClient.login({ email: "user@example.com", password: "Password123!" });
      expect(result).toEqual(mockSession);
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({
          method: "POST",
          credentials: "same-origin",
        })
      );
    });

    it("getMe retrieves active user session from /api/auth/me", async () => {
      const mockUser = { id: "u-123", email: "user@example.com", is_active: true };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(mockUser), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

      const result = await apiClient.getMe();
      expect(result).toEqual(mockUser);
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/me",
        expect.objectContaining({
          method: "GET",
          credentials: "same-origin",
        })
      );
    });

    it("logout clears cookie session via /api/auth/logout", async () => {
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ message: "Logged out successfully" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

      await apiClient.logout();
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/logout",
        expect.objectContaining({
          method: "POST",
          credentials: "same-origin",
        })
      );
    });

    it("throws ApiClientError with status 401 on authentication failure", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Invalid email or password" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      );

      await expect(
        apiClient.login({ email: "wrong@domain.com", password: "badpassword" })
      ).rejects.toThrow(ApiClientError);
    });
  });

  describe("2. Server CSRF Protection", () => {
    it("accepts requests when origin matches host", () => {
      const req = new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "http://localhost:3000",
        },
      });
      expect(verifyCsrfOrigin(req)).toBe(true);
    });

    it("accepts requests when referer matches host", () => {
      const req = new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          referer: "http://localhost:3000/login",
        },
      });
      expect(verifyCsrfOrigin(req)).toBe(true);
    });

    it("rejects cross-site requests with mismatched origin", () => {
      const req = new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
          origin: "https://evil-attacker.com",
        },
      });
      expect(verifyCsrfOrigin(req)).toBe(false);
    });

    it("rejects requests missing both origin and referer", () => {
      const req = new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: {
          host: "localhost:3000",
        },
      });
      expect(verifyCsrfOrigin(req)).toBe(false);
    });
  });

  describe("3. Login Page UX & Flow", () => {
    it("renders official LENS logo and login form elements", () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      expect(screen.getByText("Sign in to LENS")).toBeDefined();
      expect(screen.getByLabelText(/Email Address/i)).toBeDefined();
      expect(screen.getByLabelText(/^Password/i)).toBeDefined();
      expect(screen.getByRole("button", { name: /^Sign in$/i })).toBeDefined();
      expect(screen.getByText(/Create an account/i)).toBeDefined();
    });

    it("validates empty and invalid email client-side", async () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const submitButton = screen.getByRole("button", { name: /^Sign in$/i });
      fireEvent.click(submitButton);

      expect(await screen.findByText("Email address is required.")).toBeDefined();

      const emailInput = screen.getByLabelText(/Email Address/i);
      fireEvent.change(emailInput, { target: { value: "invalid-email" } });
      fireEvent.click(submitButton);

      expect(await screen.findByText("Please enter a valid email address.")).toBeDefined();
    });

    it("validates empty password client-side", async () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const emailInput = screen.getByLabelText(/Email Address/i);
      fireEvent.change(emailInput, { target: { value: "user@example.com" } });

      const submitButton = screen.getByRole("button", { name: /^Sign in$/i });
      fireEvent.click(submitButton);

      expect(await screen.findByText("Password is required.")).toBeDefined();
    });

    it("toggles password visibility", () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const passwordInput = screen.getByLabelText(/^Password/i) as HTMLInputElement;
      expect(passwordInput.type).toBe("password");

      const toggleButton = screen.getByRole("button", { name: "Show" });
      fireEvent.click(toggleButton);

      expect(passwordInput.type).toBe("text");
      expect(screen.getByRole("button", { name: "Hide" })).toBeDefined();
    });

    it("handles successful login and redirects to default or custom redirect url", async () => {
      mockSearchParams = new URLSearchParams("redirect=/settings");
      vi.spyOn(apiClient, "login").mockResolvedValueOnce({
        success: true,
        user: { id: "u-1", email: "user@example.com", is_active: true },
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "user@example.com" },
      });
      fireEvent.change(screen.getByLabelText(/^Password/i), {
        target: { value: "Password123!" },
      });

      fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/settings");
      });
    });

    it("displays error message on invalid credentials 401", async () => {
      vi.spyOn(apiClient, "login").mockRejectedValueOnce(
        new ApiClientError(401, "Invalid email or password")
      );

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "user@example.com" },
      });
      fireEvent.change(screen.getByLabelText(/^Password/i), {
        target: { value: "WrongPassword" },
      });

      fireEvent.click(screen.getByRole("button", { name: /^Sign in$/i }));

      expect(
        await screen.findByText("Invalid email or password. Please verify your credentials.")
      ).toBeDefined();
    });
  });

  describe("4. Register Page UX & Flow", () => {
    it("renders registration form with required fields", () => {
      render(
        <AuthProvider>
          <RegisterPage />
        </AuthProvider>
      );

      expect(screen.getByText("Create your LENS Account")).toBeDefined();
      expect(screen.getByLabelText(/Email Address/i)).toBeDefined();
      expect(screen.getByLabelText(/Password \(min\. 8 characters\)/i)).toBeDefined();
      expect(screen.getByLabelText(/Confirm Password/i)).toBeDefined();
      expect(screen.getByRole("button", { name: /^Create account$/i })).toBeDefined();
    });

    it("enforces minimum password length of 8 characters", async () => {
      render(
        <AuthProvider>
          <RegisterPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "user@example.com" },
      });
      fireEvent.change(screen.getByLabelText(/Password \(min\. 8 characters\)/i), {
        target: { value: "short" },
      });
      fireEvent.change(screen.getByLabelText(/Confirm Password/i), {
        target: { value: "short" },
      });

      fireEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

      expect(await screen.findByText("Password must be at least 8 characters long.")).toBeDefined();
    });

    it("enforces password confirmation match", async () => {
      render(
        <AuthProvider>
          <RegisterPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "user@example.com" },
      });
      fireEvent.change(screen.getByLabelText(/Password \(min\. 8 characters\)/i), {
        target: { value: "Password123!" },
      });
      fireEvent.change(screen.getByLabelText(/Confirm Password/i), {
        target: { value: "DifferentPassword123!" },
      });

      fireEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

      expect(await screen.findByText("Passwords do not match.")).toBeDefined();
    });

    it("displays friendly message on duplicate email registration 409", async () => {
      vi.spyOn(apiClient, "register").mockRejectedValueOnce(
        new ApiClientError(409, "User already exists")
      );

      render(
        <AuthProvider>
          <RegisterPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "existing@example.com" },
      });
      fireEvent.change(screen.getByLabelText(/Password \(min\. 8 characters\)/i), {
        target: { value: "Password123!" },
      });
      fireEvent.change(screen.getByLabelText(/Confirm Password/i), {
        target: { value: "Password123!" },
      });

      fireEvent.click(screen.getByRole("button", { name: /^Create account$/i }));

      expect(
        await screen.findByText("An account with this email address already exists. Please sign in instead.")
      ).toBeDefined();
    });
  });

  describe("5. Protected Route Guard", () => {
    it("renders children when user is authenticated", async () => {
      vi.spyOn(apiClient, "getMe").mockResolvedValueOnce({
        id: "u-123",
        email: "authed@example.com",
        is_active: true,
      });

      render(
        <AuthProvider>
          <ProtectedRoute>
            <div data-testid="protected-content">Secret Notes</div>
          </ProtectedRoute>
        </AuthProvider>
      );

      expect(await screen.findByTestId("protected-content")).toBeDefined();
      expect(screen.getByText("Secret Notes")).toBeDefined();
    });

    it("redirects unauthenticated users to /login with encoded redirect query", async () => {
      mockPathname = "/captures/new";

      // Mock getMe returning 401
      vi.spyOn(apiClient, "getMe").mockRejectedValueOnce(
        new ApiClientError(401, "Unauthorized")
      );

      render(
        <AuthProvider>
          <ProtectedRoute>
            <div>Protected Content</div>
          </ProtectedRoute>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/login?redirect=%2Fcaptures%2Fnew");
      });
    });
  });

  describe("6. Fail-Closed AuthContext Guarantees", () => {
    it("throws explicit error when useAuth is called outside AuthProvider", () => {
      function NakedConsumer() {
        useAuth();
        return <div>Naked</div>;
      }

      // Suppress React boundary console.error during expected throw
      const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      expect(() => render(<NakedConsumer />)).toThrow(
        "useAuth must be used within an AuthProvider"
      );

      errorSpy.mockRestore();
    });

    it("fails closed with user=null and isAuthenticated=false when getMe returns 401", async () => {
      vi.spyOn(apiClient, "getMe").mockRejectedValueOnce(
        new ApiClientError(401, "Unauthorized")
      );

      let observedContext: ReturnType<typeof useAuth> | null = null;
      function ContextProbe() {
        observedContext = useAuth();
        return <div>Probe</div>;
      }

      render(
        <AuthProvider>
          <ContextProbe />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(observedContext).not.toBeNull();
        expect(observedContext!.isLoading).toBe(false);
      });

      expect(observedContext!.user).toBeNull();
      expect(observedContext!.isAuthenticated).toBe(false);
    });

    it("never returns a fake or hardcoded default user", async () => {
      vi.spyOn(apiClient, "getMe").mockRejectedValueOnce(
        new ApiClientError(401, "Unauthorized")
      );

      let probedUser: unknown = "initial-sentinel";
      function SentinelProbe() {
        const { user } = useAuth();
        probedUser = user;
        return <div>Sentinel</div>;
      }

      render(
        <AuthProvider>
          <SentinelProbe />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(probedUser).toBeNull();
      });

      expect(probedUser).not.toEqual(
        expect.objectContaining({ email: "user@example.com", id: "default-user" })
      );
    });
  });

  describe("6. Hardening Regression Tests (Stage 19.3.1)", () => {
    it("race condition: slow refreshUser does not overwrite newer login", async () => {
      let resolveGetMe: (val: any) => void = () => {};
      const slowGetMePromise = new Promise((resolve) => {
        resolveGetMe = resolve;
      });
      vi.spyOn(apiClient, "getMe").mockReturnValueOnce(slowGetMePromise as any);

      let auth: ReturnType<typeof useAuth> | null = null;
      function TestComponent() {
        auth = useAuth();
        return <div>{auth.user?.email || "none"}</div>;
      }

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      // Now trigger a login while getMe is still in flight
      const loggedInUser = { id: "u-fast", email: "fast@example.com", is_active: true };
      vi.spyOn(apiClient, "login").mockResolvedValueOnce({ user: loggedInUser });

      await waitFor(() => {
        expect(auth).not.toBeNull();
      });

      await auth!.login("fast@example.com", "pass");

      await waitFor(() => {
        expect(auth!.user).toEqual(loggedInUser);
      });

      // Now resolve the older slow getMe with 401 or null
      resolveGetMe(null);
      await new Promise((r) => setTimeout(r, 10));

      // Active user MUST NOT be overwritten
      expect(auth!.user).toEqual(loggedInUser);
    });

    it("503 / network error sets verificationError and preserves session without redirecting", async () => {
      vi.spyOn(apiClient, "getMe").mockRejectedValueOnce(
        new ApiClientError(503, "Backend Database Unavailable")
      );

      render(
        <AuthProvider>
          <ProtectedRoute>
            <div>Protected Content</div>
          </ProtectedRoute>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-verification-error")).toBeInTheDocument();
      });

      expect(screen.getByText(/Backend Database Unavailable/i)).toBeInTheDocument();
      expect(mockPush).not.toHaveBeenCalled();
      expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
    });

    it("retryVerification clears error and renders content when service recovers", async () => {
      vi.spyOn(apiClient, "getMe").mockRejectedValueOnce(
        new ApiClientError(503, "Backend Down")
      );

      const recoveredUser = { id: "u-rec", email: "recovered@example.com", is_active: true };

      render(
        <AuthProvider>
          <ProtectedRoute>
            <div>Protected Content Recovered</div>
          </ProtectedRoute>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-verification-error")).toBeInTheDocument();
      });

      // Now backend recovers
      vi.spyOn(apiClient, "getMe").mockResolvedValueOnce(recoveredUser);

      fireEvent.click(screen.getByTestId("retry-verification-btn"));

      await waitFor(() => {
        expect(screen.getByText("Protected Content Recovered")).toBeInTheDocument();
      });
      expect(screen.queryByTestId("auth-verification-error")).not.toBeInTheDocument();
    });

    it("logout failure preserves user session and does not redirect to login", async () => {
      const activeUser = { id: "u-active", email: "stay@example.com", is_active: true };
      vi.spyOn(apiClient, "logout").mockRejectedValueOnce(new Error("Network disconnect"));

      let auth: ReturnType<typeof useAuth> | null = null;
      function LogoutProbe() {
        auth = useAuth();
        return <div>{auth.user?.email}</div>;
      }

      render(
        <AuthProvider initialUser={activeUser} initialLoading={false}>
          <LogoutProbe />
        </AuthProvider>
      );

      await expect(auth!.logout()).rejects.toThrow("Network disconnect");

      // User session must remain active
      expect(auth!.user).toEqual(activeUser);
      expect(mockPush).not.toHaveBeenCalled();
    });

    it("login rejects open redirect attempts to external protocols or domains", async () => {
      mockSearchParams = new URLSearchParams("redirect=//evil.com/phish");
      vi.spyOn(apiClient, "login").mockResolvedValueOnce({
        user: { id: "u-1", email: "user@example.com", is_active: true },
      });

      render(
        <AuthProvider initialUser={null} initialLoading={false}>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "user@example.com" } });
      fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "Secret123!" } });
      fireEvent.click(screen.getByRole("button", { name: /^Sign In$/i }));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/captures");
      });
      expect(mockPush).not.toHaveBeenCalledWith("//evil.com/phish");
    });

    it("login preserves safe same-origin path with search query", async () => {
      mockSearchParams = new URLSearchParams("redirect=" + encodeURIComponent("/search?q=test&filter=all"));
      vi.spyOn(apiClient, "login").mockResolvedValueOnce({
        user: { id: "u-1", email: "user@example.com", is_active: true },
      });

      render(
        <AuthProvider initialUser={null} initialLoading={false}>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "user@example.com" } });
      fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "Secret123!" } });
      fireEvent.click(screen.getByRole("button", { name: /^Sign In$/i }));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/search?q=test&filter=all");
      });
    });

    it("register handles auto-login failure separately from account creation", async () => {
      vi.spyOn(apiClient, "register").mockResolvedValueOnce({
        id: "u-reg",
        email: "newuser@example.com",
        is_active: true,
      });
      vi.spyOn(apiClient, "login").mockRejectedValueOnce(
        new ApiClientError(500, "Auto-login failed after registration")
      );

      render(
        <AuthProvider initialUser={null} initialLoading={false}>
          <RegisterPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "newuser@example.com" } });
      fireEvent.change(screen.getByLabelText(/^Password/i), { target: { value: "Password123!" } });
      fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "Password123!" } });
      fireEvent.click(screen.getByRole("button", { name: /Create Account/i }));

      await waitFor(() => {
        expect(screen.getByText(/account has been created successfully/i)).toBeInTheDocument();
        expect(screen.getByTestId("signin-after-register-btn")).toBeInTheDocument();
      });
    });

    it("login prevents duplicate concurrent submissions", async () => {
      let resolveLogin: (val: any) => void = () => {};
      const loginPromise = new Promise((resolve) => {
        resolveLogin = resolve;
      });
      const loginSpy = vi.spyOn(apiClient, "login").mockReturnValue(loginPromise as any);

      render(
        <AuthProvider initialUser={null} initialLoading={false}>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "user@example.com" } });
      fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "Secret123!" } });

      const submitBtn = screen.getByRole("button", { name: /^Sign In$/i });
      fireEvent.click(submitBtn);
      fireEvent.click(submitBtn);
      fireEvent.click(submitBtn);

      expect(loginSpy).toHaveBeenCalledTimes(1);

      resolveLogin({ user: { id: "u-1", email: "user@example.com", is_active: true } });
    });
  });
});
