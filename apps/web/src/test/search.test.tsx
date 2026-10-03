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
});
