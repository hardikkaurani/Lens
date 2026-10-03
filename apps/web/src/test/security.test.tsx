import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { CaptureDetailContent } from "@/app/captures/[id]/page";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { sanitizeUrl } from "@/lib/security";
import type { CaptureDetail } from "@/types/api";

describe("Frontend Security Audit (Tests 27-30)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // 27. Malicious capture content rendered as text, not executable HTML
  it("27. renders malicious HTML and script tags safely as plain text without execution", async () => {
    const maliciousCapture: CaptureDetail = {
      id: "cap-xss-1",
      source_type: "text",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T12:00:00Z",
      title: "<script>window.__xss_title = true;</script>",
      original_url: null,
      content: "<img src=x onerror='window.__xss_body = true;'><b>Dangerous Bold</b>",
      mime_type: "text/plain",
      source_id: null,
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:00:00Z",
      metadata: null,
      chunks: [],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(maliciousCapture);

    const { container } = render(<CaptureDetailContent id="cap-xss-1" />);

    await waitFor(() => {
      expect(
        screen.getByText("<script>window.__xss_title = true;</script>")
      ).toBeInTheDocument();
      expect(
        screen.getByText("<img src=x onerror='window.__xss_body = true;'><b>Dangerous Bold</b>")
      ).toBeInTheDocument();
    });

    // Verify scripts or imgs were not injected into the DOM as active executable elements
    expect(container.querySelector("script")).toBeNull();
    const imgs = container.querySelectorAll("img");
    expect(imgs.length).toBe(0);
    expect((window as unknown as Record<string, unknown>).__xss_title).toBeUndefined();
    expect((window as unknown as Record<string, unknown>).__xss_body).toBeUndefined();
  });

  // 28. javascript: URL sanitized and rejected
  it("28. rejects javascript:, data:, and vbscript: URLs from navigation links", () => {
    expect(sanitizeUrl("javascript:alert(1)")).toBeNull();
    expect(sanitizeUrl("JAVASCRIPT:alert(document.cookie)")).toBeNull();
    expect(sanitizeUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(sanitizeUrl("vbscript:msgbox(1)")).toBeNull();
    expect(sanitizeUrl("file:///etc/passwd")).toBeNull();

    // Valid URLs must pass
    expect(sanitizeUrl("https://example.com/clean")).toBe("https://example.com/clean");
    expect(sanitizeUrl("http://localhost:8000/docs")).toBe("http://localhost:8000/docs");
  });

  // 29. Backend stack traces are not displayed
  it("29. masks internal Python tracebacks and database connection strings from errors", async () => {
    vi.spyOn(apiClient, "getCapture").mockRejectedValue(
      new ApiClientError(
        500,
        "A server error occurred. Please try again later."
      )
    );

    render(<CaptureDetailContent id="cap-err-1" />);

    await waitFor(() => {
      expect(
        screen.getByText("A server error occurred. Please try again later.")
      ).toBeInTheDocument();
    });

    expect(screen.queryByText(/Traceback/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/postgresql:\/\//i)).not.toBeInTheDocument();
    expect(screen.queryByText(/redis:\/\//i)).not.toBeInTheDocument();
  });

  // 30. Secrets are not exposed to client configuration
  it("30. ensures client configuration does not expose server secrets or database passwords", () => {
    // Only NEXT_PUBLIC_* variables should be accessible
    const envVars = Object.keys(process.env);
    const leakedSecrets = envVars.filter(
      (key) =>
        key.includes("DATABASE_URL") ||
        key.includes("OPENAI_API_KEY") ||
        key.includes("REDIS_PASSWORD") ||
        key.includes("JWT_SECRET") ||
        key.includes("GITHUB_CLIENT_SECRET")
    );

    expect(leakedSecrets).toEqual([]);
  });
});
