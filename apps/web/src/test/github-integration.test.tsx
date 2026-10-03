import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { SettingsContent } from "@/app/settings/page";
import { apiClient } from "@/lib/api-client";
import type { GitHubConnectionStatus } from "@/types/api";

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/settings",
}));

describe("Stage 13 Web GitHub Integration UX (Tests 29-37)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  // 29. disconnected UI renders "Connect GitHub"
  it("29. renders disconnected state with Connect GitHub action", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: false,
    });

    render(<SettingsContent />);

    expect(screen.getByTestId("settings-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("github-disconnected-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("status-badge-disconnected")).toHaveTextContent("Not Connected");
    const connectBtn = screen.getByTestId("connect-github-btn");
    expect(connectBtn).toBeInTheDocument();
    expect(connectBtn).toHaveTextContent("Connect GitHub");
  });

  // 30. connect action navigates to backend connect endpoint
  it("30. connect button links to backend connect endpoint without constructing client-side OAuth URL", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: false,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("connect-github-btn")).toBeInTheDocument();
    });

    const connectBtn = screen.getByTestId("connect-github-btn");
    const href = connectBtn.getAttribute("href");
    expect(href).toContain("/integrations/github/connect");
    // Ensure no client secret or client-constructed oauth params are in the button href
    expect(href).not.toContain("client_secret");
    expect(href).not.toContain("github.com/login/oauth/authorize");
  });

  // 31. connected UI renders connected state
  it("31. renders connected state when GitHub account is linked", async () => {
    const mockConnectedStatus: GitHubConnectionStatus = {
      connected: true,
      github_username: "octocat_developer",
      github_user_id: "123456",
      scope: "read:user",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    };
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("github-connected-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("status-badge-connected")).toHaveTextContent("Connected");
    expect(screen.getByTestId("connected-username")).toHaveTextContent("@octocat_developer");
    expect(screen.getByTestId("disconnect-github-btn")).toBeInTheDocument();
  });

  // 32. username safely rendered
  it("32. renders malicious GitHub username safely as text node without HTML injection", async () => {
    const maliciousStatus: GitHubConnectionStatus = {
      connected: true,
      github_username: "<script>alert('xss')</script>octocat",
      github_user_id: "999",
      scope: "read:user",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T10:00:00Z",
    };
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(maliciousStatus);

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("connected-username")).toBeInTheDocument();
    });

    const usernameEl = screen.getByTestId("connected-username");
    expect(usernameEl.textContent).toBe("@<script>alert('xss')</script>octocat");
    // Ensure script tags are not rendered as DOM elements
    expect(document.querySelector("script[src]")).toBeNull();
  });

  // 33. disconnect action calls DELETE and updates UI
  it("33. disconnect button triggers API call and transitions to disconnected state", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const disconnectSpy = vi.spyOn(apiClient, "disconnectGitHub").mockResolvedValue({
      status: "disconnected",
      message: "Disconnected",
    });

    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "connected_user",
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("disconnect-github-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("disconnect-github-btn"));

    await waitFor(() => {
      expect(disconnectSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("github-disconnected-card")).toBeInTheDocument();
    });
  });

  // 34. loading state renders cleanly
  it("34. displays loading skeleton while fetching connection status", () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockReturnValue(new Promise(() => {}));

    render(<SettingsContent />);

    expect(screen.getByTestId("settings-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("github-connected-card")).toBeNull();
    expect(screen.queryByTestId("github-disconnected-card")).toBeNull();
  });

  // 35. safe error rendering on OAuth error query param
  it("35. displays sanitized notification banner when redirected with error query param", async () => {
    mockSearchParams = new URLSearchParams("github_error=access_denied");
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: false,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("settings-notification")).toBeInTheDocument();
    });

    expect(screen.getByTestId("settings-notification")).toHaveTextContent(
      "GitHub authorization was canceled or denied."
    );
  });

  // 36. token never appears in rendered DOM
  it("36. guarantees no access token or secret exists anywhere in the rendered DOM", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "token_safety_user",
      scope: "read:user",
      connected_at: "2026-10-03T10:00:00Z",
    });

    const { container } = render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("github-connected-card")).toBeInTheDocument();
    });

    const html = container.innerHTML.toLowerCase();
    expect(html).not.toContain("gho_");
    expect(html).not.toContain("ghp_");
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("client_secret");
    expect(html).not.toContain("token_encryption_key");
  });

  // 37. no GitHub OAuth URL constructed client-side
  it("37. ensures client does not construct direct GitHub authorize URLs", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: false,
    });

    const { container } = render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("github-disconnected-card")).toBeInTheDocument();
    });

    // All links/buttons in settings must target our backend API, never raw github.com/login/oauth
    const links = Array.from(container.querySelectorAll("a"));
    for (const link of links) {
      expect(link.getAttribute("href")).not.toContain("https://github.com/login/oauth/authorize");
    }
  });
});
