"use client";

import React, { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { apiClient, ApiClientError } from "@/lib/api-client";
import type { SearchResponse } from "@/types/api";
import { SourceTypeBadge } from "@/components/SourceTypeBadge";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingListSkeleton } from "@/components/LoadingSkeleton";
import { formatScorePercentage } from "@/lib/format";
import { sanitizeUrl } from "@/lib/security";
import { ProtectedRoute } from "@/components/ProtectedRoute";

const FILTER_OPTIONS = [
  { id: "all", label: "All Sources" },
  { id: "captures", label: "Captures" },
  { id: "text", label: "Notes" },
  { id: "url", label: "Web Links" },
  { id: "pdf", label: "PDFs" },
  { id: "github", label: "GitHub" },
  { id: "pull_request", label: "PRs" },
  { id: "issue", label: "Issues" },
  { id: "commit", label: "Commits" },
];

function SearchContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";
  const initialSourceType = searchParams.get("source_type") || "all";

  const [inputVal, setInputVal] = useState<string>(initialQuery);
  const [activeQuery, setActiveQuery] = useState<string>(initialQuery);
  const [selectedFilter, setSelectedFilter] = useState<string>(initialSourceType);
  const [prevQuery, setPrevQuery] = useState<string>(initialQuery);
  const [prevSourceType, setPrevSourceType] = useState<string>(initialSourceType);

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(() => Boolean(initialQuery.trim()));
  const [error, setError] = useState<string | null>(null);

  // Synchronize local input, active query, and filter states from URL search params during render
  if (prevQuery !== initialQuery) {
    setPrevQuery(initialQuery);
    setInputVal(initialQuery);
    setActiveQuery(initialQuery);
    if (!initialQuery.trim()) {
      setResponse(null);
      setError(null);
      setLoading(false);
    } else {
      setLoading(true);
    }
  }

  if (prevSourceType !== initialSourceType) {
    setPrevSourceType(initialSourceType);
    setSelectedFilter(initialSourceType);
    if (initialQuery.trim()) {
      setLoading(true);
    }
  }

  const abortControllerRef = useRef<AbortController | null>(null);
  const latestRequestIdRef = useRef<number>(0);

  const executeSearch = useCallback(async (query: string, filter?: string) => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResponse(null);
      setError(null);
      return;
    }

    const currentFilter = filter !== undefined ? filter : selectedFilter;

    // Cancel in-flight requests to prevent stale results
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const requestId = ++latestRequestIdRef.current;

    setLoading(true);
    setError(null);

    try {
      const data = await apiClient.search({
        q: trimmed,
        limit: 20,
        source_type: currentFilter === "all" ? undefined : currentFilter,
        signal: controller.signal,
      });

      // Prevent race conditions: only update state if this is the newest request
      if (requestId === latestRequestIdRef.current) {
        setResponse(data);
        setError(null);
      }
    } catch (err: unknown) {
      if (requestId === latestRequestIdRef.current) {
        if (err instanceof ApiClientError && err.isTimeout) {
          // Aborted by a newer query or user navigation
          return;
        }
        const message = err instanceof ApiClientError ? err.detail : "Search request failed.";
        setError(message);
        setResponse(null);
      }
    } finally {
      if (requestId === latestRequestIdRef.current) {
        setLoading(false);
      }
    }
  }, [selectedFilter]);

  // Fetch search results when URL query or filter changes
  useEffect(() => {
    // If query is empty, cancel any pending requests
    if (!initialQuery.trim()) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      latestRequestIdRef.current++;
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const requestId = ++latestRequestIdRef.current;

    apiClient
      .search({
        q: initialQuery.trim(),
        limit: 20,
        source_type: initialSourceType === "all" ? undefined : initialSourceType,
        signal: controller.signal,
      })
      .then((data) => {
        if (requestId === latestRequestIdRef.current) {
          setResponse(data);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (requestId === latestRequestIdRef.current) {
          if (err instanceof ApiClientError && err.isTimeout) return;
          const message = err instanceof ApiClientError ? err.detail : "Search request failed.";
          setError(message);
          setResponse(null);
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [initialQuery, initialSourceType]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputVal.trim();
    if (!trimmed) return;

    setActiveQuery(trimmed);
    const filterParam = selectedFilter !== "all" ? `&source_type=${encodeURIComponent(selectedFilter)}` : "";
    const isUrlChanging = trimmed !== initialQuery.trim() || selectedFilter !== initialSourceType;

    if (isUrlChanging) {
      setLoading(true);
      setError(null);
      router.push(`/search?q=${encodeURIComponent(trimmed)}${filterParam}`);
    } else {
      executeSearch(trimmed, selectedFilter);
    }
  };

  const handleFilterSelect = (filterId: string) => {
    setSelectedFilter(filterId);
    const queryToUse = activeQuery.trim() || inputVal.trim();
    if (queryToUse) {
      const isUrlChanging = filterId !== initialSourceType || queryToUse !== initialQuery.trim();
      if (isUrlChanging) {
        setLoading(true);
        setError(null);
        const filterParam = filterId !== "all" ? `&source_type=${encodeURIComponent(filterId)}` : "";
        router.push(`/search?q=${encodeURIComponent(queryToUse)}${filterParam}`);
      } else {
        executeSearch(queryToUse, filterId);
      }
    }
  };

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="pb-5 border-b border-[#E5E7EB]">
        <h1 className="text-2xl font-semibold tracking-tight text-[#0F172A]">Search Knowledge Base</h1>
        <p className="text-sm text-[#5B6472] mt-1">
          Unified knowledge retrieval combining captured items (notes, links, PDFs) and ingested GitHub activities (PRs, issues, commits, reviews).
        </p>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSubmit} className="flex gap-2.5">
        <div className="relative flex-1">
          <input
            type="search"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            placeholder="Search concepts, code, links, notes, PRs, commits (e.g. 'fastapi async pool')..."
            className="w-full h-12 pl-10 pr-4 text-sm bg-white border border-[#E5E7EB] rounded-[4px] text-[#0F172A] placeholder-[#94A3B8] focus:outline-none focus:border-[#2075CC] focus:ring-1 focus:ring-[#2075CC] transition-colors"
            autoFocus
          />
          <svg
            className="w-4 h-4 text-[#5B6472] absolute left-3.5 top-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <button
          type="submit"
          disabled={!inputVal.trim()}
          className="h-12 px-6 rounded-[4px] text-sm font-semibold text-white bg-[#2075CC] hover:bg-[#115AA4] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0 flex items-center justify-center gap-2"
          data-testid="search-submit-btn"
        >
          {loading ? (
            <>
              <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Searching...</span>
            </>
          ) : (
            <span>Search</span>
          )}
        </button>
      </form>

      {/* Source Category Filter Pills */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="search-filter-pills">
        <span className="text-[11px] font-semibold text-[#5B6472] mr-1.5 font-mono uppercase tracking-wider">Filter:</span>
        {FILTER_OPTIONS.map((opt) => {
          const isSelected = selectedFilter === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleFilterSelect(opt.id)}
              aria-pressed={isSelected}
              className={`px-3 py-1.5 rounded-[4px] text-xs font-medium transition-colors border ${
                isSelected
                  ? "bg-[#2075CC] text-white border-[#2075CC] shadow-xs"
                  : "bg-white text-[#5B6472] hover:text-[#0F172A] hover:bg-[#F8FAFC] border-[#E5E7EB]"
              }`}
              data-testid={`filter-btn-${opt.id}`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {/* Degraded Search Warning Banner */}
      {response?.degraded && (
        <div className="p-4 rounded-[4px] bg-[#FFFBEB] border border-[#FDE68A] text-[#92400E] text-xs flex items-center gap-2.5">
          <svg className="w-4 h-4 text-[#D97706] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>
            Semantic search is temporarily running in degraded mode; showing lexical full-text results across captures and activities.
          </span>
        </div>
      )}

      {/* Error State */}
      {error && <ErrorMessage message={error} onRetry={() => executeSearch(activeQuery, selectedFilter)} />}

      {/* Loading Skeleton */}
      {loading && <LoadingListSkeleton count={3} />}

      {/* Empty Search Prompt (Initial State) */}
      {!loading && !response && !error && (
        <div className="bg-white border border-[#E5E7EB] rounded-[8px] p-12 text-center text-[#5B6472] space-y-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
          <div className="w-12 h-12 mx-auto rounded-full bg-[#F8FAFC] border border-[#E5E7EB] flex items-center justify-center text-[#2075CC]">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-[#0F172A]">Type a search query above and press Enter to search.</p>
          <p className="text-xs text-[#5B6472] max-w-sm mx-auto">
            Search concepts, notes, links, and code commits across your integrated knowledge base.
          </p>
        </div>
      )}

      {/* No Results State */}
      {!loading && response && response.results.length === 0 && !error && (
        <div className="bg-white border border-[#E5E7EB] rounded-[8px] p-12 text-center space-y-3 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
          <div className="w-12 h-12 mx-auto rounded-full bg-[#F8FAFC] border border-[#E5E7EB] flex items-center justify-center text-[#5B6472]">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-[#0F172A]">No matching captures found</h3>
          <p className="text-xs text-[#5B6472] max-w-sm mx-auto">
            We couldn&apos;t find any content matching &quot;{response.query}&quot;. Try different keywords or conceptual terms.
          </p>
        </div>
      )}

      {/* Results List */}
      {!loading && response && response.results.length > 0 && (
        <div className="space-y-4" data-testid="search-results">
          <div className="flex items-center justify-between text-xs text-[#5B6472] px-1 font-mono">
            <span>
              Found {response.total} result{response.total === 1 ? "" : "s"} for &quot;{response.query}&quot;
              {response.source_filter && ` (${response.source_filter})`}
            </span>
          </div>

          {response.results.map((res) => {
            const isGitHub =
              res.result_kind === "github_activity" ||
              ["pull_request", "issue", "commit", "review"].includes(res.source_type);
            const safeUrl = sanitizeUrl(res.original_url);
            const titleDisplay = res.title?.trim() || res.original_url || (isGitHub ? "Untitled Activity" : "Untitled Note");

            return (
              <div
                key={res.capture_id}
                className="bg-white border border-[#E5E7EB] hover:border-[#2075CC]/50 rounded-[8px] p-5 space-y-3.5 transition-all shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
                data-testid={`search-result-${res.capture_id}`}
              >
                {/* Header Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <SourceTypeBadge sourceType={res.source_type} />
                    {res.repository_name && (
                      <span className="px-2 py-0.5 rounded-[4px] text-[11px] font-mono bg-[#F8FAFC] text-[#334155] border border-[#E5E7EB]">
                        {res.repository_name}
                      </span>
                    )}
                    {res.state && (
                      <span
                        className={`px-1.5 py-0.5 rounded-[4px] text-[10px] font-mono border font-medium ${
                          res.state === "open"
                            ? "bg-[#ECFDF5] text-[#065F46] border-[#A7F3D0]"
                            : res.state === "merged"
                            ? "bg-[#FAF5FF] text-[#6B21A8] border-[#E9D5FF]"
                            : "bg-[#F8FAFC] text-[#5B6472] border-[#E5E7EB]"
                        }`}
                      >
                        {res.state.toUpperCase()}
                      </span>
                    )}
                    {res.author_login && (
                      <span className="text-[11px] font-mono text-[#5B6472]">
                        @{res.author_login}
                      </span>
                    )}
                    <span className="px-2 py-0.5 rounded-[4px] text-xs font-semibold bg-[#EFF6FF] text-[#2075CC] border border-[#BFDBFE]">
                      Relevance: {formatScorePercentage(res.best_score)}
                    </span>
                    {res.best_lexical_score !== null && (
                      <span className="text-[11px] font-mono text-[#5B6472]" title="Normalized Full-Text Keyword Score">
                        Lexical: {formatScorePercentage(res.best_lexical_score)}
                      </span>
                    )}
                    {res.best_semantic_score !== null && (
                      <span className="text-[11px] font-mono text-[#5B6472]" title="Cosine Semantic Vector Score">
                        Semantic: {formatScorePercentage(res.best_semantic_score)}
                      </span>
                    )}
                  </div>

                  {isGitHub ? (
                    safeUrl ? (
                      <a
                        href={safeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[#2075CC] hover:text-[#115AA4] font-medium self-start sm:self-auto flex items-center gap-1 font-mono"
                        data-testid={`inspect-github-${res.capture_id}`}
                      >
                        <span>View on GitHub</span>
                        <span>↗</span>
                      </a>
                    ) : (
                      <span className="text-xs text-[#5B6472] font-mono">GitHub Activity</span>
                    )
                  ) : (
                    <Link
                      href={`/captures/${res.capture_id}`}
                      className="text-xs text-[#2075CC] hover:text-[#115AA4] font-semibold self-start sm:self-auto flex items-center gap-1"
                    >
                      <span>Inspect Capture</span>
                      <span>→</span>
                    </Link>
                  )}
                </div>

                {/* Title */}
                <h3 className="text-base font-semibold text-[#0F172A] hover:text-[#2075CC] transition-colors">
                  {isGitHub && safeUrl ? (
                    <a
                      href={safeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline"
                    >
                      {titleDisplay}
                    </a>
                  ) : isGitHub ? (
                    <span>{titleDisplay}</span>
                  ) : (
                    <Link href={`/captures/${res.capture_id}`} className="hover:underline">
                      {titleDisplay}
                    </Link>
                  )}
                </h3>

                {safeUrl && !isGitHub && (
                  <p className="text-xs text-[#5B6472] font-mono truncate">
                    <a
                      href={safeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline hover:text-[#2075CC]"
                    >
                      {safeUrl}
                    </a>
                  </p>
                )}

                {/* Matching Chunks / Excerpt */}
                {res.matching_chunks && res.matching_chunks.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-[#F1F5F9]">
                    {res.matching_chunks.map((chunk) => (
                      <div
                        key={chunk.chunk_id}
                        className="p-3 rounded-[4px] bg-[#F8FAFC] border border-[#E5E7EB] text-xs text-[#334155] leading-relaxed font-sans"
                      >
                        <div className="flex items-center justify-between text-[11px] font-mono text-[#5B6472] pb-1.5 mb-1.5 border-b border-[#E5E7EB]">
                          <span>
                            {isGitHub ? "Activity snippet" : `Chunk #${chunk.chunk_index + 1} match`}
                          </span>
                          <div className="flex gap-2">
                            <span className="font-semibold text-[#2075CC]">Score: {formatScorePercentage(chunk.score)}</span>
                            {chunk.lexical_score !== null && <span>Lex: {formatScorePercentage(chunk.lexical_score)}</span>}
                            {chunk.semantic_score !== null && <span>Sem: {formatScorePercentage(chunk.semantic_score)}</span>}
                          </div>
                        </div>
                        <p className="whitespace-pre-wrap">{chunk.content_excerpt}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<LoadingListSkeleton count={3} />}>
        <SearchContent />
      </Suspense>
    </ProtectedRoute>
  );
}
