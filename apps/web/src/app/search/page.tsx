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
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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

  // Sync with URL query and filter on initial load or URL change
  useEffect(() => {
    // Synchronize local input, active query, and filter states from URL search params
    setInputVal(initialQuery);
    setActiveQuery(initialQuery);
    setSelectedFilter(initialSourceType);

    // If query is empty, cancel any pending requests and clear stale results
    if (!initialQuery.trim()) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      latestRequestIdRef.current++;
      setResponse(null);
      setError(null);
      setLoading(false);
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const requestId = ++latestRequestIdRef.current;
    setLoading(true);

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
    router.push(`/search?q=${encodeURIComponent(trimmed)}${filterParam}`);
    executeSearch(trimmed, selectedFilter);
  };

  const handleFilterSelect = (filterId: string) => {
    setSelectedFilter(filterId);
    const queryToUse = activeQuery.trim() || inputVal.trim();
    if (queryToUse) {
      const filterParam = filterId !== "all" ? `&source_type=${encodeURIComponent(filterId)}` : "";
      router.push(`/search?q=${encodeURIComponent(queryToUse)}${filterParam}`);
      executeSearch(queryToUse, filterId);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="pb-4 border-b border-white/10">
        <h1 className="text-2xl font-bold tracking-tight text-white">Search Knowledge Base</h1>
        <p className="text-sm text-slate-400 mt-1">
          Unified knowledge retrieval combining captured items (notes, links, PDFs) and ingested GitHub activities (PRs, issues, commits, reviews).
        </p>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <input
            type="search"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            placeholder="Search concepts, code, links, notes, PRs, commits (e.g. 'fastapi async pool')..."
            className="lens-input pl-10 pr-4 py-3 text-sm rounded-xl"
            autoFocus
          />
          <svg
            className="w-5 h-5 text-slate-400 absolute left-3 top-3.5"
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
          className="lens-button-primary px-5 py-3 rounded-xl text-sm"
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
        <span className="text-xs text-slate-400 mr-1 font-mono">Filter:</span>
        {FILTER_OPTIONS.map((opt) => {
          const isSelected = selectedFilter === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleFilterSelect(opt.id)}
              aria-pressed={isSelected}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                isSelected
                  ? "bg-indigo-600 text-white shadow-sm shadow-indigo-500/20"
                  : "bg-slate-800/80 text-slate-400 hover:text-white hover:bg-slate-700/80 border border-slate-700/50"
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
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-200 text-xs flex items-center gap-2.5">
          <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
        <div className="lens-card p-10 text-center text-slate-400 space-y-2">
          <svg className="w-10 h-10 mx-auto text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p className="text-sm">Type a search query above and press Enter to search.</p>
        </div>
      )}

      {/* No Results State */}
      {!loading && response && response.results.length === 0 && !error && (
        <div className="lens-card p-10 text-center space-y-3">
          <div className="w-12 h-12 mx-auto rounded-full bg-slate-800/80 flex items-center justify-center text-slate-400">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-white">No matching captures found</h3>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            We couldn&apos;t find any content matching &quot;{response.query}&quot;. Try different keywords or conceptual terms.
          </p>
        </div>
      )}

      {/* Results List */}
      {!loading && response && response.results.length > 0 && (
        <div className="space-y-4" data-testid="search-results">
          <div className="flex items-center justify-between text-xs text-slate-400 px-1 font-mono">
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
                className="lens-card p-5 space-y-3.5 group hover:border-indigo-500/40"
                data-testid={`search-result-${res.capture_id}`}
              >
                {/* Header Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <SourceTypeBadge sourceType={res.source_type} />
                    {res.repository_name && (
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-300 border border-slate-700">
                        {res.repository_name}
                      </span>
                    )}
                    {res.state && (
                      <span
                        className={`px-1.5 py-0.2 rounded text-[10px] font-mono border ${
                          res.state === "open"
                            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                            : res.state === "merged"
                            ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                            : "bg-slate-800 text-slate-400 border-slate-700"
                        }`}
                      >
                        {res.state.toUpperCase()}
                      </span>
                    )}
                    {res.author_login && (
                      <span className="text-[11px] font-mono text-slate-400">
                        @{res.author_login}
                      </span>
                    )}
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                      Relevance: {formatScorePercentage(res.best_score)}
                    </span>
                    {res.best_lexical_score !== null && (
                      <span className="text-[11px] font-mono text-slate-400" title="Normalized Full-Text Keyword Score">
                        Lexical: {formatScorePercentage(res.best_lexical_score)}
                      </span>
                    )}
                    {res.best_semantic_score !== null && (
                      <span className="text-[11px] font-mono text-slate-400" title="Cosine Semantic Vector Score">
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
                        className="text-xs text-cyan-400 hover:text-cyan-300 font-medium self-start sm:self-auto flex items-center gap-1 font-mono"
                        data-testid={`inspect-github-${res.capture_id}`}
                      >
                        <span>View on GitHub</span>
                        <span>↗</span>
                      </a>
                    ) : (
                      <span className="text-xs text-slate-500 font-mono">GitHub Activity</span>
                    )
                  ) : (
                    <Link
                      href={`/captures/${res.capture_id}`}
                      className="text-xs text-indigo-400 hover:text-indigo-300 font-medium self-start sm:self-auto flex items-center gap-1"
                    >
                      <span>Inspect Capture</span>
                      <span>→</span>
                    </Link>
                  )}
                </div>

                {/* Title */}
                <h3 className="text-base font-semibold text-white group-hover:text-indigo-300 transition-colors">
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
                    <Link href={`/captures/${res.capture_id}`}>
                      {titleDisplay}
                    </Link>
                  )}
                </h3>

                {safeUrl && !isGitHub && (
                  <p className="text-xs text-slate-400 font-mono truncate">
                    <a
                      href={safeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline hover:text-indigo-300"
                    >
                      {safeUrl}
                    </a>
                  </p>
                )}

                {/* Matching Chunks / Excerpt */}
                {res.matching_chunks && res.matching_chunks.length > 0 && (
                  <div className="space-y-2 pt-1 border-t border-white/5">
                    {res.matching_chunks.map((chunk) => (
                      <div
                        key={chunk.chunk_id}
                        className="p-3 rounded-lg bg-[#0d121e] border border-white/5 text-xs text-slate-300/90 leading-relaxed font-sans"
                      >
                        <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pb-1 mb-1 border-b border-white/5">
                          <span>
                            {isGitHub ? "Activity snippet" : `Chunk #${chunk.chunk_index + 1} match`}
                          </span>
                          <div className="flex gap-2">
                            <span>Score: {formatScorePercentage(chunk.score)}</span>
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
    <Suspense fallback={<LoadingListSkeleton count={3} />}>
      <SearchContent />
    </Suspense>
  );
}
