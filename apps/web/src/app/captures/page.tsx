"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { Capture } from "@/types/api";
import { StatusBadge } from "@/components/StatusBadge";
import { SourceTypeBadge } from "@/components/SourceTypeBadge";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingListSkeleton } from "@/components/LoadingSkeleton";
import { formatDate } from "@/lib/format";
import { sanitizeUrl, truncateExcerpt } from "@/lib/security";
import { ProtectedRoute } from "@/components/ProtectedRoute";

const PAGE_LIMIT = 15;
const MAX_POLL_ATTEMPTS = 10;
const POLL_INTERVAL_MS = 3000;

function CapturesContent() {
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  const pollAttemptsRef = useRef<number>(0);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    apiClient
      .listCaptures({ limit: PAGE_LIMIT, offset: 0, signal: controller.signal })
      .then((res) => {
        if (isMounted) {
          setCaptures(res.items);
          setTotal(res.total);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        if (err instanceof ApiClientError && err.isTimeout) return;
        const message = err instanceof ApiClientError ? err.detail : "Failed to load captures.";
        setError(message);
        setLoading(false);
      });

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [refreshKey]);

  // Bounded polling if any visible capture is pending or processing
  useEffect(() => {
    const hasActiveJobs = captures.some(
      (c) => c.processing_status === "pending" || c.processing_status === "processing"
    );

    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    if (hasActiveJobs && pollAttemptsRef.current < MAX_POLL_ATTEMPTS) {
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
  }, [captures]);

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    pollAttemptsRef.current = 0;
    setRefreshKey((k) => k + 1);
  };

  const handleLoadMore = async () => {
    setLoadingMore(true);
    try {
      const res = await apiClient.listCaptures({
        limit: PAGE_LIMIT,
        offset: captures.length,
      });
      setCaptures((prev) => [...prev, ...res.items]);
      setTotal(res.total);
    } catch (err: unknown) {
      const message = err instanceof ApiClientError ? err.detail : "Failed to load more captures.";
      setError(message);
    } finally {
      setLoadingMore(false);
    }
  };

  const hasMore = captures.length < total;

  return (
    <div className="space-y-8">
      {/* Top Editorial Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-3xl font-normal tracking-tight text-[#000000]">Captures</h1>
          <p className="text-sm text-[#5B6472] mt-1.5 leading-normal">
            Knowledge items saved from the web, research papers, or quick unstructured notes.
          </p>
        </div>
        <Link
          href="/captures/new"
          className="lens-button-primary shrink-0"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          <span>New Capture</span>
        </Link>
      </div>

      {/* Error state */}
      {error && (
        <ErrorMessage
          message={error}
          onRetry={handleRetry}
        />
      )}

      {/* Initial Loading */}
      {loading && <LoadingListSkeleton count={4} />}

      {/* Empty State */}
      {!loading && !error && captures.length === 0 && (
        <div className="lens-card p-12 text-center space-y-5 bg-white border border-[#E5E7EB] rounded-[8px]">
          <div className="w-12 h-12 mx-auto rounded-[4px] bg-[#EFF6FF] border border-[#BFDBFE] flex items-center justify-center text-[#2075CC]">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
          <div className="space-y-1.5">
            <h3 className="text-base font-semibold text-[#000000]">No captures yet</h3>
            <p className="text-sm text-[#5B6472] max-w-sm mx-auto leading-relaxed">
              Start building your knowledge repository by saving a web article or capturing quick thoughts.
            </p>
          </div>
          <div className="pt-2">
            <Link href="/captures/new" className="lens-button-primary">
              Capture your first item
            </Link>
          </div>
        </div>
      )}

      {/* Capture Cards List */}
      {!loading && captures.length > 0 && (
        <div className="space-y-4" data-testid="capture-list">
          {captures.map((capture) => {
            const safeUrl = sanitizeUrl(capture.original_url);
            const titleDisplay = capture.title?.trim() || capture.original_url || "Untitled Note";
            const previewText = truncateExcerpt(capture.content || "", 180);

            return (
              <div
                key={capture.id}
                className="lens-card p-6 bg-white border border-[#E5E7EB] rounded-[8px] hover:border-[#CBD5E1] transition-all space-y-3"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                  <Link
                    href={`/captures/${capture.id}`}
                    className="text-base font-semibold text-[#000000] hover:text-[#2075CC] transition-colors leading-snug line-clamp-1"
                  >
                    {titleDisplay}
                  </Link>
                  <div className="shrink-0">
                    <StatusBadge status={capture.processing_status} />
                  </div>
                </div>

                {/* Metadata row */}
                <div className="flex flex-wrap items-center gap-2.5 text-xs text-[#5B6472]">
                  <SourceTypeBadge sourceType={capture.source_type} />
                  {safeUrl && (
                    <>
                      <span>•</span>
                      <a
                        href={safeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[#115AA4] hover:text-[#2075CC] hover:underline truncate max-w-xs sm:max-w-md"
                      >
                        {safeUrl}
                      </a>
                    </>
                  )}
                  <span>•</span>
                  <span>{formatDate(capture.created_at)}</span>
                </div>

                {/* Excerpt */}
                {previewText && (
                  <p className="text-sm text-[#5B6472] line-clamp-2 leading-relaxed">
                    {previewText}
                  </p>
                )}

                {/* Processing Error Notice */}
                {capture.processing_status === "failed" && capture.processing_error && (
                  <div className="text-xs text-[#C62828] bg-[#FFEBEE] border border-[#FFCDD2] p-2.5 rounded-[4px] leading-relaxed">
                    Processing error: {capture.processing_error}
                  </div>
                )}
              </div>
            );
          })}

          {/* Load more button */}
          {hasMore && (
            <div className="pt-4 flex justify-center">
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loadingMore}
                className="lens-button-secondary"
              >
                {loadingMore ? "Loading..." : "Load more captures"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CapturesPage() {
  return (
    <ProtectedRoute>
      <CapturesContent />
    </ProtectedRoute>
  );
}
