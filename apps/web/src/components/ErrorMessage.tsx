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
      className="p-4 rounded-xl border border-rose-500/30 bg-rose-950/20 text-rose-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
    >
      <div className="flex items-start gap-3">
        <svg
          className="w-5 h-5 text-rose-400 shrink-0 mt-0.5"
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
          <h4 className="text-sm font-semibold text-rose-100">{title}</h4>
          <p className="text-xs text-rose-300/90 mt-0.5">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="self-start sm:self-auto px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/30 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
