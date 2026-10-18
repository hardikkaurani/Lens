"use client";

import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { GitHubActivity, GitHubConnectionStatus, GitHubRepository } from "@/types/api";
import { ErrorMessage } from "@/components/ErrorMessage";

function getCategoryCounts(repo: GitHubRepository): Array<[string, number]> {
  const meta = repo.activity_sync_metadata;
  if (!meta || typeof meta !== "object") return [];

  // Backend contract stores counts inside meta.categories[category].count
  if (meta.categories && typeof meta.categories === "object") {
    const entries: Array<[string, number]> = [];
    for (const [type, data] of Object.entries(meta.categories as Record<string, { count?: number }>)) {
      if (data && typeof data === "object" && typeof data.count === "number") {
        entries.push([type, data.count]);
      }
    }
    if (entries.length > 0) return entries;
  }

  // Fallback if direct counts dictionary is present
  if (meta.counts && typeof meta.counts === "object") {
    return Object.entries(meta.counts as Record<string, number>).filter(
      ([, count]) => typeof count === "number"
    );
  }

  return [];
}

export function SettingsContent() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<GitHubConnectionStatus | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isDisconnecting, setIsDisconnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  // Repository state
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [totalRepos, setTotalRepos] = useState<number>(0);
  const [isLoadingRepos, setIsLoadingRepos] = useState<boolean>(true);
  const [isSyncingRepos, setIsSyncingRepos] = useState<boolean>(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [repoSearch, setRepoSearch] = useState<string>("");

  // Activity Ingestion state
  const [isSyncingActivities, setIsSyncingActivities] = useState<boolean>(false);
  const [activitySyncRepoId, setActivitySyncRepoId] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activities, setActivities] = useState<GitHubActivity[]>([]);
  const [showActivityDrawer, setShowActivityDrawer] = useState<boolean>(false);
  const [isLoadingActivities, setIsLoadingActivities] = useState<boolean>(false);
  const [activityTypeFilter, setActivityTypeFilter] = useState<string>("");

  const [dismissedNotification, setDismissedNotification] = useState<boolean>(false);
  const [actionNotification, setActionNotification] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Compute notification derived from query parameters
  const urlNotification = useMemo(() => {
    const githubParam = searchParams.get("github");
    const githubError = searchParams.get("github_error");

    if (githubParam === "connected") {
      return {
        type: "success" as const,
        message: "GitHub account connected successfully!",
      };
    }
    if (githubError) {
      const sanitizedMsg =
        githubError === "access_denied"
          ? "GitHub authorization was canceled or denied."
          : `GitHub connection failed: ${githubError.replace(/[^\w\s-]/g, "")}`;
      return {
        type: "error" as const,
        message: sanitizedMsg,
      };
    }
    return null;
  }, [searchParams]);

  const activeNotification = dismissedNotification ? actionNotification : (actionNotification || urlNotification);

  // Fetch connection status on mount and upon refresh
  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    apiClient
      .getGitHubStatus({ signal: controller.signal })
      .then((res) => {
        if (isMounted) {
          setStatus(res);
          setError(null);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        const message = err instanceof ApiClientError ? err.detail : "Could not load integration status. Please check your connection.";
        setError(message);
        setIsLoading(false);
      });

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [refreshKey]);

  // Fetch repositories whenever account is connected
  useEffect(() => {
    if (!status?.connected) {
      return;
    }

    let isMounted = true;
    const controller = new AbortController();

    apiClient
      .getGitHubRepositories({ signal: controller.signal })
      .then((res) => {
        if (isMounted) {
          setRepositories(res.items);
          setTotalRepos(res.total);
          setIsLoadingRepos(false);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        const message = err instanceof ApiClientError ? err.detail : "Could not load repositories.";
        setRepoError(message);
        setIsLoadingRepos(false);
      });

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, [status?.connected, refreshKey]);

  // Handle repository sync
  const handleSyncRepositories = async () => {
    if (isSyncingRepos) return;
    if (status?.has_required_scope === false) {
      setRepoError(
        status.missing_scope_reason ||
          "Your GitHub connection is missing repository permissions. Please reconnect your account."
      );
      return;
    }
    setIsSyncingRepos(true);
    setRepoError(null);

    try {
      const syncRes = await apiClient.syncGitHubRepositories();
      if (syncRes.status === "enqueued") {
        setDismissedNotification(false);
        setActionNotification({
          type: "success",
          message: "Repository synchronization job enqueued in background worker.",
        });
      } else if (syncRes.status === "already_syncing") {
        setDismissedNotification(false);
        setActionNotification({
          type: "error",
          message: "Repository synchronization is already in progress for this connection.",
        });
      } else {
        const listRes = await apiClient.getGitHubRepositories();
        setRepositories(listRes.items);
        setTotalRepos(listRes.total);
        setDismissedNotification(false);
        setActionNotification({
          type: "success",
          message: `Successfully discovered and synchronized ${syncRes.synced_count} repositories.`,
        });
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        if (err.status === 429) {
          setRepoError("GitHub API rate limit exceeded. Please try again later.");
        } else {
          setRepoError(err.detail);
        }
      } else if (
        (typeof err === "object" && err !== null && "status" in err && (err as { status: unknown }).status === 429) ||
        (err instanceof Error && err.message.toLowerCase().includes("rate limit"))
      ) {
        setRepoError("GitHub API rate limit exceeded. Please try again later.");
      } else {
        setRepoError("Failed to synchronize repositories. Please check your network connection.");
      }
    } finally {
      setIsSyncingRepos(false);
    }
  };

  // Handle repository selection toggle
  const handleToggleSelect = async (repo: GitHubRepository) => {
    const nextSelected = !repo.is_selected;
    setRepositories((prev) =>
      prev.map((r) => (r.id === repo.id ? { ...r, is_selected: nextSelected } : r))
    );

    try {
      await apiClient.updateGitHubRepositorySelection(repo.id, nextSelected);
    } catch (err: unknown) {
      // Revert optimistic update on failure
      setRepositories((prev) =>
        prev.map((r) => (r.id === repo.id ? { ...r, is_selected: repo.is_selected } : r))
      );
      const msg = err instanceof ApiClientError ? err.detail : "Failed to update repository selection.";
      setRepoError(msg);
    }
  };

  // Filter repositories client-side
  const filteredRepos = useMemo(() => {
    if (!repoSearch.trim()) return repositories;
    const q = repoSearch.toLowerCase().trim();
    return repositories.filter(
      (r) => r.name.toLowerCase().includes(q) || r.full_name.toLowerCase().includes(q)
    );
  }, [repositories, repoSearch]);

  // Selected repositories memo
  const selectedRepos = useMemo(() => repositories.filter((r) => r.is_selected), [repositories]);

  // Handle activity sync (all selected or specific repository)
  const handleSyncActivities = async (repositoryId?: string) => {
    if (isSyncingActivities) return;
    if (status?.has_required_scope === false) {
      setActivityError(
        status.missing_scope_reason ||
          "Your GitHub connection is missing repository permissions. Please reconnect your account."
      );
      return;
    }

    const targetIds = repositoryId ? [repositoryId] : selectedRepos.map((r) => r.id);
    if (targetIds.length === 0) {
      setActivityError("Please select at least one repository before synchronizing activities.");
      return;
    }

    setIsSyncingActivities(true);
    setActivitySyncRepoId(repositoryId || null);
    setActivityError(null);

    try {
      const syncRes = await apiClient.syncGitHubActivities({
        repository_ids: targetIds,
        async_sync: true,
      });

      if (syncRes.status === "enqueued") {
        setDismissedNotification(false);
        setActionNotification({
          type: "success",
          message: "Activity synchronization job enqueued in background worker.",
        });
      } else if (syncRes.status === "already_syncing") {
        setDismissedNotification(false);
        setActionNotification({
          type: "error",
          message: "Activity synchronization is already in progress for this repository.",
        });
      } else {
        setDismissedNotification(false);
        setActionNotification({
          type: "success",
          message: syncRes.message || `Successfully synchronized activities across ${syncRes.synced_repositories} repositories.`,
        });
      }

      // Refresh repository list to update sync status, metadata counts, and timestamps
      const listRes = await apiClient.getGitHubRepositories();
      setRepositories(listRes.items);
      setTotalRepos(listRes.total);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        if (err.status === 429) {
          setActivityError("GitHub API rate limit exceeded. Please try again later.");
        } else if (err.status === 401) {
          setActivityError("GitHub authorization expired. Please reconnect your account.");
        } else {
          setActivityError(err.detail);
        }
      } else {
        setActivityError("Failed to synchronize activities. Please check your network connection.");
      }
    } finally {
      setIsSyncingActivities(false);
      setActivitySyncRepoId(null);
    }
  };

  // Fetch activities preview
  const activityRequestSeq = useRef(0);
  const handleLoadActivities = async (typeFilter?: string) => {
    const seq = ++activityRequestSeq.current;
    setIsLoadingActivities(true);
    try {
      const filterToUse = typeFilter !== undefined ? (typeFilter || undefined) : (activityTypeFilter || undefined);
      const res = await apiClient.getGitHubActivities({
        activity_type: filterToUse,
        limit: 25,
      });
      if (seq === activityRequestSeq.current) {
        setActivities(res.items);
      }
    } catch {
      // safe fallback
    } finally {
      if (seq === activityRequestSeq.current) {
        setIsLoadingActivities(false);
      }
    }
  };

  const renderActivityStatusBadge = (repo: GitHubRepository) => {
    const s = repo.activity_sync_status || "idle";
    if (s === "syncing") {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-cyan-950/50 text-cyan-300 border border-cyan-500/30" data-testid={`activity-status-${repo.id}`}>
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          Syncing...
        </span>
      );
    }
    if (s === "queued") {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-950/50 text-amber-300 border border-amber-500/30" data-testid={`activity-status-${repo.id}`}>
          Queued
        </span>
      );
    }
    if (s === "synced") {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-950/50 text-emerald-300 border border-emerald-500/30" data-testid={`activity-status-${repo.id}`}>
          Synced
        </span>
      );
    }
    if (s === "partial") {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-950/50 text-amber-300 border border-amber-500/30" data-testid={`activity-status-${repo.id}`}>
          Partial Sync
        </span>
      );
    }
    if (s === "failed") {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-rose-950/50 text-rose-300 border border-rose-500/30" data-testid={`activity-status-${repo.id}`}>
          Sync Failed
        </span>
      );
    }
    return null;
  };

  // Handle disconnect action
  const handleDisconnect = async () => {
    if (!confirm("Are you sure you want to disconnect your GitHub account?")) {
      return;
    }

    setIsDisconnecting(true);
    setError(null);
    try {
      await apiClient.disconnectGitHub();
      setStatus({ connected: false });
      setRepositories([]);
      setTotalRepos(0);
      setDismissedNotification(false);
      setActionNotification({
        type: "success",
        message: "GitHub account disconnected.",
      });
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.detail);
      } else {
        setError("Failed to disconnect GitHub. Please try again.");
      }
    } finally {
      setIsDisconnecting(false);
    }
  };

  return (
    <div className="space-y-8 max-w-4xl" data-testid="settings-page">
      {/* Page Title Header */}
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Integrations & Settings</h1>
        <p className="text-sm text-slate-400 mt-1">
          Manage third-party platform connections and indexing permissions.
        </p>
      </div>

      {/* Notification Banner */}
      {activeNotification && (
        <div
          role="alert"
          className={`p-4 rounded-xl text-xs flex items-center justify-between border ${
            activeNotification.type === "success"
              ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-200"
              : "bg-rose-950/30 border-rose-500/30 text-rose-200"
          }`}
          data-testid="settings-notification"
        >
          <div className="flex items-center gap-2.5">
            {activeNotification.type === "success" ? (
              <svg className="w-4 h-4 shrink-0 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4 shrink-0 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            <span>{activeNotification.message}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setDismissedNotification(true);
              setActionNotification(null);
            }}
            className="text-slate-400 hover:text-white p-1 rounded"
            aria-label="Dismiss notification"
          >
            ✕
          </button>
        </div>
      )}

      {/* Error Message with Retry */}
      {error && <ErrorMessage message={error} onRetry={() => setRefreshKey((k) => k + 1)} />}

      {/* Integrations Section */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold text-slate-200">Connected Accounts</h2>

        {isLoading ? (
          /* Loading Skeleton */
          <div className="lens-card p-6 space-y-4 animate-pulse bg-[#0d121e]" data-testid="settings-loading">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-slate-800" />
                <div className="space-y-2">
                  <div className="w-24 h-4 rounded bg-slate-800" />
                  <div className="w-48 h-3 rounded bg-slate-800/60" />
                </div>
              </div>
              <div className="w-20 h-6 rounded bg-slate-800" />
            </div>
          </div>
        ) : status?.connected ? (
          /* CONNECTED STATE */
          <div className="lens-card p-6 space-y-6 bg-[#0d121e]" data-testid="github-connected-card">
            {/* Account Info Header */}
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div className="w-11 h-11 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-white">
                  <svg className="w-6 h-6 fill-current" viewBox="0 0 24 24">
                    <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                  </svg>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-white text-base">GitHub</h3>
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20" data-testid="status-badge-connected">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      Connected
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Account: <span className="text-slate-200 font-mono font-medium" data-testid="connected-username">@{status.github_username || "unknown"}</span>
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={handleDisconnect}
                disabled={isDisconnecting}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-rose-500/20 text-rose-300 hover:text-rose-200 hover:bg-rose-950/30 transition-colors disabled:opacity-50"
                data-testid="disconnect-github-btn"
              >
                {isDisconnecting ? "Disconnecting..." : "Disconnect"}
              </button>
            </div>

            {/* Connection Details Metadata */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-white/5 text-xs">
              <div>
                <span className="text-slate-500 block font-mono text-[11px]">Authorized Scope</span>
                <span className="text-slate-300 font-mono">{status.scope || "read:user"}</span>
              </div>
              <div>
                <span className="text-slate-500 block font-mono text-[11px]">Connected At</span>
                <span className="text-slate-300 font-mono">{formatDate(status.connected_at)}</span>
              </div>
              <div>
                <span className="text-slate-500 block font-mono text-[11px]">Last Verified</span>
                <span className="text-slate-300 font-mono">{formatDate(status.last_verified_at)}</span>
              </div>
            </div>

            {/* Missing Required Scope Warning Banner */}
            {status.has_required_scope === false && (
              <div
                role="alert"
                className="p-4 rounded-xl text-xs bg-amber-950/40 border border-amber-500/40 text-amber-200 flex flex-wrap items-center justify-between gap-3"
                data-testid="missing-scope-warning"
              >
                <div className="flex items-center gap-2.5">
                  <svg className="w-5 h-5 shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <div>
                    <span className="font-semibold block text-amber-300">Repository Discovery Permission Required</span>
                    <span className="text-[11px] text-amber-200/90">
                      {status.missing_scope_reason ||
                        "Your GitHub connection is missing repository permissions (repo or public_repo scope). Please reconnect your account to grant access."}
                    </span>
                  </div>
                </div>
                <a
                  href={apiClient.getGitHubConnectUrl()}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors shrink-0"
                  data-testid="reconnect-github-btn"
                >
                  Reconnect GitHub
                </a>
              </div>
            )}

            {/* REPOSITORY DISCOVERY & SELECTION SECTION */}
            <div className="border-t border-white/10 pt-5 space-y-4" data-testid="repositories-section">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-semibold text-white">Discovered Repositories</h4>
                  <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-300 border border-slate-700">
                    {totalRepos}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2.5">
                  <input
                    type="text"
                    value={repoSearch}
                    onChange={(e) => setRepoSearch(e.target.value)}
                    placeholder="Search repositories..."
                    className="px-2.5 py-1.5 rounded-lg text-xs bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors w-44 sm:w-56"
                    data-testid="repo-search-input"
                  />

                  <button
                    type="button"
                    onClick={handleSyncRepositories}
                    disabled={isSyncingRepos}
                    className="lens-button-primary text-xs px-3.5 py-1.5 font-medium flex items-center gap-1.5 disabled:opacity-50"
                    data-testid="sync-repos-btn"
                  >
                    {isSyncingRepos ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>Syncing...</span>
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        <span>Sync Repositories</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSyncActivities()}
                    disabled={isSyncingActivities || selectedRepos.length === 0}
                    className="lens-button-primary text-xs px-3.5 py-1.5 font-medium flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="sync-activities-btn"
                  >
                    {isSyncingActivities && !activitySyncRepoId ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>Syncing Activities...</span>
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                        </svg>
                        <span>Sync Activities ({selectedRepos.length})</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Repository Error Banner */}
              {repoError && (
                <div
                  role="alert"
                  className="p-3 rounded-lg text-xs bg-rose-950/40 border border-rose-500/30 text-rose-200 flex items-center gap-2"
                  data-testid="repo-error-message"
                >
                  <svg className="w-4 h-4 shrink-0 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{repoError}</span>
                </div>
              )}

              {/* Activity Error Banner */}
              {activityError && (
                <div
                  role="alert"
                  className="p-3 rounded-lg text-xs bg-rose-950/40 border border-rose-500/30 text-rose-200 flex items-center justify-between gap-2"
                  data-testid="activity-error-message"
                >
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 shrink-0 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{activityError}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleSyncActivities()}
                    className="text-xs font-semibold text-rose-300 hover:text-white underline ml-2 shrink-0"
                    data-testid="retry-activities-btn"
                  >
                    Retry
                  </button>
                </div>
              )}

              {/* Repository Content Area */}
              {isLoadingRepos ? (
                <div className="space-y-2 animate-pulse" data-testid="repos-loading">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-16 rounded-lg bg-slate-900/60 border border-slate-800" />
                  ))}
                </div>
              ) : filteredRepos.length === 0 ? (
                <div
                  className="p-8 text-center rounded-xl border border-dashed border-slate-800 bg-slate-900/20 text-slate-400 space-y-2"
                  data-testid="repo-empty-state"
                >
                  <svg className="w-8 h-8 mx-auto text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                  </svg>
                  <p className="text-xs font-medium text-slate-300">
                    {repositories.length === 0
                      ? "No repositories discovered yet. Click 'Sync Repositories' to discover your GitHub repositories."
                      : "No repositories match your search filter."}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Discovering repositories imports metadata and prepares selection for future ingestion.
                  </p>
                </div>
              ) : (
                <div className="space-y-2 max-h-96 overflow-y-auto pr-1" data-testid="repo-list">
                  {filteredRepos.map((repo) => (
                    <div
                      key={repo.id}
                      className="p-3 rounded-lg border border-slate-800/80 bg-slate-900/40 hover:bg-slate-900/80 transition-colors flex flex-col gap-2"
                      data-testid={`repo-item-${repo.id}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3 min-w-0 flex-1">
                          <input
                            type="checkbox"
                            checked={repo.is_selected}
                            onChange={() => handleToggleSelect(repo)}
                            className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-600 focus:ring-cyan-500 cursor-pointer"
                            data-testid={`repo-checkbox-${repo.id}`}
                            aria-label={`Select ${repo.full_name}`}
                          />

                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <a
                                href={repo.html_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs font-semibold text-white hover:text-cyan-400 transition-colors truncate font-mono"
                                data-testid={`repo-name-${repo.id}`}
                              >
                                {repo.full_name}
                              </a>

                              {/* Badges */}
                              <span
                                className={`px-1.5 py-0.2 rounded text-[10px] font-mono border ${
                                  repo.is_private
                                    ? "bg-amber-950/30 text-amber-300 border-amber-800/40"
                                    : "bg-slate-800 text-slate-300 border-slate-700"
                                }`}
                              >
                                {repo.is_private ? "Private" : "Public"}
                              </span>

                              {repo.is_archived && (
                                <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-rose-950/30 text-rose-300 border border-rose-800/40">
                                  Archived
                                </span>
                              )}

                              {repo.is_fork && (
                                <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-purple-950/30 text-purple-300 border border-purple-800/40">
                                  Fork
                                </span>
                              )}

                              {repo.language && (
                                <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-blue-950/30 text-blue-300 border border-blue-800/40">
                                  {repo.language}
                                </span>
                              )}
                            </div>

                            {repo.description && (
                              <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">
                                {repo.description}
                              </p>
                            )}

                            <div className="flex flex-wrap items-center gap-4 mt-1.5 text-[10px] text-slate-500 font-mono">
                              {repo.default_branch && <span>Branch: {repo.default_branch}</span>}
                              {repo.last_synced_at && <span>Synced: {formatDate(repo.last_synced_at)}</span>}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Activity Ingestion Section */}
                      {repo.is_selected && (
                        <div className="flex flex-wrap items-center justify-between gap-2 mt-1 pt-2 border-t border-slate-800/60 text-[11px]" data-testid={`repo-activity-section-${repo.id}`}>
                          <div className="flex items-center gap-2">
                            <span className="text-slate-400">Activities:</span>
                            {renderActivityStatusBadge(repo)}
                            {(!repo.activity_sync_status || repo.activity_sync_status === "idle") && (
                              <span className="text-[10px] text-slate-500 font-mono" data-testid={`activity-status-${repo.id}`}>Idle</span>
                            )}
                          </div>

                          {repo.activity_sync_error && (
                            <div className="flex items-center gap-1.5 text-rose-400" data-testid={`repo-activity-error-${repo.id}`}>
                              <span className="text-[10px]">{repo.activity_sync_error}</span>
                              <button
                                type="button"
                                onClick={() => handleSyncActivities(repo.id)}
                                disabled={isSyncingActivities}
                                className="text-[10px] underline font-medium hover:text-white ml-1"
                                data-testid={`retry-repo-sync-${repo.id}`}
                              >
                                Retry
                              </button>
                            </div>
                          )}

                          {(() => {
                            const categoryCounts = getCategoryCounts(repo);
                            return categoryCounts.length > 0 ? (
                              <div className="text-[10px] font-mono text-slate-400 flex flex-wrap items-center gap-1.5" data-testid={`repo-counts-${repo.id}`}>
                                {categoryCounts.map(([type, count]) => (
                                  <span key={type} className="bg-slate-800/90 px-1.5 py-0.5 rounded text-slate-300 border border-slate-700/50">
                                    {type}: {String(count)}
                                  </span>
                                ))}
                              </div>
                            ) : null;
                          })()}

                          {repo.activity_last_synced_at && (
                            <span className="text-[10px] text-slate-500 font-mono ml-auto" data-testid={`repo-activity-synced-at-${repo.id}`}>
                              Ingested: {formatDate(repo.activity_last_synced_at)}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* INGESTED ACTIVITIES PREVIEW */}
              <div className="border-t border-white/5 pt-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h5 className="text-xs font-semibold text-slate-300">Ingested Activity Stream</h5>
                    <span className="text-[11px] text-slate-500">(Stage 15 Preview)</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const next = !showActivityDrawer;
                      setShowActivityDrawer(next);
                      if (next && activities.length === 0) {
                        handleLoadActivities();
                      }
                    }}
                    className="text-xs font-medium text-cyan-400 hover:text-cyan-300 transition-colors flex items-center gap-1"
                    data-testid="toggle-activities-btn"
                  >
                    {showActivityDrawer ? "Hide Activities" : "View Recent Activities"}
                    <svg className={`w-3.5 h-3.5 transition-transform ${showActivityDrawer ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                </div>

                {showActivityDrawer && (
                  <div className="mt-3 space-y-3 bg-slate-900/30 p-3.5 rounded-xl border border-slate-800" data-testid="activities-drawer">
                    {/* Activity Filter Buttons */}
                    <div className="flex flex-wrap items-center gap-2">
                      {["", "pull_request", "issue", "commit", "review"].map((type) => (
                        <button
                          key={type || "all"}
                          type="button"
                          onClick={() => {
                            setActivityTypeFilter(type);
                            handleLoadActivities(type);
                          }}
                          className={`px-2 py-1 rounded text-[11px] font-mono transition-colors ${
                            activityTypeFilter === type
                              ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40"
                              : "bg-slate-800/60 text-slate-400 hover:text-white border border-slate-700/50"
                          }`}
                          data-testid={`activity-filter-${type || "all"}`}
                        >
                          {type ? type.replace("_", " ") : "All"}
                        </button>
                      ))}
                    </div>

                    {isLoadingActivities ? (
                      <div className="py-6 text-center text-xs text-slate-500 animate-pulse" data-testid="activities-loading">
                        Loading ingested activities...
                      </div>
                    ) : activities.length === 0 ? (
                      <div className="py-6 text-center text-xs text-slate-500" data-testid="activities-empty">
                        No activities ingested yet. Select a repository and click &apos;Sync Activities&apos;.
                      </div>
                    ) : (
                      <div className="space-y-2 max-h-72 overflow-y-auto pr-1" data-testid="activities-list">
                        {activities.map((act) => (
                          <div
                            key={act.id}
                            className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 flex items-start justify-between gap-3 text-xs"
                            data-testid={`activity-item-${act.id}`}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-800 text-cyan-300 border border-slate-700">
                                  {act.activity_type.replace("_", " ")}
                                </span>
                                {act.state && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800/80 text-slate-300 border border-slate-700/50">
                                    {act.state}
                                  </span>
                                )}
                                {act.author_login && (
                                  <span className="text-[11px] text-slate-400 font-mono">
                                    @{act.author_login}
                                  </span>
                                )}
                                {act.source_created_at && (
                                  <span className="text-[10px] text-slate-500 font-mono ml-auto">
                                    {formatDate(act.source_created_at)}
                                  </span>
                                )}
                              </div>
                              <div className="mt-1">
                                {act.html_url ? (
                                  <a
                                    href={act.html_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-white hover:text-cyan-400 font-medium truncate block transition-colors"
                                    data-testid={`activity-title-${act.id}`}
                                  >
                                    {act.title || act.external_id}
                                  </a>
                                ) : (
                                  <span className="text-white font-medium truncate block" data-testid={`activity-title-${act.id}`}>
                                    {act.title || act.external_id}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* DISCONNECTED STATE */
          <div className="lens-card p-6 space-y-4 bg-[#0d121e]" data-testid="github-disconnected-card">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div className="w-11 h-11 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-slate-400">
                  <svg className="w-6 h-6 fill-current" viewBox="0 0 24 24">
                    <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                  </svg>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-white text-base">GitHub</h3>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-slate-700/40 text-slate-400 border border-slate-600/30" data-testid="status-badge-disconnected">
                      Not Connected
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Connect your account to enable future repository, issue, and PR knowledge indexing.
                  </p>
                </div>
              </div>

              {/* Direct Server OAuth Navigation Link */}
              <a
                href={apiClient.getGitHubConnectUrl()}
                className="lens-button-primary text-xs px-4 py-2 font-medium"
                data-testid="connect-github-btn"
              >
                Connect GitHub
              </a>
            </div>

            <p className="text-[11px] text-slate-500 pt-2 border-t border-white/5">
              Permissions requested: <code className="text-slate-400 font-mono">read:user, repo</code>. GitHub&apos;s <code className="text-slate-400 font-mono">repo</code> scope grants full read and write access to your public and private repositories.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-xs text-slate-500">Loading settings...</div>}>
      <SettingsContent />
    </Suspense>
  );
}
