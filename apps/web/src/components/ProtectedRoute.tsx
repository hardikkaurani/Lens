"use client";

import React, { useEffect } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

function RouteRedirectGuard({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, verificationError, retryVerification } = useAuth();
  const router = useRouter();
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !verificationError) {
      const search = searchParams?.toString();
      const fullPath = search ? `${pathname}?${search}` : pathname;
      const redirectUrl = fullPath ? `/login?redirect=${encodeURIComponent(fullPath)}` : "/login";
      router.push(redirectUrl);
    }
  }, [isLoading, isAuthenticated, verificationError, router, pathname, searchParams]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]" data-testid="auth-loading">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-500" />
      </div>
    );
  }

  if (verificationError && !isAuthenticated) {
    return (
      <div
        className="flex flex-col items-center justify-center min-h-[50vh] p-6 text-center"
        data-testid="auth-verification-error"
      >
        <div className="max-w-md p-6 bg-slate-900 border border-amber-500/30 rounded-xl space-y-4">
          <h2 className="text-lg font-semibold text-white">Authentication Service Unavailable</h2>
          <p className="text-sm text-slate-400">
            Unable to verify your session due to a connection or server error: {verificationError}
          </p>
          <div className="flex gap-3 justify-center pt-2">
            <button
              type="button"
              onClick={() => retryVerification()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors cursor-pointer"
              data-testid="retry-verification-btn"
            >
              Retry Connection
            </button>
            <button
              type="button"
              onClick={() => router.push("/login")}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium rounded-lg transition-colors cursor-pointer"
            >
              Go to Sign In
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  return (
    <React.Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[50vh]" data-testid="auth-loading">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-500" />
        </div>
      }
    >
      <RouteRedirectGuard>{children}</RouteRedirectGuard>
    </React.Suspense>
  );
}
