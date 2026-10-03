"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiClient, ApiClientError } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import type { GitHubConnectionStatus } from "@/types/api";
import { ErrorMessage } from "@/components/ErrorMessage";

export function SettingsContent() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<GitHubConnectionStatus | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isDisconnecting, setIsDisconnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);

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
          <div className="lens-card p-6 space-y-5 bg-[#0d121e]" data-testid="github-connected-card">
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
              Permissions requested: <code className="text-slate-400 font-mono">read:user</code> (read-only profile verification). No repository or write permissions are required at this stage.
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
