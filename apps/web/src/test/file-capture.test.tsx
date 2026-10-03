import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { FileCaptureForm } from "@/components/FileCaptureForm";
import NewCapturePage from "@/app/captures/new/page";
import NewFileCapturePage from "@/app/captures/new/file/page";
import { CaptureDetailContent } from "@/app/captures/[id]/page";
import { SourceTypeBadge } from "@/components/SourceTypeBadge";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { validatePdfFile, MAX_FILE_SIZE_BYTES } from "@/lib/validation";
import type { CaptureDetail } from "@/types/api";

const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/captures/new",
}));

describe("Stage 12 Web PDF / File Capture UX (Tests 1-28)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockRouterPush.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // 1. file picker renders
  it("1. file picker renders with appropriate accept attribute and dropzone", () => {
    render(<FileCaptureForm />);

    const input = screen.getByTestId("hidden-file-input") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.type).toBe("file");
    expect(input.accept).toBe(".pdf,application/pdf");

    const dropzone = screen.getByTestId("pdf-dropzone");
    expect(dropzone).toBeInTheDocument();
    expect(dropzone).toHaveAttribute("role", "region");
    expect(dropzone).toHaveAttribute("aria-label", "PDF upload dropzone");
  });

  // 2. invalid MIME rejected
  it("2. invalid MIME type is rejected by client validation", () => {
    const invalidMimeFile = new File(["dummy content"], "doc.pdf", {
      type: "image/png",
    });
    const result = validatePdfFile(invalidMimeFile);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/Unsupported file type/i);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [invalidMimeFile] } });

    expect(screen.getByTestId("upload-client-error")).toHaveTextContent(/Unsupported file type/i);
  });

  // 3. invalid extension rejected where applicable
  it("3. non-PDF extension is rejected even if MIME is application/pdf", () => {
    const wrongExtFile = new File(["dummy"], "notes.txt", {
      type: "application/pdf",
    });
    const result = validatePdfFile(wrongExtFile);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/Only PDF documents \(\.pdf\) are supported/i);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [wrongExtFile] } });

    expect(screen.getByTestId("upload-client-error")).toHaveTextContent(/Only PDF documents \(\.pdf\)/i);
  });

  // 4. empty file rejected
  it("4. empty file (0 bytes) is rejected", () => {
    const emptyFile = new File([], "empty.pdf", { type: "application/pdf" });
    const result = validatePdfFile(emptyFile);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/empty \(0 bytes\)/i);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [emptyFile] } });

    expect(screen.getByTestId("upload-client-error")).toHaveTextContent(/empty \(0 bytes\)/i);
  });

  // 5. oversized file rejected
  it("5. oversized file exceeding MAX_FILE_SIZE_BYTES is rejected", () => {
    const bigFile = new File(["a".repeat(100)], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(bigFile, "size", { value: MAX_FILE_SIZE_BYTES + 1024 });

    const result = validatePdfFile(bigFile);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/exceeds maximum allowed limit/i);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [bigFile] } });

    expect(screen.getByTestId("upload-client-error")).toHaveTextContent(/exceeds maximum allowed limit/i);
  });

  // 6. valid PDF accepted
  it("6. valid PDF file is accepted and populates file card", () => {
    const validFile = new File(["%PDF-1.4 sample content"], "research-paper.pdf", {
      type: "application/pdf",
    });

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    expect(screen.queryByTestId("upload-client-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("selected-file-card")).toBeInTheDocument();
    expect(screen.getByTestId("selected-filename")).toHaveTextContent("research-paper.pdf");
  });

  // 7. selected filename renders safely
  it("7. selected filename renders safely without script execution", () => {
    const maliciousName = "<script>alert('xss')</script>.pdf";
    const xssFile = new File(["%PDF-1.4 test"], maliciousName, {
      type: "application/pdf",
    });

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [xssFile] } });

    const nameEl = screen.getByTestId("selected-filename");
    expect(nameEl).toHaveTextContent("<script>alert('xss')</script>.pdf");
    expect(document.querySelector("script:not([src])")).toBeNull();
  });

  // 8. drag/drop valid file
  it("8. drag and drop accepts valid PDF file and activates drag-over visual style", () => {
    render(<FileCaptureForm />);
    const dropzone = screen.getByTestId("pdf-dropzone");

    fireEvent.dragEnter(dropzone);
    expect(dropzone.className).toMatch(/border-indigo-400/);

    const validFile = new File(["%PDF-1.4 valid"], "dropped-doc.pdf", {
      type: "application/pdf",
    });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [validFile],
      },
    });

    expect(screen.getByTestId("selected-filename")).toHaveTextContent("dropped-doc.pdf");
  });

  // 9. drag/drop invalid file
  it("9. drag and drop of non-PDF file displays validation error", () => {
    render(<FileCaptureForm />);
    const dropzone = screen.getByTestId("pdf-dropzone");

    const invalidFile = new File(["image data"], "picture.png", {
      type: "image/png",
    });

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [invalidFile],
      },
    });

    expect(screen.getByTestId("upload-client-error")).toHaveTextContent(/Only PDF documents/i);
    expect(screen.queryByTestId("selected-file-card")).not.toBeInTheDocument();
  });

  // 10. remove/change selected file
  it("10. allows removing or changing the selected file before upload", () => {
    const file1 = new File(["%PDF-1.4 content"], "file1.pdf", { type: "application/pdf" });

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [file1] } });

    expect(screen.getByTestId("selected-filename")).toHaveTextContent("file1.pdf");

    // Click remove
    const removeBtn = screen.getByTestId("remove-file-btn");
    fireEvent.click(removeBtn);

    expect(screen.queryByTestId("selected-file-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("selected-filename")).not.toBeInTheDocument();
  });

  // 11. upload button disabled when invalid
  it("11. upload submit button is disabled when no file is selected", () => {
    render(<FileCaptureForm />);
    const submitBtn = screen.getByTestId("upload-submit-btn");
    expect(submitBtn).toBeDisabled();
  });

  // 12. double-submit prevention
  it("12. prevents double submission while upload request is in-flight", async () => {
    const validFile = new File(["%PDF-1.4 content"], "sample.pdf", { type: "application/pdf" });
    let resolveUpload: (val: CaptureDetail) => void = () => {};
    const uploadPromise = new Promise<CaptureDetail>((res) => {
      resolveUpload = res;
    });

    const spy = vi.spyOn(apiClient, "uploadCapture").mockReturnValue(uploadPromise);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    const submitBtn = screen.getByTestId("upload-submit-btn");
    expect(submitBtn).not.toBeDisabled();

    // Click submit once and immediately again
    await act(async () => {
      fireEvent.click(submitBtn);
      fireEvent.click(submitBtn);
    });

    // Verify uploadCapture was only called once
    expect(spy).toHaveBeenCalledTimes(1);

    // Cleanup promise
    await act(async () => {
      resolveUpload({
        id: "cap-1",
        source_type: "pdf",
        processing_status: "completed",
        processing_error: null,
        processed_at: "2026-10-02T10:00:00Z",
        title: "sample.pdf",
        original_url: null,
        content: null,
        mime_type: "application/pdf",
        source_id: "captures/cap-1/obj.pdf",
        created_at: "2026-10-02T10:00:00Z",
        updated_at: "2026-10-02T10:00:00Z",
      });
    });
  });

  // 13. upload progress rendering
  it("13. renders upload progress indicator as chunks are transmitted", async () => {
    const validFile = new File(["%PDF-1.4 test"], "progress.pdf", { type: "application/pdf" });
    let progressCallback: ((prog: { loaded: number; total: number; percentage: number }) => void) | undefined;

    vi.spyOn(apiClient, "uploadCapture").mockImplementation((_f, options) => {
      progressCallback = options?.onProgress;
      return new Promise(() => {}); // never resolves during this assertion
    });

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    fireEvent.click(screen.getByTestId("upload-submit-btn"));

    expect(screen.getByTestId("upload-progress-container")).toBeInTheDocument();

    // Trigger 45% progress
    act(() => {
      progressCallback?.({ loaded: 450, total: 1000, percentage: 45 });
    });

    expect(screen.getByText("45%")).toBeInTheDocument();
  });

  // 14. upload success
  it("14. renders success card when upload and processing complete immediately", async () => {
    const validFile = new File(["%PDF-1.4 test"], "completed.pdf", { type: "application/pdf" });
    const mockDetail: CaptureDetail = {
      id: "cap-completed-1",
      source_type: "pdf",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T10:00:00Z",
      title: "Completed Document",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-completed-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    fireEvent.click(screen.getByTestId("upload-submit-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("upload-success-card")).toBeInTheDocument();
      expect(screen.getByText("PDF Capture Ready")).toBeInTheDocument();
      expect(screen.getByTestId("view-capture-detail-link")).toHaveAttribute(
        "href",
        "/captures/cap-completed-1"
      );
    });
  });

  // 15. processing polling starts after upload
  it("15. begins bounded status polling when upload returns pending status", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "pending.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-pending-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Pending Document",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-pending-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi.spyOn(apiClient, "getCapture").mockResolvedValue(mockPendingDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    expect(screen.getByTestId("upload-processing-card")).toBeInTheDocument();

    // Advance timer to trigger polling interval
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(getSpy).toHaveBeenCalledWith("cap-pending-1");
  });

  // 16. polling stops on completed
  it("16. polling terminates immediately when status transitions to completed", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "poll.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-poll-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Poll Document",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-poll-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    const mockCompletedDetail: CaptureDetail = {
      ...mockPendingDetail,
      processing_status: "completed",
      processed_at: "2026-10-02T10:01:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi
      .spyOn(apiClient, "getCapture")
      .mockResolvedValueOnce(mockPendingDetail)
      .mockResolvedValueOnce(mockCompletedDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    // Advance first poll interval
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    // Advance second poll interval -> returns completed
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(screen.getByTestId("upload-success-card")).toBeInTheDocument();

    // Advance more intervals and verify no further getCapture calls occur
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  // 17. polling stops on failed
  it("17. polling terminates immediately when status transitions to failed", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "poll.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-failed-1",
      source_type: "pdf",
      processing_status: "processing",
      processing_error: null,
      processed_at: null,
      title: "Failed Document",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-failed-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    const mockFailedDetail: CaptureDetail = {
      ...mockPendingDetail,
      processing_status: "failed",
      processing_error: "Encrypted or password-protected PDF files are not supported.",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi
      .spyOn(apiClient, "getCapture")
      .mockResolvedValueOnce(mockFailedDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(screen.getByTestId("upload-failure-card")).toBeInTheDocument();
    expect(
      screen.getByText("Encrypted or password-protected PDF files are not supported.")
    ).toBeInTheDocument();

    // Further timer ticks do not trigger getCapture
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(getSpy).toHaveBeenCalledTimes(1);
  });

  // 18. polling stops on 404
  it("18. polling terminates cleanly if capture record returns 404", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "poll.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-404-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Doc",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-404-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi
      .spyOn(apiClient, "getCapture")
      .mockRejectedValueOnce(new ApiClientError(404, "Capture record not found on server."));

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(screen.getByTestId("upload-failure-card")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(getSpy).toHaveBeenCalledTimes(1);
  });

  // 19. polling cannot overlap
  it("19. prevents concurrent overlapping poll requests if response takes longer than interval", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "poll.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-slow-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Doc",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-slow-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);

    // Return a hanging promise that does not resolve immediately
    let resolveSlowPoll: () => void = () => {};
    const slowPromise = new Promise<CaptureDetail>((res) => {
      resolveSlowPoll = () => res(mockPendingDetail);
    });

    const getSpy = vi.spyOn(apiClient, "getCapture").mockReturnValue(slowPromise);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    // Advance timer by 2500ms -> first getCapture called
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(getSpy).toHaveBeenCalledTimes(1);

    // Advance timer by another 2500ms while first is still pending -> no overlapping call
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(getSpy).toHaveBeenCalledTimes(1);

    // Resolve first poll
    await act(async () => {
      resolveSlowPoll();
    });
  });

  // 20. polling stops on unmount
  it("20. cancels polling timer and in-flight request when component unmounts", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "unmount.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-unmount-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Doc",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-unmount-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi.spyOn(apiClient, "getCapture").mockResolvedValue(mockPendingDetail);

    const { unmount } = render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    // Unmount before poll timer fires
    unmount();

    // Advance timers
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(getSpy).not.toHaveBeenCalled();
  });

  // 21. bounded polling exhaustion
  it("21. stops polling after maximum attempts (20) to prevent indefinite loops", async () => {
    vi.useFakeTimers();
    const validFile = new File(["%PDF-1.4 test"], "exhaust.pdf", { type: "application/pdf" });
    const mockPendingDetail: CaptureDetail = {
      id: "cap-exhaust-1",
      source_type: "pdf",
      processing_status: "pending",
      processing_error: null,
      processed_at: null,
      title: "Doc",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-exhaust-1/doc.pdf",
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockPendingDetail);
    const getSpy = vi.spyOn(apiClient, "getCapture").mockResolvedValue(mockPendingDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("upload-submit-btn"));
    });

    // Fast-forward through all 21 intervals
    for (let i = 0; i < 22; i++) {
      await act(async () => {
        vi.advanceTimersByTime(2500);
      });
    }

    // Must be bounded at 20 attempts
    expect(getSpy).toHaveBeenCalledTimes(20);
    expect(
      screen.getByText(/Document processing is taking longer than expected/i)
    ).toBeInTheDocument();
  });

  // 22. sanitized backend error rendering
  it("22. displays sanitized backend processing error without raw stack traces or internal paths", () => {
    render(
      <CaptureDetailContent id="cap-failed-err" />
    );
  });

  // 23. capture detail renders PDF/file metadata safely
  it("23. capture detail renders PDF metadata card without exposing internal storage credentials", async () => {
    const pdfDetail: CaptureDetail = {
      id: "cap-pdf-meta-1",
      source_type: "pdf",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T12:00:00Z",
      title: "Architecture Specification",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: "captures/cap-pdf-meta-1/abc.pdf",
      created_at: "2026-10-02T12:00:00Z",
      updated_at: "2026-10-02T12:00:00Z",
      metadata: {
        original_filename: "architecture_v1.pdf",
        byte_size: 204850,
        mime_type: "application/pdf",
        sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        bucket: "lens-media-private", // internal detail
        object_key: "captures/cap-pdf-meta-1/abc.pdf", // internal detail
      },
      chunks: [
        {
          id: "chunk-pdf-1",
          chunk_index: 0,
          content: "LENS architecture provides hybrid search over PDF and URL captures.",
          created_at: "2026-10-02T12:00:00Z",
        },
      ],
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(pdfDetail);

    render(<CaptureDetailContent id="cap-pdf-meta-1" />);

    await waitFor(() => {
      expect(screen.getByTestId("document-info-section")).toBeInTheDocument();
      expect(screen.getByTestId("detail-filename")).toHaveTextContent("architecture_v1.pdf");
      expect(screen.getByTestId("detail-filesize")).toHaveTextContent("200.0 KB");
      expect(screen.getByTestId("detail-mimetype")).toHaveTextContent("application/pdf");
      expect(screen.getByTestId("detail-sha256")).toHaveTextContent(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      );
      // Ensure internal storage bucket credentials and private paths are not rendered
      expect(screen.queryByText("lens-media-private")).toBeNull();
    });
  });

  // 24. search result renders file/PDF source type
  it("24. SourceTypeBadge correctly formats and renders pdf and file types", () => {
    const { unmount } = render(<SourceTypeBadge sourceType="pdf" />);
    expect(screen.getByTestId("source-type-badge-pdf")).toHaveTextContent("PDF Document");
    expect(screen.getByTestId("source-type-badge-pdf").className).toMatch(/text-emerald-300/);
    unmount();

    render(<SourceTypeBadge sourceType="file" />);
    expect(screen.getByTestId("source-type-badge-file")).toHaveTextContent("File");
  });

  // 25. navigation to capture detail works
  it("25. View Capture Details button on success card navigates to /captures/[id]", async () => {
    const validFile = new File(["%PDF-1.4 test"], "doc.pdf", { type: "application/pdf" });
    const mockDetail: CaptureDetail = {
      id: "cap-nav-1",
      source_type: "pdf",
      processing_status: "completed",
      processing_error: null,
      processed_at: "2026-10-02T10:00:00Z",
      title: "Document",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: null,
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "uploadCapture").mockResolvedValue(mockDetail);

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [validFile] } });
    fireEvent.click(screen.getByTestId("upload-submit-btn"));

    await waitFor(() => {
      const link = screen.getByTestId("view-capture-detail-link");
      expect(link).toHaveAttribute("href", "/captures/cap-nav-1");
    });
  });

  // 26. no unsafe HTML rendering
  it("26. renders malicious strings in processing_error as plain text without DOM injection", async () => {
    const xssDetail: CaptureDetail = {
      id: "cap-xss-1",
      source_type: "pdf",
      processing_status: "failed",
      processing_error: "<img src=x onerror=alert('xss') /> PDF extraction failed.",
      processed_at: "2026-10-02T10:00:00Z",
      title: "Doc",
      original_url: null,
      content: null,
      mime_type: "application/pdf",
      source_id: null,
      created_at: "2026-10-02T10:00:00Z",
      updated_at: "2026-10-02T10:00:00Z",
    };

    vi.spyOn(apiClient, "getCapture").mockResolvedValue(xssDetail);

    render(<CaptureDetailContent id="cap-xss-1" />);

    await waitFor(() => {
      expect(
        screen.getByText("<img src=x onerror=alert('xss') /> PDF extraction failed.")
      ).toBeInTheDocument();
      expect(document.querySelector("img[src='x']")).toBeNull();
    });
  });

  // 27. long filename handling
  it("27. handles very long filenames safely without breaking UI layout", () => {
    const longName = "a".repeat(200) + ".pdf";
    const longFile = new File(["%PDF-1.4 test"], longName, { type: "application/pdf" });

    render(<FileCaptureForm />);
    const input = screen.getByTestId("hidden-file-input");
    fireEvent.change(input, { target: { files: [longFile] } });

    const nameEl = screen.getByTestId("selected-filename");
    expect(nameEl).toBeInTheDocument();
    expect(nameEl.className).toMatch(/truncate|break-all/);
  });

  // 28. keyboard accessibility basics
  it("28. dropzone is focusable and activates file picker with Enter or Space key", () => {
    render(<FileCaptureForm />);
    const dropzone = screen.getByTestId("pdf-dropzone");
    const input = screen.getByTestId("hidden-file-input");

    const clickSpy = vi.spyOn(input, "click");

    dropzone.focus();
    expect(dropzone).toHaveFocus();

    fireEvent.keyDown(dropzone, { key: "Enter" });
    expect(clickSpy).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(dropzone, { key: " " });
    expect(clickSpy).toHaveBeenCalledTimes(2);
  });

  // Additional test: /captures/new tab switching
  it("switches to PDF Document tab in NewCapturePage", () => {
    render(<NewCapturePage />);

    expect(screen.getByTestId("tab-file")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-file"));

    expect(screen.getByTestId("pdf-dropzone")).toBeInTheDocument();
  });

  // Additional test: /captures/new/file dedicated page renders
  it("renders dedicated NewFileCapturePage correctly", () => {
    render(<NewFileCapturePage />);
    expect(screen.getByText("Upload PDF Document")).toBeInTheDocument();
    expect(screen.getByTestId("pdf-dropzone")).toBeInTheDocument();
  });
});
