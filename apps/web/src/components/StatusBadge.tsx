import React from "react";
import type { ProcessingStatus } from "@/types/api";
import { formatProcessingStatus } from "@/lib/format";

interface StatusBadgeProps {
  status: ProcessingStatus;
  showIcon?: boolean;
}

export function StatusBadge({ status, showIcon = true }: StatusBadgeProps) {
  const label = formatProcessingStatus(status);

  let badgeStyle = "border-[#FDE68A] text-[#B45309] bg-[#FEF3C7]";
  let icon = (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );

  if (status === "processing") {
    badgeStyle = "border-[#BFDBFE] text-[#115AA4] bg-[#EFF6FF]";
    icon = (
      <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    );
  } else if (status === "completed") {
    badgeStyle = "border-[#A7F3D0] text-[#065F46] bg-[#ECFDF5]";
    icon = (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
      </svg>
    );
  } else if (status === "failed") {
    badgeStyle = "border-[#FECACA] text-[#C62828] bg-[#FFEBEE]";
    icon = (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-[4px] text-xs font-medium border ${badgeStyle}`}
      data-testid={`status-badge-${status}`}
      role="status"
    >
      {showIcon && icon}
      <span>{label}</span>
    </span>
  );
}
