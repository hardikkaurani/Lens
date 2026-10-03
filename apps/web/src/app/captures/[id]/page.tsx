"use client";

import React, { useEffect, useRef, useState, use } from "react";
import Link from "next/link";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { CaptureDetail } from "@/types/api";
import { StatusBadge } from "@/components/StatusBadge";
import { SourceTypeBadge } from "@/components/SourceTypeBadge";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingCardSkeleton } from "@/components/LoadingSkeleton";
import { formatDate, formatFileSize } from "@/lib/format";
import { sanitizeUrl } from "@/lib/security";

const MAX_POLL_ATTEMPTS = 10;
const POLL_INTERVAL_MS = 3000;

interface PageProps {
  params: Promise<{ id: string }>;
}

export function CaptureDetailContent({ id }: { id: string }) {
  const [capture, setCapture] = useState<CaptureDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isNotFound, setIsNotFound] = useState<boolean>(false);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  const pollAttemptsRef = useRef<number>(0);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    apiClient
      .getCapture(id, { signal: controller.signal })
      .then((data) => {
        if (isMounted) {
          setCapture(data);
          setError(null);
          setIsNotFound(false);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        if (err instanceof ApiClientError && err.isTimeout) return;

        if (err instanceof ApiClientError && err.status === 404) {
          setIsNotFound(true);
        } else {
          const message = err instanceof ApiClientError ? err.detail : "Failed to load capture details.";
          setError(message);
        }
        setLoading(false);
      });

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [id, refreshKey]);

  // Bounded polling if capture is in pending or processing state
  useEffect(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    const isPendingOrProcessing =
      capture &&
      (capture.processing_status === "pending" || capture.processing_status === "processing");

    if (isPendingOrProcessing && pollAttemptsRef.current < MAX_POLL_ATTEMPTS) {
      pollTimerRef.current = setInterval(() => {
        pollAttemptsRef.current += 1;
        if (pollAttemptsRef.current >= MAX_POLL_ATTEMPTS) {
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
        }
        setRefreshKey((k) => k + 1);
      }, POLL_INTERVAL_MS);
    }

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [capture]);

  if (loading) {
    return (
      <div className="space-y-6 max-w-4xl">
        <div className="h-6 bg-slate-800 rounded w-32 animate-shimmer" />
        <LoadingCardSkeleton />
        <LoadingCardSkeleton />
      </div>
    );
  }

  if (isNotFound) {
    return (
      <div className="lens-card p-12 text-center space-y-4 max-w-2xl mx-auto">
        <div className="w-14 h-14 mx-auto rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
          <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <h2 className="text-lg font-bold text-white">Capture Not Found</h2>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          The requested capture ID does not exist or may have been deleted.
        </p>
        <div className="pt-2">
          <Link href="/captures" className="lens-button-primary">
            Back to Captures
          </Link>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 max-w-2xl">
        <ErrorMessage
          message={error}
          onRetry={() => {
            setLoading(true);
            setRefreshKey((k) => k + 1);
          }}
        />
        <div>
          <Link href="/captures" className="lens-button-secondary text-xs">
            Back to Captures
          </Link>
        </div>
      </div>
    );
  }

  if (!capture) {
    return null;
  }

  const safeUrl = sanitizeUrl(capture.original_url);
  const chunks = capture.chunks || [];

  return (
    <div className="space-y-6 max-w-4xl" data-testid="capture-detail">
      {/* Breadcrumb & Navigation */}
      <div className="flex items-center justify-between pb-3 border-b border-white/10">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Link href="/captures" className="hover:text-white transition-colors">
            Captures
          </Link>
          <span>/</span>
          <span className="font-mono text-slate-300 truncate max-w-[200px]">{capture.id}</span>
        </div>
        <Link href="/captures" className="lens-button-secondary text-xs">
          ← Back to Captures
        </Link>
      </div>

      {/* Main Metadata Card */}
      <div className="lens-card p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <SourceTypeBadge sourceType={capture.source_type} />
            <StatusBadge status={capture.processing_status} />
          </div>
          <div className="text-xs text-slate-400 font-mono">
            Captured {formatDate(capture.created_at)}
          </div>
        </div>

        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight break-words">
          {capture.title || capture.original_url || "Untitled Note"}
        </h1>

        {safeUrl && (
          <div className="flex items-center gap-2 text-xs font-mono text-indigo-300 break-all">
            <svg className="w-4 h-4 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
            <a
              href={safeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline hover:text-indigo-200"
            >
              {safeUrl}
            </a>
          </div>
        )}

        {/* Processing Failure Alert */}
        {capture.processing_status === "failed" && (
          <div className="p-4 rounded-xl bg-rose-950/30 border border-rose-500/30 text-rose-200 text-xs space-y-1">
            <div className="font-semibold text-rose-100 flex items-center gap-2">
              <svg className="w-4 h-4 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Ingestion Pipeline Halted</span>
            </div>
            <p className="text-rose-300">
              {capture.processing_error || "The capture could not be processed due to an upstream extraction or network error."}
            </p>
          </div>
        )}

        {/* Pending or Processing Ingestion Banner */}
        {(capture.processing_status === "pending" || capture.processing_status === "processing") && (
          <div className="p-4 rounded-xl bg-indigo-950/30 border border-indigo-500/30 text-indigo-200 text-xs flex items-center gap-3">
            <svg className="w-5 h-5 animate-spin text-indigo-400 shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <div>
              <p className="font-semibold text-indigo-100">
                {capture.processing_status === "pending"
                  ? "Queued for Ingestion"
                  : capture.source_type === "pdf" || capture.source_type === "file"
                  ? "Extracting and Indexing PDF"
                  : "Processing Webpage"}
              </p>
              <p className="text-indigo-300/80 mt-0.5">
                {capture.source_type === "pdf" || capture.source_type === "file"
                  ? "The background worker is currently extracting text, normalizing, chunking, and embedding this PDF."
                  : "The background worker is currently fetching, normalizing, chunking, and embedding this item."}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Captured Content / Chunks Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-white">
            {chunks.length > 0
              ? `Extracted Content Chunks (${chunks.length})`
              : "Content"}
          </h2>
          {capture.processed_at && (
            <span className="text-xs text-slate-500 font-mono">
              Processed: {formatDate(capture.processed_at)}
            </span>
          )}
        </div>

        {/* Chunks List */}
        {chunks.length > 0 ? (
          <div className="space-y-3" data-testid="chunks-container">
            {chunks.map((chunk) => (
              <div
                key={chunk.id}
                className="lens-card p-4 space-y-2 bg-[#0d121e]"
                data-testid={`chunk-item-${chunk.chunk_index}`}
              >
                <div className="flex items-center justify-between text-xs text-slate-400 font-mono border-b border-white/5 pb-2">
                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                    Chunk #{chunk.chunk_index + 1}
                  </span>
                  <span>{chunk.content.length.toLocaleString()} characters</span>
                </div>
                <div className="text-xs sm:text-sm text-slate-200 leading-relaxed font-sans whitespace-pre-wrap select-text">
                  {chunk.content}
                </div>
              </div>
            ))}
          </div>
        ) : capture.content ? (
          /* Raw Text Content for Text Captures */
          <div className="lens-card p-5 bg-[#0d121e]">
            <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap select-text font-sans">
              {capture.content}
            </div>
          </div>
        ) : (
          /* Placeholder while waiting or if empty */
          <div className="lens-card p-8 text-center text-xs text-slate-500">
            {capture.processing_status === "completed"
              ? "No extracted textual chunks available for this capture."
              : "Content will appear here once background ingestion and chunking finish."}
          </div>
        )}
      </div>

      {/* Document Information Section for PDF/File Captures */}
      {(capture.source_type === "pdf" || capture.source_type === "file") && capture.metadata ? (
        <div className="space-y-3 pt-2" data-testid="document-info-section">
          <h3 className="text-sm font-semibold text-slate-300">Document Information</h3>
          <div className="lens-card p-5 bg-[#0d121e] grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div>
              <span className="text-slate-500 block font-mono text-[11px]">Filename</span>
              <span className="text-slate-200 font-semibold break-all" data-testid="detail-filename">
                {String(capture.metadata.original_filename || capture.title || "document.pdf")}
              </span>
            </div>
            {typeof capture.metadata.byte_size === "number" && (
              <div>
                <span className="text-slate-500 block font-mono text-[11px]">File Size</span>
                <span className="text-slate-200 font-semibold font-mono" data-testid="detail-filesize">
                  {formatFileSize(capture.metadata.byte_size)}
                </span>
              </div>
            )}
            {Boolean(capture.metadata.mime_type || capture.mime_type) && (
              <div>
                <span className="text-slate-500 block font-mono text-[11px]">MIME Type</span>
                <span className="text-slate-200 font-mono" data-testid="detail-mimetype">
                  {String(capture.metadata.mime_type || capture.mime_type)}
                </span>
              </div>
            )}
            {typeof capture.metadata.sha256 === "string" && (
              <div className="sm:col-span-2">
                <span className="text-slate-500 block font-mono text-[11px]">SHA-256 Checksum</span>
                <span
                  className="text-slate-300 font-mono text-[11px] break-all select-all bg-black/40 px-2.5 py-1.5 rounded block mt-1 border border-white/5"
                  data-testid="detail-sha256"
                >
                  {capture.metadata.sha256}
                </span>
              </div>
            )}
          </div>
        </div>
      ) : capture.metadata && Object.keys(capture.metadata).length > 0 ? (
        /* Generic Structured Source Metadata for other capture types */
        <div className="space-y-3 pt-2">
          <h3 className="text-sm font-semibold text-slate-300">Source Metadata</h3>
          <div className="lens-card p-4 bg-[#0d121e]">
            <pre className="text-xs text-indigo-300/90 font-mono overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(capture.metadata, null, 2)}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function CaptureDetailPage({ params }: PageProps) {
  const { id } = use(params);
  return <CaptureDetailContent id={id} />;
}
