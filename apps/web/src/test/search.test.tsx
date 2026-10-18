import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import SearchPage from "@/app/search/page";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { SearchResponse } from "@/types/api";

const mockRouterPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => mockSearchParams,
}));

describe("Search Experience & UX (Tests 20-26, 31)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockRouterPush.mockReset();
    mockSearchParams = new URLSearchParams();
  });

  // 20. Search success
  it("20. executes search query and displays ranked capture result cards", async () => {
    const mockSearchResponse: SearchResponse = {
      query: "fastapi async",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-search-1",
          title: "FastAPI Async Tutorial",
          original_url: "https://fastapi.tiangolo.com/async",
          source_type: "url",
          best_score: 0.85,
          best_lexical_score: 0.8,
          best_semantic_score: 0.9,
          matching_chunks: [
            {
              chunk_id: "chunk-s-1",
              chunk_index: 0,
              content_excerpt: "FastAPI has full native support for async def endpoints...",
              score: 0.85,
              lexical_score: 0.8,
              semantic_score: 0.9,
            },
          ],
        },
      ],
    };

    const searchSpy = vi.spyOn(apiClient, "search").mockResolvedValue(mockSearchResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    const submitBtn = screen.getByTestId("search-submit-btn");

    fireEvent.change(searchInput, { target: { value: "fastapi async" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ q: "fastapi async", limit: 20 })
      );
      expect(screen.getByText("FastAPI Async Tutorial")).toBeInTheDocument();
      expect(screen.getByText("https://fastapi.tiangolo.com/async")).toBeInTheDocument();
      expect(screen.getByText(/native support for async def endpoints/i)).toBeInTheDocument();
    });
  });

  // 21. Empty results
  it("21. displays friendly no-results message when query matches zero captures", async () => {
    const emptyResponse: SearchResponse = {
      query: "nonexistent keyword xyz",
      total: 0,
      limit: 20,
      degraded: false,
      results: [],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(emptyResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "nonexistent keyword xyz" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(screen.getByText("No matching captures found")).toBeInTheDocument();
      expect(screen.getByText(/Try different keywords or conceptual terms/i)).toBeInTheDocument();
    });
  });

  // 22. Search API failure
  it("22. displays error message on API failure with retry option", async () => {
    vi.spyOn(apiClient, "search").mockRejectedValue(
      new ApiClientError(500, "Database search timeout occurred.")
    );

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "database query" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(screen.getByText("Database search timeout occurred.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
    });
  });

  // 23. Empty query handling
  it("23. ignores empty or whitespace-only search submissions", async () => {
    const searchSpy = vi.spyOn(apiClient, "search");

    render(<SearchPage />);

    const submitBtn = screen.getByTestId("search-submit-btn");
    expect(submitBtn).toBeDisabled();

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "    " } });

    expect(submitBtn).toBeDisabled();
    fireEvent.click(submitBtn);

    expect(searchSpy).not.toHaveBeenCalled();
  });

  // 24. Result navigation
  it("24. search result cards link directly to capture detail", async () => {
    const mockResponse: SearchResponse = {
      query: "python",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-python-999",
          title: "Python 3.12 Release Notes",
          original_url: null,
          source_type: "text",
          best_score: 0.92,
          best_lexical_score: 0.9,
          best_semantic_score: 0.94,
          matching_chunks: [],
        },
      ],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(mockResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "python" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      const inspectLinks = screen.getAllByRole("link", { name: /Inspect Capture/i });
      expect(inspectLinks[0]).toHaveAttribute("href", "/captures/cap-python-999");
    });
  });

  // 25. Score display
  it("25. displays hybrid, lexical, and semantic scores accurately", async () => {
    const mockResponse: SearchResponse = {
      query: "scoring test",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-score-1",
          title: "Scoring Target",
          original_url: null,
          source_type: "text",
          best_score: 0.824,
          best_lexical_score: 0.72,
          best_semantic_score: 0.928,
          matching_chunks: [
            {
              chunk_id: "ch-1",
              chunk_index: 0,
              content_excerpt: "Matching excerpt with scoring indicators.",
              score: 0.824,
              lexical_score: 0.72,
              semantic_score: 0.928,
            },
          ],
        },
      ],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(mockResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "scoring test" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(screen.getByText("Relevance: 82%")).toBeInTheDocument();
      expect(screen.getByText("Lexical: 72%")).toBeInTheDocument();
      expect(screen.getByText("Semantic: 93%")).toBeInTheDocument();
    });
  });

  // 26. No embedding/vector leakage
  it("26. ensures search response does not contain or display raw embedding vectors", async () => {
    const mockResponse: SearchResponse = {
      query: "privacy test",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-leak-check",
          title: "Privacy Checking Page",
          original_url: null,
          source_type: "text",
          best_score: 0.9,
          best_lexical_score: null,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(mockResponse);

    const { container } = render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "privacy test" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(screen.getByText("Privacy Checking Page")).toBeInTheDocument();
    });

    // Check rendered HTML does not contain vector representations
    expect(container.innerHTML).not.toContain("0.02458");
    expect(container.innerHTML).not.toContain("embedding");
    expect(container.innerHTML).not.toContain("cosine_distance");
  });

  // 31. Stale search response race condition handling
  it("31. prevents older in-flight search responses from overwriting newer query results", async () => {
    let resolveFirstQuery!: (value: SearchResponse) => void;
    let resolveSecondQuery!: (value: SearchResponse) => void;

    const firstPromise = new Promise<SearchResponse>((resolve) => {
      resolveFirstQuery = resolve;
    });
    const secondPromise = new Promise<SearchResponse>((resolve) => {
      resolveSecondQuery = resolve;
    });

    const searchSpy = vi.spyOn(apiClient, "search");
    searchSpy.mockReturnValueOnce(firstPromise);
    searchSpy.mockReturnValueOnce(secondPromise);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    const submitBtn = screen.getByTestId("search-submit-btn");

    // First search: "first query"
    fireEvent.change(searchInput, { target: { value: "first query" } });
    fireEvent.click(submitBtn);

    // Second search immediately: "second query"
    fireEvent.change(searchInput, { target: { value: "second query" } });
    fireEvent.click(submitBtn);

    // Now resolve the SECOND query first
    resolveSecondQuery({
      query: "second query",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-second",
          title: "Newer Second Result",
          original_url: null,
          source_type: "text",
          best_score: 0.99,
          best_lexical_score: null,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    });

    await waitFor(() => {
      expect(screen.getByText("Newer Second Result")).toBeInTheDocument();
    });

    // Now resolve the FIRST (older) query afterwards
    resolveFirstQuery({
      query: "first query",
      total: 1,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-first",
          title: "Older First Result (Stale)",
          original_url: null,
          source_type: "text",
          best_score: 0.5,
          best_lexical_score: null,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    });

    // Verify older response did NOT overwrite the newer result
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("Newer Second Result")).toBeInTheDocument();
    expect(screen.queryByText("Older First Result (Stale)")).not.toBeInTheDocument();
  });

  // Stage 16: Mixed results rendering (captures + GitHub activities)
  it("Stage 16: renders mixed results with captures and GitHub activity metadata", async () => {
    const mockUnifiedResponse: SearchResponse = {
      query: "auth refactor",
      total: 2,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "cap-note-1",
          title: "Auth Refactor Architectural Notes",
          original_url: null,
          source_type: "text",
          result_kind: "capture",
          best_score: 0.95,
          best_lexical_score: 0.9,
          best_semantic_score: 1.0,
          matching_chunks: [
            {
              chunk_id: "chunk-1",
              chunk_index: 0,
              content_excerpt: "We decided to decouple token storage from sessions...",
              score: 0.95,
              lexical_score: 0.9,
              semantic_score: 1.0,
            },
          ],
        },
        {
          capture_id: "gh-pr-101",
          title: "PR #42: Refactor OAuth token storage",
          original_url: "https://github.com/octocat/Lens/pull/42",
          source_type: "pull_request",
          result_kind: "github_activity",
          activity_type: "pull_request",
          repository_name: "octocat/Lens",
          author_login: "octocat",
          state: "merged",
          external_id: "42",
          best_score: 0.88,
          best_lexical_score: 0.88,
          best_semantic_score: null,
          matching_chunks: [
            {
              chunk_id: "chunk-gh-1",
              chunk_index: 0,
              content_excerpt: "Closes issue #39 by migrating to encrypted token metadata.",
              score: 0.88,
              lexical_score: 0.88,
              semantic_score: null,
            },
          ],
        },
      ],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(mockUnifiedResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "auth refactor" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      // Capture item rendered with inspect capture link
      expect(screen.getByText("Auth Refactor Architectural Notes")).toBeInTheDocument();
      const captureInspectLink = screen.getByRole("link", { name: /Inspect Capture/i });
      expect(captureInspectLink).toHaveAttribute("href", "/captures/cap-note-1");

      // GitHub activity item rendered with GitHub metadata and external link
      expect(screen.getByText("PR #42: Refactor OAuth token storage")).toBeInTheDocument();
      expect(screen.getByText("octocat/Lens")).toBeInTheDocument();
      expect(screen.getByText("@octocat")).toBeInTheDocument();
      expect(screen.getByText("MERGED")).toBeInTheDocument();
      const ghLink = screen.getByTestId("inspect-github-gh-pr-101");
      expect(ghLink).toHaveAttribute("href", "https://github.com/octocat/Lens/pull/42");
      expect(ghLink).toHaveAttribute("target", "_blank");
    });
  });

  // Stage 16: Source filter selection
  it("Stage 16: clicking source filter pill triggers search with source_type parameter", async () => {
    const searchSpy = vi.spyOn(apiClient, "search").mockResolvedValue({
      query: "redis pool",
      total: 1,
      limit: 20,
      degraded: false,
      source_filter: "github",
      results: [
        {
          capture_id: "gh-issue-5",
          title: "Issue #5: Redis connection pooling error",
          original_url: "https://github.com/octocat/Lens/issues/5",
          source_type: "issue",
          result_kind: "github_activity",
          activity_type: "issue",
          repository_name: "octocat/Lens",
          author_login: "monalisa",
          state: "open",
          external_id: "5",
          best_score: 0.91,
          best_lexical_score: 0.91,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    });

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "redis pool" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ q: "redis pool", limit: 20 })
      );
    });

    // Now click the GitHub filter pill
    const githubFilterBtn = screen.getByTestId("filter-btn-github");
    fireEvent.click(githubFilterBtn);

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ q: "redis pool", source_type: "github" })
      );
    });
  });

  // Stage 16.1 Finding E: Accessible filter button aria-pressed
  it("Stage 16.1 Finding E: filter buttons expose aria-pressed for assistive technologies", async () => {
    render(<SearchPage />);

    const allBtn = screen.getByTestId("filter-btn-all");
    const githubBtn = screen.getByTestId("filter-btn-github");
    const notesBtn = screen.getByTestId("filter-btn-text");

    expect(allBtn).toHaveAttribute("aria-pressed", "true");
    expect(githubBtn).toHaveAttribute("aria-pressed", "false");
    expect(notesBtn).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(githubBtn);

    expect(allBtn).toHaveAttribute("aria-pressed", "false");
    expect(githubBtn).toHaveAttribute("aria-pressed", "true");
    expect(notesBtn).toHaveAttribute("aria-pressed", "false");
  });

  // Stage 16.1 Finding F: Safe web links for GitHub activities (no safe URL -> plain text, not /captures/[id])
  it("Stage 16.1 Finding F: renders plain text title for GitHub activity with missing or unsafe URL", async () => {
    const mockResponse: SearchResponse = {
      query: "unsafe commit",
      total: 2,
      limit: 20,
      degraded: false,
      results: [
        {
          capture_id: "gh-unsafe-1",
          title: "Commit: missing url activity",
          original_url: null,
          source_type: "commit",
          result_kind: "github_activity",
          activity_type: "commit",
          best_score: 0.8,
          best_lexical_score: 0.8,
          best_semantic_score: null,
          matching_chunks: [],
        },
        {
          capture_id: "gh-unsafe-2",
          title: "PR: javascript scheme activity",
          original_url: "javascript:alert(1)",
          source_type: "pull_request",
          result_kind: "github_activity",
          activity_type: "pull_request",
          best_score: 0.75,
          best_lexical_score: 0.75,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    };

    vi.spyOn(apiClient, "search").mockResolvedValue(mockResponse);

    render(<SearchPage />);

    const searchInput = screen.getByPlaceholderText(/Search concepts, code, links/i);
    fireEvent.change(searchInput, { target: { value: "unsafe commit" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(screen.getByText("Commit: missing url activity")).toBeInTheDocument();
      expect(screen.getByText("PR: javascript scheme activity")).toBeInTheDocument();
    });

    // Neither activity should link to /captures/gh-unsafe-1 or /captures/gh-unsafe-2
    expect(screen.queryByRole("link", { name: /Commit: missing url activity/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /PR: javascript scheme activity/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /javascript:alert/i })).not.toBeInTheDocument();
  });

  // Stage 16.1 Finding D: URL search params synchronization and clearing
  it("Stage 16.1 Finding D: URL search params synchronize input and filter, and clearing query clears results", async () => {
    mockSearchParams = new URLSearchParams("q=initial+query&source_type=issue");

    const mockResponse: SearchResponse = {
      query: "initial query",
      total: 1,
      limit: 20,
      degraded: false,
      source_filter: "issue",
      results: [
        {
          capture_id: "gh-issue-10",
          title: "Initial Issue",
          original_url: "https://github.com/octocat/Lens/issues/10",
          source_type: "issue",
          result_kind: "github_activity",
          activity_type: "issue",
          best_score: 0.9,
          best_lexical_score: 0.9,
          best_semantic_score: null,
          matching_chunks: [],
        },
      ],
    };

    const searchSpy = vi.spyOn(apiClient, "search").mockResolvedValue(mockResponse);

    const { rerender } = render(<SearchPage />);

    // Verify initial URL state was synchronized into input and filter
    const input = screen.getByPlaceholderText(/Search concepts, code, links/i) as HTMLInputElement;
    expect(input.value).toBe("initial query");
    expect(screen.getByTestId("filter-btn-issue")).toHaveAttribute("aria-pressed", "true");

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ q: "initial query", source_type: "issue" })
      );
      expect(screen.getByText("Initial Issue")).toBeInTheDocument();
    });

    // Now simulate back/forward navigation that clears query parameters
    mockSearchParams = new URLSearchParams("");
    rerender(<SearchPage />);

    await waitFor(() => {
      expect(input.value).toBe("");
      expect(screen.queryByText("Initial Issue")).not.toBeInTheDocument();
    });
  });
});
