import React from "react";

interface ErrorMessageProps {
  message: string;
  onRetry?: () => void;
  title?: string;
}

export function ErrorMessage({ message, onRetry, title = "Something went wrong" }: ErrorMessageProps) {
  return (
    <div
      role="alert"
      className="p-4 rounded-[4px] border border-[#FFCDD2] bg-[#FFEBEE] text-[#C62828] flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-fadeIn"
    >
      <div className="flex items-start gap-3">
        <svg
          className="w-5 h-5 text-[#C62828] shrink-0 mt-0.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <div>
          <h4 className="text-sm font-semibold text-[#000000]">{title}</h4>
          <p className="text-xs text-[#5B6472] mt-0.5">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="self-start sm:self-auto px-3.5 py-1.5 text-xs font-medium rounded-[4px] bg-white hover:bg-slate-50 text-[#C62828] border border-[#FFCDD2] transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
