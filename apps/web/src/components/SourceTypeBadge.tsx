import React from "react";
import type { SourceType } from "@/types/api";
import { formatSourceType } from "@/lib/format";

interface SourceTypeBadgeProps {
  sourceType: SourceType | string;
}

export function SourceTypeBadge({ sourceType }: SourceTypeBadgeProps) {
  const normType = sourceType.toLowerCase();
  const isUrl = normType === "url";
  const isPdf = normType === "pdf" || normType === "file";
  const isPR = normType === "pull_request";
  const isIssue = normType === "issue";
  const isCommit = normType === "commit";
  const isReview = normType === "review";
  const isGitHub = normType === "github" || isPR || isIssue || isCommit || isReview;
  const label = formatSourceType(sourceType);

  let badgeColor = "bg-slate-700/40 text-slate-300 border border-slate-600/30";
  if (isUrl) {
    badgeColor = "bg-indigo-500/10 text-indigo-300 border border-indigo-500/20";
  } else if (isPdf) {
    badgeColor = "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20";
  } else if (isPR) {
    badgeColor = "bg-purple-500/10 text-purple-300 border border-purple-500/20";
  } else if (isIssue) {
    badgeColor = "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20";
  } else if (isCommit) {
    badgeColor = "bg-cyan-500/10 text-cyan-300 border border-cyan-500/20";
  } else if (isReview) {
    badgeColor = "bg-amber-500/10 text-amber-300 border border-amber-500/20";
  } else if (isGitHub) {
    badgeColor = "bg-slate-500/10 text-slate-300 border border-slate-500/20";
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium ${badgeColor}`}
      data-testid={`source-type-badge-${sourceType}`}
    >
      {isUrl ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
      ) : isPdf ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
      ) : isPR ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <circle cx="18" cy="18" r="3" strokeWidth={2} />
          <circle cx="6" cy="6" r="3" strokeWidth={2} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 9v12m12-9a9 9 0 00-9-9" />
        </svg>
      ) : isIssue ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="9" strokeWidth={2} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01" />
        </svg>
      ) : isCommit ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="4" strokeWidth={2} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M1.5 12h6.5m8 0h6.5" />
        </svg>
      ) : isReview ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ) : (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      )}
      <span>{label}</span>
    </span>
  );
}
