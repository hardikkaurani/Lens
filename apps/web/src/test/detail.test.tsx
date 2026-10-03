import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { CaptureDetailContent } from "@/app/captures/[id]/page";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { CaptureDetail } from "@/types/api";

describe("Capture Detail Page (Tests 13-19)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // 13. Detail loading state
  it("13. renders loading card skeleton while fetching capture detail", () => {
    vi.spyOn(apiClient, "getCapture").mockReturnValue(new Promise(() => {})); // pending

    render(<CaptureDetailContent id="cap-123" />);

    expect(screen.getAllByTestId("loading-skeleton").length).toBeGreaterThan(0);
  });

  // 14. Detail success
  it("14. renders title, source type, URL, and metadata successfully", async () => {
    const detail: CaptureDetail = {
      id: "cap-123",
      source_type: "url",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T12:00:00Z",
      title: "FastAPI Documentation",
      original_url: "https://fastapi.tiangolo.com",
      content: null,
      mime_type: "text/html",
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:00:00Z",
      metadata: { author: "tiangolo" },
      chunks: [
        {
          id: "chunk-1",
          chunk_index: 0,
          content: "FastAPI is a high-performance web framework for Python.",
          created_at: "2026-10-02T12:00:00Z",
        },
      ],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(detail);

    render(<CaptureDetailContent id="cap-123" />);

    await waitFor(() => {
      expect(screen.getByText("FastAPI Documentation")).toBeInTheDocument();
    });
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Web Page")).toBeInTheDocument();
    expect(screen.getByText(/https:\/\/fastapi\.tiangolo\.com/)).toBeInTheDocument();
    expect(screen.getByText(/FastAPI is a high-performance/i)).toBeInTheDocument();
    expect(screen.getByText(/"author": "tiangolo"/)).toBeInTheDocument();
  });

  // 15. 404 Not Found
  it("15. displays Capture Not Found message when backend returns 404", async () => {
    vi.spyOn(apiClient, "getCapture").mockRejectedValue(
      new ApiClientError(404, "Capture 'cap-missing' not found.")
    );

    render(<CaptureDetailContent id="cap-missing" />);

    await waitFor(() => {
      expect(screen.getByText("Capture Not Found")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Back to Captures/i })).toBeInTheDocument();
    });
  });

  // 16. Failed processing state
  it("16. renders safe backend processing_error message when status is failed", async () => {
    const failedCapture: CaptureDetail = {
      id: "cap-failed-456",
      source_type: "url",
      processing_status: "failed",
      processing_error: "SSRF security policy blocked destination: loopback address is not permitted.",
      processed_at: "2026-10-02T12:01:00Z",
      title: "Blocked Localhost Page",
      original_url: "http://127.0.0.1:8080/admin",
      content: null,
      mime_type: null,
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:01:00Z",
      metadata: null,
      chunks: [],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(failedCapture);

    render(<CaptureDetailContent id="cap-failed-456" />);

    await waitFor(() => {
      expect(screen.getByText("Processing failed")).toBeInTheDocument();
      expect(screen.getByText("Ingestion Pipeline Halted")).toBeInTheDocument();
      expect(
        screen.getByText(/SSRF security policy blocked destination/i)
      ).toBeInTheDocument();
    });
  });

  // 17. Pending processing state
  it("17. displays Queued for Ingestion notice when status is pending", async () => {
    const pendingCapture: CaptureDetail = {
      id: "cap-pending-789",
      source_type: "url",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Pending Capture",
      original_url: "https://example.com/pending",
      content: null,
      mime_type: null,
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:00:00Z",
      metadata: null,
      chunks: [],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(pendingCapture);

    render(<CaptureDetailContent id="cap-pending-789" />);

    await waitFor(() => {
      expect(screen.getByText("Waiting to process")).toBeInTheDocument();
      expect(screen.getByText("Queued for Ingestion")).toBeInTheDocument();
    });
  });

  // 18. Completed processing state
  it("18. displays Ready badge and chunks container when status is completed", async () => {
    const completedCapture: CaptureDetail = {
      id: "cap-done-111",
      source_type: "url",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T12:02:00Z",
      title: "Completed Doc",
      original_url: "https://example.com/doc",
      content: null,
      mime_type: "text/html",
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:02:00Z",
      metadata: null,
      chunks: [
        {
          id: "c1",
          chunk_index: 0,
          content: "First paragraph extracted from doc.",
          created_at: "2026-10-02T12:02:00Z",
        },
        {
          id: "c2",
          chunk_index: 1,
          content: "Second paragraph extracted from doc.",
          created_at: "2026-10-02T12:02:00Z",
        },
      ],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(completedCapture);

    render(<CaptureDetailContent id="cap-done-111" />);

    await waitFor(() => {
      expect(screen.getByText("Ready")).toBeInTheDocument();
      expect(screen.getByText(/Extracted Content Chunks \(2\)/i)).toBeInTheDocument();
      expect(screen.getByText("Chunk #1")).toBeInTheDocument();
      expect(screen.getByText("Chunk #2")).toBeInTheDocument();
    });
  });

  // 19. Missing chunks
  it("19. handles completed capture with zero chunks without errors", async () => {
    const noChunksCapture: CaptureDetail = {
      id: "cap-empty-222",
      source_type: "url",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T12:02:00Z",
      title: "Page With No Chunks",
      original_url: "https://example.com/empty",
      content: null,
      mime_type: "text/html",
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:02:00Z",
      metadata: null,
      chunks: [],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(noChunksCapture);

    render(<CaptureDetailContent id="cap-empty-222" />);

    await waitFor(() => {
      expect(
        screen.getByText("No extracted textual chunks available for this capture.")
      ).toBeInTheDocument();
    });
  });
});
