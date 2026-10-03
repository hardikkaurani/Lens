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

const PAGE_LIMIT = 15;
const MAX_POLL_ATTEMPTS = 10;
const POLL_INTERVAL_MS = 3000;

export default function CapturesPage() {
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
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/10">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Captures</h1>
          <p className="text-sm text-slate-400 mt-1">
            Knowledge items saved from the web or quick notes.
          </p>
        </div>
        <Link
          href="/captures/new"
          className="lens-button-primary"
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
        <div className="lens-card p-12 text-center space-y-4">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">No captures yet</h3>
            <p className="text-sm text-slate-400 max-w-sm mx-auto mt-1">
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
        <div className="space-y-3.5" data-testid="capture-list">
          {captures.map((capture) => {
            const safeUrl = sanitizeUrl(capture.original_url);
            const titleDisplay = capture.title?.trim() || capture.original_url || "Untitled Note";
            const previewText = truncateExcerpt(capture.content || "", 180);

            return (
              <div
                key={capture.id}
                className="lens-card p-5 group hover:border-indigo-500/40"
                data-testid={`capture-card-${capture.id}`}
              >
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                  <div className="space-y-2 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <SourceTypeBadge sourceType={capture.source_type} />
                      <StatusBadge status={capture.processing_status} />
                      <span className="text-xs text-slate-500 font-mono">
                        {formatDate(capture.created_at)}
                      </span>
                    </div>

                    <h2 className="text-base font-semibold text-white group-hover:text-indigo-300 transition-colors truncate">
                      <Link href={`/captures/${capture.id}`} className="hover:underline focus:outline-none">
                        {titleDisplay}
                      </Link>
                    </h2>

                    {safeUrl && (
                      <p className="text-xs text-slate-400 font-mono truncate flex items-center gap-1.5">
                        <svg className="w-3.5 h-3.5 shrink-0 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                        <a
                          href={safeUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-indigo-400 hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {safeUrl}
                        </a>
                      </p>
                    )}

                    {previewText && (
                      <p className="text-xs text-slate-300/80 leading-relaxed line-clamp-2">
                        {previewText}
                      </p>
                    )}

                    {capture.processing_status === "failed" && capture.processing_error && (
                      <div className="p-2 rounded bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
                        {capture.processing_error}
                      </div>
                    )}
                  </div>

                  <div className="shrink-0 self-start sm:self-center">
                    <Link
                      href={`/captures/${capture.id}`}
                      className="lens-button-secondary text-xs py-1.5 px-3"
                    >
                      View Details
                    </Link>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Load More Pagination */}
          <div className="pt-4 flex flex-col items-center justify-center gap-2">
            {hasMore ? (
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loadingMore}
                className="lens-button-secondary"
              >
                {loadingMore ? (
                  <>
                    <svg className="w-4 h-4 animate-spin text-slate-400" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    <span>Loading more...</span>
                  </>
                ) : (
                  <span>Load More Captures</span>
                )}
              </button>
            ) : (
              <span className="text-xs text-slate-500 font-mono">
                Showing all {captures.length} captures
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
