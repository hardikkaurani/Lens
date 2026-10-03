import React from "react";

export function LoadingCardSkeleton() {
  return (
    <div className="lens-card p-5 space-y-3 animate-shimmer" data-testid="loading-skeleton">
      <div className="flex items-center justify-between">
        <div className="h-4 bg-slate-800 rounded w-24" />
        <div className="h-4 bg-slate-800 rounded-full w-28" />
      </div>
      <div className="h-5 bg-slate-700 rounded w-3/4" />
      <div className="h-4 bg-slate-800 rounded w-full" />
      <div className="h-4 bg-slate-800 rounded w-2/3" />
      <div className="h-3 bg-slate-900 rounded w-32 pt-1" />
    </div>
  );
}

export function LoadingListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }).map((_, idx) => (
        <LoadingCardSkeleton key={idx} />
      ))}
    </div>
  );
}
