import React from "react";

export function LoadingCardSkeleton() {
  return (
    <div className="lens-card p-6 space-y-3.5 animate-shimmer" data-testid="loading-skeleton">
      <div className="flex items-center justify-between">
        <div className="h-4 bg-slate-200 rounded-[3px] w-28" />
        <div className="h-4 bg-slate-100 rounded-[3px] w-24" />
      </div>
      <div className="h-5 bg-slate-200 rounded-[3px] w-3/4" />
      <div className="h-4 bg-slate-100 rounded-[3px] w-full" />
      <div className="h-4 bg-slate-100 rounded-[3px] w-2/3" />
      <div className="h-3 bg-slate-100 rounded-[3px] w-32 pt-1" />
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
