"use client";

import React, { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { LensLogo } from "@/components/LensLogo";
import { ApiClientError } from "@/lib/api-client";

function getSafeRedirect(rawRedirect: string | null): string {
  if (!rawRedirect) return "/captures";
  try {
    const trimmed = rawRedirect.trim();
    if (
      trimmed.startsWith("/") &&
      !trimmed.startsWith("//") &&
      !trimmed.includes("\\") &&
      !trimmed.includes("\0")
    ) {
      const parsed = new URL(trimmed, "http://localhost");
      if (parsed.origin === "http://localhost") {
        return parsed.pathname + parsed.search + parsed.hash;
      }
    }
  } catch {
    // Malformed URI
  }
  return "/captures";
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawRedirect = searchParams.get("redirect");
  const redirectTarget = getSafeRedirect(rawRedirect);

  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const validate = (): boolean => {
    setClientError(null);
    setServerError(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setClientError("Email address is required.");
      return false;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(trimmedEmail)) {
      setClientError("Please enter a valid email address.");
      return false;
    }

    if (!password) {
      setClientError("Password is required.");
      return false;
    }
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    if (!validate()) return;

    setSubmitting(true);
    setServerError(null);

    try {
      await login(email.trim(), password);
      router.push(redirectTarget);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.status === 401) {
          setServerError("Invalid email or password. Please verify your credentials.");
        } else if (err.status === 429) {
          setServerError("Too many login attempts. Please wait a moment and try again.");
        } else {
          setServerError(err.message || "Failed to sign in. Please try again.");
        }
      } else if (err instanceof Error) {
        setServerError(err.message);
      } else {
        setServerError("An unexpected error occurred. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-md mx-auto">
      <div className="flex flex-col items-center mb-8">
        <Link href="/" className="mb-4 inline-block">
          <LensLogo size="lg" subtitle="Personal Knowledge" priority />
        </Link>
        <h1 className="text-2xl font-bold tracking-tight text-white mt-2">Sign in to LENS</h1>
        <p className="text-sm text-slate-400 mt-1 text-center">
          Access your private captures, search indices, and research notes.
        </p>
      </div>

      <div className="bg-[#111726] border border-white/10 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur">
        {(clientError || serverError) && (
          <div
            role="alert"
            className="mb-5 p-3.5 rounded-lg bg-rose-950/60 border border-rose-800/60 text-rose-200 text-sm flex items-start gap-2.5 animate-fadeIn"
          >
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
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <div className="flex-1 font-medium">{clientError || serverError}</div>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1.5">
              Email Address
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@domain.com"
              disabled={submitting}
              className="w-full px-3.5 py-2.5 rounded-lg bg-slate-900/80 border border-white/10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent text-sm transition-all"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="password" className="block text-xs font-semibold uppercase tracking-wider text-slate-300">
                Password
              </label>
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="text-xs text-indigo-400 hover:text-indigo-300 font-medium focus:outline-none"
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            <div className="relative">
              <input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={submitting}
                className="w-full px-3.5 py-2.5 rounded-lg bg-slate-900/80 border border-white/10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent text-sm transition-all"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full mt-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:opacity-60 text-white font-medium text-sm transition-all shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-[#111726]"
          >
            {submitting ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                <span>Signing in...</span>
              </>
            ) : (
              <span>Sign in</span>
            )}
          </button>
        </form>

        <div className="mt-6 pt-5 border-t border-white/5 text-center">
          <p className="text-xs text-slate-400">
            Don&apos;t have an account?{" "}
            <Link
              href={`/register${rawRedirect ? `?redirect=${encodeURIComponent(rawRedirect)}` : ""}`}
              className="text-indigo-400 hover:text-indigo-300 font-semibold transition-colors"
            >
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-[300px] flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
