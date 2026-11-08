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
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-[#2075CC]" />
      </div>
    );
  }

  if (verificationError && !isAuthenticated) {
    return (
      <div
        className="flex flex-col items-center justify-center min-h-[50vh] p-6 text-center"
        data-testid="auth-verification-error"
      >
        <div className="max-w-md p-8 bg-white border border-[#E5E7EB] rounded-[8px] space-y-4 shadow-sm">
          <div className="w-10 h-10 mx-auto rounded-[4px] bg-[#FEF3C7] border border-[#FDE68A] flex items-center justify-center text-[#B45309]">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-[#000000]">Authentication Service Unavailable</h2>
          <p className="text-sm text-[#5B6472] leading-relaxed">
            Unable to verify your session due to a connection or server error: {verificationError}
          </p>
          <div className="flex gap-3 justify-center pt-2">
            <button
              type="button"
              onClick={() => retryVerification()}
              className="lens-button-primary text-xs h-10 px-4"
              data-testid="retry-verification-btn"
            >
              Retry Connection
            </button>
            <button
              type="button"
              onClick={() => router.push("/login")}
              className="lens-button-secondary text-xs h-10 px-4"
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
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-[#2075CC]" />
        </div>
      }
    >
      <RouteRedirectGuard>{children}</RouteRedirectGuard>
    </React.Suspense>
  );
}
