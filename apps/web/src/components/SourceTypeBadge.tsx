import React from "react";
import type { SourceType } from "@/types/api";
import { formatSourceType } from "@/lib/format";

interface SourceTypeBadgeProps {
  sourceType: SourceType | string;
}

export function SourceTypeBadge({ sourceType }: SourceTypeBadgeProps) {
  const isUrl = sourceType === "url";
  const isPdf = sourceType === "pdf" || sourceType === "file";
  const label = formatSourceType(sourceType);

  let badgeColor = "bg-slate-700/40 text-slate-300 border border-slate-600/30";
  if (isUrl) {
    badgeColor = "bg-indigo-500/10 text-indigo-300 border border-indigo-500/20";
  } else if (isPdf) {
    badgeColor = "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20";
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
      ) : (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      )}
      <span>{label}</span>
    </span>
  );
}
