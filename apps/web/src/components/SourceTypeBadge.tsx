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

  let badgeColor = "bg-[#F8FAFC] text-[#475569] border border-[#E2E8F0]";
  if (isUrl) {
    badgeColor = "bg-[#EFF6FF] text-[#115AA4] border border-[#BFDBFE]";
  } else if (isPdf) {
    badgeColor = "bg-[#ECFDF5] text-[#065F46] text-emerald-300 border border-[#A7F3D0]";
  } else if (isPR) {
    badgeColor = "bg-[#F5F3FF] text-[#6D28D9] border border-[#DDD6FE]";
  } else if (isIssue) {
    badgeColor = "bg-[#ECFDF5] text-[#047857] border border-[#A7F3D0]";
  } else if (isCommit) {
    badgeColor = "bg-[#F0FDF4] text-[#15803D] border border-[#BBF7D0]";
  } else if (isReview) {
    badgeColor = "bg-[#FFFBEB] text-[#B45309] border border-[#FDE68A]";
  } else if (isGitHub) {
    badgeColor = "bg-[#F8FAFC] text-[#334155] border border-[#CBD5E1]";
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[4px] text-xs font-mono font-medium ${badgeColor}`}
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
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
        </svg>
      ) : isIssue ? (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ) : isCommit ? (
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
