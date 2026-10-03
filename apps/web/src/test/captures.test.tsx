import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import CapturesPage from "@/app/captures/page";
import NewCapturePage from "@/app/captures/new/page";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { Capture, CaptureDetail, CaptureListResponse } from "@/types/api";

const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

describe("Captures Management & Creation (Tests 4-12)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockRouterPush.mockReset();
  });

  // 4. Capture list loading
  it("4. displays loading skeleton while captures are being fetched", () => {
    vi.spyOn(apiClient, "listCaptures").mockReturnValue(new Promise(() => {})); // pending promise
    render(<CapturesPage />);

    expect(screen.getAllByTestId("loading-skeleton").length).toBeGreaterThan(0);
  });

  // 5. Capture list success
  it("5. renders capture list with title, status, and metadata", async () => {
    const mockCaptures: Capture[] = [
      {
        id: "cap-1",
        source_type: "url",
        processing_status: "completed",
        processing_error: null,
        processed_at: "2026-10-02T10:00:00Z",
        title: "FastAPI Documentation",
        original_url: "https://fastapi.tiangolo.com",
        content: null,
        mime_type: "text/html",
        source_id: null,
        created_at: "2026-10-02T10:00:00Z",
        updated_at: "2026-10-02T10:00:00Z",
      },
    ];
    const mockResponse: CaptureListResponse = {
      items: mockCaptures,
      total: 1,
      limit: 15,
      offset: 0,
    };
    vi.spyOn(apiClient, "listCaptures").mockResolvedValue(mockResponse);

    render(<CapturesPage />);

    await waitFor(() => {
      expect(screen.getByText("FastAPI Documentation")).toBeInTheDocument();
      expect(screen.getByText("Ready")).toBeInTheDocument();
      expect(screen.getByText("Web Page")).toBeInTheDocument();
      expect(screen.getByText(/https:\/\/fastapi\.tiangolo\.com/)).toBeInTheDocument();
    });
  });

  // 6. Empty captures state
  it("6. displays friendly empty state when no captures exist", async () => {
    vi.spyOn(apiClient, "listCaptures").mockResolvedValue({
      items: [],
      total: 0,
      limit: 15,
      offset: 0,
    });

    render(<CapturesPage />);

    await waitFor(() => {
      expect(screen.getByText("No captures yet")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Capture your first item/i })).toBeInTheDocument();
    });
  });

  // 7. Capture list error
  it("7. displays error message with retry button on API failure", async () => {
    vi.spyOn(apiClient, "listCaptures").mockRejectedValue(
      new ApiClientError(500, "Unable to load captures from database.")
    );

    render(<CapturesPage />);

    await waitFor(() => {
      expect(screen.getByText("Unable to load captures from database.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
    });
  });

  // 8. URL creation success
  it("8. successfully creates URL capture and navigates to detail page", async () => {
    const createdCapture: CaptureDetail = {
      id: "cap-new-url-123",
      source_type: "url",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "My Saved Article",
      original_url: "https://example.com/article",
      content: null,
      mime_type: null,
      source_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      metadata: null,
      chunks: [],
    };

    const createSpy = vi.spyOn(apiClient, "createCapture").mockResolvedValue(createdCapture);

    render(<NewCapturePage />);

    const urlInput = screen.getByLabelText(/Webpage URL/i);
    const titleInput = screen.getByLabelText(/Optional Title/i);
    const submitBtn = screen.getByTestId("submit-capture-btn");

    fireEvent.change(urlInput, { target: { value: "https://example.com/article" } });
    fireEvent.change(titleInput, { target: { value: "My Saved Article" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith({
        source_type: "url",
        original_url: "https://example.com/article",
        title: "My Saved Article",
      });
      expect(mockRouterPush).toHaveBeenCalledWith("/captures/cap-new-url-123");
    });
  });

  // 9. Text creation success
  it("9. successfully creates Text capture and navigates to detail page", async () => {
    const createdCapture: CaptureDetail = {
      id: "cap-new-text-456",
      source_type: "text",
      processing_status: "completed",
      processing_error: null,
      processed_at: new Date().toISOString(),
      title: "Quick Thought",
      original_url: null,
      content: "Remember to review database connection pooling settings.",
      mime_type: "text/plain",
      source_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      metadata: null,
      chunks: [],
    };

    const createSpy = vi.spyOn(apiClient, "createCapture").mockResolvedValue(createdCapture);

    render(<NewCapturePage />);

    // Switch to Text tab
    const textTabBtn = screen.getByRole("button", { name: /Text \/ Note/i });
    fireEvent.click(textTabBtn);

    const titleInput = screen.getByLabelText(/Title/i);
    const contentInput = screen.getByLabelText(/Content/i);
    const submitBtn = screen.getByTestId("submit-capture-btn");

    fireEvent.change(titleInput, { target: { value: "Quick Thought" } });
    fireEvent.change(contentInput, {
      target: { value: "Remember to review database connection pooling settings." },
    });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith({
        source_type: "text",
        title: "Quick Thought",
        content: "Remember to review database connection pooling settings.",
      });
      expect(mockRouterPush).toHaveBeenCalledWith("/captures/cap-new-text-456");
    });
  });

  // 10. Client validation errors
  it("10. rejects empty URL, invalid scheme, and whitespace-only text client-side", async () => {
    const createSpy = vi.spyOn(apiClient, "createCapture");

    render(<NewCapturePage />);

    // Test empty URL
    const submitBtn = screen.getByTestId("submit-capture-btn");
    fireEvent.click(submitBtn);
    expect(screen.getByText("URL is required.")).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();

    // Test unsupported scheme
    const urlInput = screen.getByLabelText(/Webpage URL/i);
    fireEvent.change(urlInput, { target: { value: "ftp://example.com/file" } });
    fireEvent.click(submitBtn);
    expect(screen.getByText("Only HTTP and HTTPS URLs are supported.")).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();

    // Test text tab whitespace-only
    const textTabBtn = screen.getByRole("button", { name: /Text \/ Note/i });
    fireEvent.click(textTabBtn);

    const contentInput = screen.getByLabelText(/Content/i);
    fireEvent.change(contentInput, { target: { value: "   " } });
    fireEvent.click(submitBtn);
    expect(screen.getByText("Text content is required and cannot be empty.")).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  // 11. API 422 Handling
  it("11. displays specific validation message when backend returns 422", async () => {
    vi.spyOn(apiClient, "createCapture").mockRejectedValue(
      new ApiClientError(422, "Validation failed on original_url: Unsupported URL scheme")
    );

    render(<NewCapturePage />);

    const urlInput = screen.getByLabelText(/Webpage URL/i);
    fireEvent.change(urlInput, { target: { value: "https://example.com" } });
    fireEvent.click(screen.getByTestId("submit-capture-btn"));

    await waitFor(() => {
      expect(
        screen.getByText("Validation failed on original_url: Unsupported URL scheme")
      ).toBeInTheDocument();
    });
  });

  // 12. API failure handling
  it("12. handles general API failure gracefully without crashing", async () => {
    vi.spyOn(apiClient, "createCapture").mockRejectedValue(
      new ApiClientError(500, "Internal database error occurred.")
    );

    render(<NewCapturePage />);

    const urlInput = screen.getByLabelText(/Webpage URL/i);
    fireEvent.change(urlInput, { target: { value: "https://example.com/page" } });
    fireEvent.click(screen.getByTestId("submit-capture-btn"));

    await waitFor(() => {
      expect(screen.getByText("Internal database error occurred.")).toBeInTheDocument();
    });
  });
});
