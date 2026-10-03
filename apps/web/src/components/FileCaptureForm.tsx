"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { formatFileSize } from "@/lib/format";
import { validatePdfFile, MAX_FILE_SIZE_MB } from "@/lib/validation";
import type { CaptureDetail, UploadProgress } from "@/types/api";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorMessage } from "@/components/ErrorMessage";

const MAX_POLL_ATTEMPTS = 20;
const POLL_INTERVAL_MS = 2500;

type UploadPhase = "idle" | "uploading" | "processing" | "completed" | "failed";

export function FileCaptureForm() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState<string>("");
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState<number>(0);
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [createdCapture, setCreatedCapture] = useState<CaptureDetail | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isPollingRef = useRef<boolean>(false);
  const pollAttemptsRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isUploadingRef = useRef<boolean>(false);

  // Stop polling helper
  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    isPollingRef.current = false;
  }, []);

  // Clean up on component unmount
  useEffect(() => {
    return () => {
      stopPolling();
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [stopPolling]);

  // Handle file selection from picker or drag/drop
  const handleSelectFile = (selectedFile: File | null | undefined) => {
    setClientError(null);
    setApiError(null);

    if (!selectedFile) return;

    const validation = validatePdfFile(selectedFile);
    if (!validation.valid) {
      setFile(null);
      setClientError(validation.error);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setFile(selectedFile);
    setClientError(null);
  };

  // Drag and drop event handlers
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only deactivate if leaving the drop container itself
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (phase === "uploading" || phase === "processing") return;

    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles && droppedFiles.length > 0) {
      handleSelectFile(droppedFiles[0]);
    }
  };

  // Keyboard accessibility: trigger file picker with Enter or Space
  const handleKeyDownDropZone = (e: React.KeyboardEvent) => {
    if (phase === "uploading" || phase === "processing") return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInputRef.current?.click();
    }
  };

  // Reset form to select another file
  const handleReset = () => {
    stopPolling();
    isUploadingRef.current = false;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setFile(null);
    setTitle("");
    setPhase("idle");
    setProgress(0);
    setClientError(null);
    setApiError(null);
    setCreatedCapture(null);
    pollAttemptsRef.current = 0;
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Begin background status polling after upload succeeds
  const startPolling = useCallback(
    (captureId: string) => {
      stopPolling();
      pollAttemptsRef.current = 0;

      pollTimerRef.current = setInterval(async () => {
        if (isPollingRef.current) return; // Prevent overlapping requests
        isPollingRef.current = true;
        pollAttemptsRef.current += 1;

        if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
          stopPolling();
          setApiError(
            "Document processing is taking longer than expected. You can inspect the capture details directly."
          );
          return;
        }

        try {
          const detail = await apiClient.getCapture(captureId);
          setCreatedCapture(detail);

          if (detail.processing_status === "completed") {
            stopPolling();
            setPhase("completed");
          } else if (detail.processing_status === "failed") {
            stopPolling();
            setPhase("failed");
            setApiError(
              detail.processing_error ||
                "PDF ingestion failed. The file could not be parsed or contains no extractable text."
            );
          }
        } catch (err: unknown) {
          if (err instanceof ApiClientError && err.status === 404) {
            stopPolling();
            setPhase("failed");
            setApiError("Capture record not found on server.");
          }
          // On network glitch, let next poll interval attempt
        } finally {
          isPollingRef.current = false;
        }
      }, POLL_INTERVAL_MS);
    },
    [stopPolling]
  );

  // Form submit: upload file
  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();

    if (isUploadingRef.current || phase === "uploading" || phase === "processing") {
      return;
    }

    setClientError(null);
    setApiError(null);

    const validation = validatePdfFile(file);
    if (!validation.valid) {
      setClientError(validation.error);
      return;
    }

    if (!file) return;

    if (title.length > 512) {
      setClientError("Title must be 512 characters or fewer.");
      return;
    }

    isUploadingRef.current = true;
    setPhase("uploading");
    setProgress(0);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await apiClient.uploadCapture(file, {
        title: title.trim() || undefined,
        signal: controller.signal,
        onProgress: (prog: UploadProgress) => {
          setProgress(prog.percentage);
        },
      });

      setCreatedCapture(response);
      setProgress(100);

      if (response.processing_status === "completed") {
        setPhase("completed");
      } else if (response.processing_status === "failed") {
        setPhase("failed");
        setApiError(response.processing_error || "PDF ingestion failed.");
      } else {
        // Pending or processing: transition to polling
        setPhase("processing");
        startPolling(response.id);
      }
    } catch (err: unknown) {
      setPhase("idle");
      setProgress(0);

      if (err instanceof ApiClientError) {
        setApiError(err.detail);
      } else {
        setApiError("Could not upload file. Please check your connection and try again.");
      }
    } finally {
      isUploadingRef.current = false;
    }
  };

  const isWorking = phase === "uploading" || phase === "processing";

  return (
    <div className="space-y-6">
      {/* Client Validation Error Banner */}
      {clientError && (
        <div
          role="alert"
          className="p-3.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-200 text-xs flex items-center gap-2"
          data-testid="upload-client-error"
        >
          <svg className="w-4 h-4 shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>{clientError}</span>
        </div>
      )}

      {/* API / Server Error Banner */}
      {apiError && phase !== "failed" && (
        <ErrorMessage message={apiError} onRetry={file ? handleSubmit : undefined} />
      )}

      {/* Success View */}
      {phase === "completed" && createdCapture && (
        <div
          className="lens-card p-6 space-y-4 border-emerald-500/30 bg-emerald-950/10"
          data-testid="upload-success-card"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-bold text-white">PDF Capture Ready</h2>
              <p className="text-xs text-slate-300 mt-0.5">
                The document has been stored, extracted into text, chunked, and embedded into the search index.
              </p>
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-black/30 border border-white/5 space-y-1 text-xs">
            <div className="flex items-center justify-between text-slate-400">
              <span>Title / File:</span>
              <span className="font-semibold text-slate-200 truncate max-w-xs">
                {createdCapture.title || file?.name || "Document"}
              </span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Status:</span>
              <StatusBadge status="completed" />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link
              href={`/captures/${createdCapture.id}`}
              className="lens-button-primary text-xs"
              data-testid="view-capture-detail-link"
            >
              <span>View Capture Details</span>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
            <button
              type="button"
              onClick={handleReset}
              className="lens-button-secondary text-xs"
              data-testid="upload-another-btn"
            >
              Upload Another PDF
            </button>
          </div>
        </div>
      )}

      {/* Processing State View (Post-Upload) */}
      {phase === "processing" && createdCapture && (
        <div
          className="lens-card p-6 space-y-4 border-indigo-500/30 bg-indigo-950/10"
          data-testid="upload-processing-card"
        >
          <div className="flex items-center gap-3">
            <svg className="w-6 h-6 animate-spin text-indigo-400 shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <div>
              <h2 className="text-base font-bold text-white">Ingesting Document</h2>
              <p className="text-xs text-indigo-300/90 mt-0.5">
                PDF successfully uploaded to secure storage. Background worker is extracting text and indexing content...
              </p>
            </div>
          </div>

          {/* Stepper Progress */}
          <div className="grid grid-cols-3 gap-2 pt-2 text-center text-xs">
            <div className="p-2.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-medium">
              ✓ Uploaded
            </div>
            <div className="p-2.5 rounded bg-sky-500/10 border border-sky-500/30 text-sky-200 font-medium animate-pulse">
              Extracting Text...
            </div>
            <div className="p-2.5 rounded bg-slate-800/40 border border-white/5 text-slate-500">
              Indexing & Chunks
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-white/5">
            <span>Tracking status automatically...</span>
            <Link
              href={`/captures/${createdCapture.id}`}
              className="text-indigo-400 hover:text-indigo-300 hover:underline"
            >
              Open detail page →
            </Link>
          </div>
        </div>
      )}

      {/* Failure State View */}
      {phase === "failed" && (
        <div
          className="lens-card p-6 space-y-4 border-rose-500/30 bg-rose-950/10"
          data-testid="upload-failure-card"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-bold text-white">Ingestion Failed</h2>
              <p className="text-xs text-rose-300 mt-0.5">
                The document could not be indexed into searchable chunks.
              </p>
            </div>
          </div>

          {apiError && (
            <div className="p-3.5 rounded-lg bg-black/40 border border-rose-500/20 text-xs text-rose-200 break-words font-mono">
              {apiError}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              type="button"
              onClick={handleReset}
              className="lens-button-primary text-xs"
              data-testid="try-another-file-btn"
            >
              Select Another File
            </button>
            {createdCapture && (
              <Link
                href={`/captures/${createdCapture.id}`}
                className="lens-button-secondary text-xs"
              >
                Inspect Error Details
              </Link>
            )}
          </div>
        </div>
      )}

      {/* Main Upload Form (Shown in idle or uploading state) */}
      {(phase === "idle" || phase === "uploading") && (
        <form onSubmit={handleSubmit} className="lens-card p-6 space-y-5" noValidate>
          {/* Hidden File Input */}
          <input
            ref={fileInputRef}
            id="file-upload-input"
            type="file"
            accept=".pdf,application/pdf"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                handleSelectFile(e.target.files[0]);
              }
            }}
            className="hidden"
            data-testid="hidden-file-input"
            disabled={isWorking}
          />

          {/* Drag & Drop Zone */}
          <div
            role="region"
            aria-label="PDF upload dropzone"
            tabIndex={0}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onKeyDown={handleKeyDownDropZone}
            onClick={() => {
              if (!isWorking) fileInputRef.current?.click();
            }}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
              isDragging
                ? "border-indigo-400 bg-indigo-500/10 shadow-[0_0_20px_rgba(99,102,241,0.25)]"
                : file
                ? "border-emerald-500/40 bg-emerald-500/5 hover:border-emerald-500/60"
                : "border-white/15 bg-white/[0.02] hover:border-indigo-500/40 hover:bg-white/[0.04]"
            }`}
            data-testid="pdf-dropzone"
          >
            <div className="flex flex-col items-center justify-center space-y-3">
              <div
                className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${
                  isDragging
                    ? "bg-indigo-500 text-white shadow-lg"
                    : file
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-slate-800/80 text-slate-400"
                }`}
              >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.75}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
              </div>

              <div className="space-y-1">
                <p className="text-sm font-semibold text-white">
                  {isDragging
                    ? "Drop PDF to upload"
                    : file
                    ? "File ready for upload"
                    : "Click to select or drag and drop a PDF"}
                </p>
                <p className="text-xs text-slate-400">
                  Supported format: <span className="font-mono text-slate-300">.pdf</span> (Max {MAX_FILE_SIZE_MB} MB)
                </p>
              </div>
            </div>
          </div>

          {/* Selected File Details Card */}
          {file && (
            <div
              className="p-4 rounded-xl bg-[#0d121e] border border-white/10 flex items-center justify-between gap-3"
              data-testid="selected-file-card"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                    />
                  </svg>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-white truncate break-all" data-testid="selected-filename">
                    {file.name}
                  </p>
                  <p className="text-[11px] text-slate-400 font-mono mt-0.5">
                    {formatFileSize(file.size)} • PDF Document
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="px-2.5 py-1 text-xs font-medium text-slate-300 hover:text-white rounded bg-slate-800 hover:bg-slate-700 transition-colors"
                  disabled={isWorking}
                  data-testid="change-file-btn"
                >
                  Change
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setFile(null);
                    setClientError(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                  className="p-1 text-slate-400 hover:text-rose-400 rounded transition-colors"
                  aria-label="Remove selected file"
                  disabled={isWorking}
                  data-testid="remove-file-btn"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          )}

          {/* Optional Title Input */}
          <div className="space-y-1.5">
            <label htmlFor="file-title-input" className="block text-xs font-semibold text-slate-300">
              Optional Title
            </label>
            <input
              id="file-title-input"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={file ? file.name : "Custom document title"}
              maxLength={512}
              className="lens-input text-xs"
              disabled={isWorking}
            />
            <p className="text-[11px] text-slate-500">
              Leave blank to use the document filename as the capture title.
            </p>
          </div>

          {/* Upload Progress Bar */}
          {phase === "uploading" && (
            <div className="space-y-2 pt-2" data-testid="upload-progress-container">
              <div className="flex items-center justify-between text-xs font-mono text-slate-300">
                <span>Uploading PDF...</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-500 to-emerald-500 transition-all duration-200"
                  style={{ width: `${progress}%` }}
                  role="progressbar"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
            </div>
          )}

          {/* Action Row */}
          <div className="pt-2 flex items-center justify-end gap-3 border-t border-white/5">
            <button
              type="submit"
              disabled={!file || Boolean(clientError) || isWorking}
              className="lens-button-primary text-xs w-full sm:w-auto"
              data-testid="upload-submit-btn"
            >
              {phase === "uploading" ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Uploading ({progress}%)...</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  <span>Upload & Ingest PDF</span>
                </>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
