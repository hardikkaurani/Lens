import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { SettingsContent } from "@/app/settings/page";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { GitHubConnectionStatus, GitHubRepoSyncResponse } from "@/types/api";

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

describe("Stage 14 Web GitHub Repository Discovery & Selection UX (Tests 34-48)", () => {
  const mockConnectedStatus: GitHubConnectionStatus = {
    connected: true,
    github_username: "octocat_repo_owner",
    github_user_id: "445566",
    scope: "read:user,repo",
    connected_at: "2026-10-03T10:00:00Z",
    last_verified_at: "2026-10-03T11:00:00Z",
  };

  const mockRepos = [
    {
      id: "repo-uuid-1",
      github_repository_id: "101",
      name: "lens-core",
      full_name: "octocat/lens-core",
      owner_login: "octocat",
      is_private: false,
      is_fork: false,
      is_archived: false,
      is_disabled: false,
      is_selected: false,
      html_url: "https://github.com/octocat/lens-core",
      description: "LENS core retrieval engine",
      default_branch: "main",
      language: "TypeScript",
      visibility: "public",
      license_name: "MIT",
      sync_status: "synced" as const,
      sync_error: null,
      created_at: "2026-10-03T10:00:00Z",
      updated_at: "2026-10-03T10:00:00Z",
    },
    {
      id: "repo-uuid-2",
      github_repository_id: "102",
      name: "lens-infra",
      full_name: "octocat/lens-infra",
      owner_login: "octocat",
      is_private: true,
      is_fork: true,
      is_archived: true,
      is_disabled: false,
      is_selected: true,
      html_url: "https://github.com/octocat/lens-infra",
      description: "Private archived deployment scripts",
      default_branch: "develop",
      language: "Python",
      visibility: "private",
      license_name: "Apache-2.0",
      sync_status: "synced" as const,
      sync_error: null,
      created_at: "2026-10-03T10:00:00Z",
      updated_at: "2026-10-03T10:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  // 34. connected GitHub state displays repositories section
  it("34. renders repositories section when GitHub is connected", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repositories-section")).toBeInTheDocument();
    });
    expect(screen.getByText("Discovered Repositories")).toBeInTheDocument();
  });

  // 35. repository sync button renders and triggers sync API
  it("35. renders sync button and calls sync API on click", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const syncSpy = vi.spyOn(apiClient, "syncGitHubRepositories").mockResolvedValue({
      status: "completed",
      synced_count: 2,
      total: 2,
      message: "Sync success",
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-repos-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("sync-repos-btn"));

    await waitFor(() => {
      expect(syncSpy).toHaveBeenCalledTimes(1);
    });
  });

  // 36. loading state displays loading skeleton
  it("36. displays repository loading skeleton while fetching", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockReturnValue(new Promise(() => {}));

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repos-loading")).toBeInTheDocument();
    });
  });

  // 37. repository list renders discovered repositories
  it("37. renders list of discovered repositories with full names and links", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-list")).toBeInTheDocument();
      expect(screen.getByTestId("repo-name-repo-uuid-1")).toHaveTextContent("octocat/lens-core");
      expect(screen.getByTestId("repo-name-repo-uuid-2")).toHaveTextContent("octocat/lens-infra");
    });
  });

  // 38. private/public display correctly shows badges
  it("38. correctly renders Public and Private badges", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      const publicBadge = screen.getByText("Public");
      const privateBadge = screen.getByText("Private");
      expect(publicBadge).toBeInTheDocument();
      expect(privateBadge).toBeInTheDocument();
    });
  });

  // 39. archived/fork indicators render badges
  it("39. correctly renders Archived and Fork badges", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByText("Archived")).toBeInTheDocument();
      expect(screen.getByText("Fork")).toBeInTheDocument();
    });
  });

  // 40. safe repository-name rendering prevents script execution
  it("40. renders malicious repository name safely without HTML injection", async () => {
    const maliciousRepos = [
      {
        ...mockRepos[0],
        name: "<script>alert('xss')</script>",
        full_name: "octocat/<script>alert('xss')</script>",
      },
    ];
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: maliciousRepos,
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      const repoNameEl = screen.getByTestId("repo-name-repo-uuid-1");
      expect(repoNameEl.textContent).toBe("octocat/<script>alert('xss')</script>");
    });
    expect(document.querySelector("script[src]")).toBeNull();
  });

  // 41. safe description rendering escapes dangerous payloads
  it("41. renders dangerous repository description safely as plain text", async () => {
    const maliciousDescRepos = [
      {
        ...mockRepos[0],
        description: "<img src=x onerror=alert('xss')>",
      },
    ];
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: maliciousDescRepos,
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByText("<img src=x onerror=alert('xss')>")).toBeInTheDocument();
    });
    expect(document.querySelector("img[src='x']")).toBeNull();
  });

  // 42. empty repository state displays clean message
  it("42. renders empty state when no repositories have been discovered", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-empty-state")).toBeInTheDocument();
      expect(screen.getByText(/no repositories discovered yet/i)).toBeInTheDocument();
    });
  });

  // 43. API error handling displays safe error message
  it("43. displays clean error banner when repository fetch fails", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockRejectedValue(
      new Error("Database connection dropped")
    );

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-error-message")).toBeInTheDocument();
    });
  });

  // 44. rate-limit error handling displays rate limit alert on 429
  it("44. displays rate limit error message when sync API returns 429", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const error429 = new ApiClientError(429, "Rate limit exceeded");
    vi.spyOn(apiClient, "syncGitHubRepositories").mockRejectedValue(error429);

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-repos-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("sync-repos-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("repo-error-message")).toBeInTheDocument();
      expect(screen.getByText(/rate limit/i)).toBeInTheDocument();
    });
  });

  // 45. sync action cannot double-submit while sync is in flight
  it("45. disables sync button while synchronization is in flight", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    let resolveSync: (value: GitHubRepoSyncResponse) => void = () => {};
    const syncPromise = new Promise<GitHubRepoSyncResponse>((resolve) => {
      resolveSync = resolve;
    });
    const syncSpy = vi.spyOn(apiClient, "syncGitHubRepositories").mockReturnValue(syncPromise);

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-repos-btn")).toBeInTheDocument();
    });

    const syncBtn = screen.getByTestId("sync-repos-btn");
    fireEvent.click(syncBtn);
    fireEvent.click(syncBtn);

    expect(syncSpy).toHaveBeenCalledTimes(1);
    expect(syncBtn).toBeDisabled();

    // Resolve in-flight request
    resolveSync({ status: "completed", synced_count: 0, total: 0, message: "Done" });
    await waitFor(() => {
      expect(syncBtn).not.toBeDisabled();
    });
  });

  // 46. no token rendered in repository DOM
  it("46. verifies no token or secret is leaked in repository section DOM", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });

    const { container } = render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repositories-section")).toBeInTheDocument();
    });

    const html = container.innerHTML.toLowerCase();
    expect(html).not.toContain("bearer");
    expect(html).not.toContain("gho_");
    expect(html).not.toContain("client_secret");
  });

  // 47. repository list search/filter behavior
  it("47. filters repository list client-side based on search input", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-name-repo-uuid-1")).toBeInTheDocument();
      expect(screen.getByTestId("repo-name-repo-uuid-2")).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId("repo-search-input");
    fireEvent.change(searchInput, { target: { value: "core" } });

    await waitFor(() => {
      expect(screen.getByTestId("repo-name-repo-uuid-1")).toBeInTheDocument();
      expect(screen.queryByTestId("repo-name-repo-uuid-2")).toBeNull();
    });
  });

  // 48. selection toggle calls update selection API
  it("48. toggling repository checkbox calls update selection API", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(mockConnectedStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: mockRepos,
      total: 2,
      limit: 50,
      offset: 0,
    });
    const updateSpy = vi.spyOn(apiClient, "updateGitHubRepositorySelection").mockResolvedValue({
      ...mockRepos[0],
      is_selected: true,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-checkbox-repo-uuid-1")).toBeInTheDocument();
    });

    const checkbox = screen.getByTestId("repo-checkbox-repo-uuid-1");
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("repo-uuid-1", true);
    });
  });

  // 49. missing required scope displays warning banner and reconnect action
  it("49. displays warning banner and reconnect action when connection lacks repository scope", async () => {
    const insufficientScopeStatus: GitHubConnectionStatus = {
      connected: true,
      github_username: "legacy_user",
      github_user_id: "654321",
      scope: "read:user",
      connected_at: "2026-10-01T10:00:00Z",
      last_verified_at: "2026-10-01T10:00:00Z",
      has_required_scope: false,
      missing_scope_reason: "Your GitHub connection is missing repository permissions (repo or public_repo scope). Please reconnect your account.",
    };
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue(insufficientScopeStatus);
    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("missing-scope-warning")).toBeInTheDocument();
    });

    expect(screen.getByTestId("missing-scope-warning")).toHaveTextContent("Repository Discovery Permission Required");
    expect(screen.getByTestId("missing-scope-warning")).toHaveTextContent("missing repository permissions");
    const reconnectBtn = screen.getByTestId("reconnect-github-btn");
    expect(reconnectBtn).toBeInTheDocument();
    expect(reconnectBtn.getAttribute("href")).toContain("/integrations/github/connect");
  });

  // 50. disconnected state accurately discloses repo's full GitHub access
  it("50. accurately discloses repo scope grants full read and write access", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: false,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("github-disconnected-card")).toBeInTheDocument();
    });

    const card = screen.getByTestId("github-disconnected-card");
    expect(card).toHaveTextContent("read:user, repo");
    expect(card).toHaveTextContent("full read and write access");
    expect(card).toHaveTextContent("public and private repositories");
    expect(card).not.toHaveTextContent("No code modification or write permissions are requested");
  });

  // -------------------------------------------------------------
  // STAGE 15: GitHub Activity Ingestion UX (Tests 51-61)
  // -------------------------------------------------------------

  // 51. activity sync button disabled when no repositories are selected
  it("51. activity sync button is disabled when no repositories are selected", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-1",
          github_repository_id: "101",
          name: "repo-one",
          full_name: "octocat/repo-one",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: false,
          sync_status: "synced" as const,
          sync_error: null,
          html_url: "https://github.com/octocat/repo-one",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-activities-btn")).toBeInTheDocument();
    });

    const syncActivitiesBtn = screen.getByTestId("sync-activities-btn");
    expect(syncActivitiesBtn).toBeDisabled();
    expect(syncActivitiesBtn).toHaveTextContent("Sync Activities (0)");
  });

  // 52. activity sync button triggers syncGitHubActivities with selected repository IDs
  it("52. triggers syncGitHubActivities with selected repository IDs", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-1",
          github_repository_id: "101",
          name: "repo-one",
          full_name: "octocat/repo-one",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: true,
          sync_status: "synced" as const,
          sync_error: null,
          html_url: "https://github.com/octocat/repo-one",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    const syncSpy = vi.spyOn(apiClient, "syncGitHubActivities").mockResolvedValue({
      status: "enqueued",
      synced_repositories: 1,
      synced_activities: 0,
      message: "Activity synchronization job enqueued in background worker.",
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-activities-btn")).toHaveTextContent("Sync Activities (1)");
    });

    const syncActivitiesBtn = screen.getByTestId("sync-activities-btn");
    expect(syncActivitiesBtn).not.toBeDisabled();

    fireEvent.click(syncActivitiesBtn);

    await waitFor(() => {
      expect(syncSpy).toHaveBeenCalledWith({ repository_ids: ["repo-1"], async_sync: true });
    });

    await waitFor(() => {
      expect(screen.getByTestId("settings-notification")).toHaveTextContent(
        "Activity synchronization job enqueued in background worker."
      );
    });
  });

  // 53. handles already_syncing status correctly
  it("53. displays already in progress notification when activity sync is already active", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-1",
          github_repository_id: "101",
          name: "repo-one",
          full_name: "octocat/repo-one",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: true,
          sync_status: "synced" as const,
          sync_error: null,
          html_url: "https://github.com/octocat/repo-one",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    vi.spyOn(apiClient, "syncGitHubActivities").mockResolvedValue({
      status: "already_syncing",
      synced_repositories: 0,
      synced_activities: 0,
      message: "Activity synchronization is already in progress for this repository.",
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-activities-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("sync-activities-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("settings-notification")).toHaveTextContent(
        "Activity synchronization is already in progress"
      );
    });
  });

  // 54. renders activity sync status badges and counts on repository item
  it("54. renders activity sync status badge and metadata counts on selected repository", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-1",
          github_repository_id: "101",
          name: "repo-one",
          full_name: "octocat/repo-one",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: true,
          sync_status: "synced" as const,
          sync_error: null,
          activity_sync_status: "synced",
          activity_sync_metadata: {
            categories: {
              pull_requests: { status: "synced", count: 12, last_synced_at: "2026-10-03T12:00:00Z", error: null },
              issues: { status: "synced", count: 4, last_synced_at: "2026-10-03T12:00:00Z", error: null },
              commits: { status: "synced", count: 45, last_synced_at: "2026-10-03T12:00:00Z", error: null },
              reviews: { status: "synced", count: 8, last_synced_at: "2026-10-03T12:00:00Z", error: null },
            },
          },
          activity_last_synced_at: "2026-10-03T12:00:00Z",
          html_url: "https://github.com/octocat/repo-one",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-activity-section-repo-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("activity-status-repo-1")).toHaveTextContent("Synced");
    const countsEl = screen.getByTestId("repo-counts-repo-1");
    expect(countsEl).toHaveTextContent("pull_requests: 12");
    expect(countsEl).toHaveTextContent("issues: 4");
    expect(countsEl).toHaveTextContent("commits: 45");
    expect(countsEl).toHaveTextContent("reviews: 8");
    expect(screen.getByTestId("repo-activity-synced-at-repo-1")).toBeInTheDocument();
  });

  // 55. displays repository error and per-repository retry action
  it("55. displays error and allows retrying sync for a specific failed repository", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-fail",
          github_repository_id: "202",
          name: "repo-fail",
          full_name: "octocat/repo-fail",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: true,
          sync_status: "synced" as const,
          sync_error: null,
          activity_sync_status: "failed",
          activity_sync_error: "GitHub API returned 502 Bad Gateway",
          html_url: "https://github.com/octocat/repo-fail",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    const syncSpy = vi.spyOn(apiClient, "syncGitHubActivities").mockResolvedValue({
      status: "enqueued",
      synced_repositories: 1,
      synced_activities: 0,
      message: "Activity synchronization job enqueued in background worker.",
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("repo-activity-error-repo-fail")).toBeInTheDocument();
    });

    expect(screen.getByTestId("activity-status-repo-fail")).toHaveTextContent("Sync Failed");
    expect(screen.getByTestId("repo-activity-error-repo-fail")).toHaveTextContent(
      "GitHub API returned 502 Bad Gateway"
    );

    const retryBtn = screen.getByTestId("retry-repo-sync-repo-fail");
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(syncSpy).toHaveBeenCalledWith({ repository_ids: ["repo-fail"], async_sync: true });
    });
  });

  // 56. displays rate limit error message when activity sync is rate limited
  it("56. displays sanitized rate limit message when API responds with 429", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [
        {
          id: "repo-1",
          github_repository_id: "101",
          name: "repo-one",
          full_name: "octocat/repo-one",
          owner_login: "octocat",
          is_private: false,
          is_fork: false,
          is_archived: false,
          is_disabled: false,
          is_selected: true,
          sync_status: "synced" as const,
          sync_error: null,
          html_url: "https://github.com/octocat/repo-one",
          created_at: "2026-10-03T10:00:00Z",
          updated_at: "2026-10-03T10:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    vi.spyOn(apiClient, "syncGitHubActivities").mockRejectedValue(
      new ApiClientError(429, "Rate limit exceeded")
    );

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("sync-activities-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("sync-activities-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("activity-error-message")).toBeInTheDocument();
    });

    expect(screen.getByTestId("activity-error-message")).toHaveTextContent(
      "GitHub API rate limit exceeded. Please try again later."
    );
  });

  // 57. toggles activity preview drawer and displays ingested activities
  it("57. opens ingested activity drawer and renders activity items", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    const getActivitiesSpy = vi.spyOn(apiClient, "getGitHubActivities").mockResolvedValue({
      items: [
        {
          id: "act-1",
          repository_id: "repo-1",
          activity_type: "pull_request",
          external_id: "42",
          title: "Add feature X",
          body: "Implements feature X",
          html_url: "https://github.com/octocat/repo/pull/42",
          author_login: "octocat",
          state: "open",
          source_created_at: "2026-10-03T11:00:00Z",
          source_updated_at: "2026-10-03T11:00:00Z",
          ingested_at: "2026-10-03T12:00:00Z",
          payload: {},
        },
      ],
      total: 1,
      limit: 25,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("toggle-activities-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("toggle-activities-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("activities-drawer")).toBeInTheDocument();
    });

    expect(getActivitiesSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByTestId("activity-item-act-1")).toBeInTheDocument();
      expect(screen.getByTestId("activity-title-act-1")).toHaveTextContent("Add feature X");
    });
  });

  // 58. selecting category filter and then selecting 'All' removes category filter
  it("58. selecting category filter and then selecting 'All' removes category filter", async () => {
    vi.spyOn(apiClient, "getGitHubStatus").mockResolvedValue({
      connected: true,
      github_username: "octocat",
      github_user_id: "123",
      scope: "read:user,repo",
      connected_at: "2026-10-03T10:00:00Z",
      last_verified_at: "2026-10-03T11:00:00Z",
    });

    vi.spyOn(apiClient, "getGitHubRepositories").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    const getActivitiesSpy = vi.spyOn(apiClient, "getGitHubActivities").mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
    });

    render(<SettingsContent />);

    await waitFor(() => {
      expect(screen.getByTestId("toggle-activities-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("toggle-activities-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("activities-drawer")).toBeInTheDocument();
    });

    // Select "issue" filter
    const issueBtn = screen.getByTestId("activity-filter-issue");
    fireEvent.click(issueBtn);

    await waitFor(() => {
      expect(getActivitiesSpy).toHaveBeenLastCalledWith({ activity_type: "issue", limit: 25 });
    });

    // Select "All" filter
    const allBtn = screen.getByTestId("activity-filter-all");
    fireEvent.click(allBtn);

    await waitFor(() => {
      expect(getActivitiesSpy).toHaveBeenLastCalledWith({ activity_type: undefined, limit: 25 });
    });
  });
});

