"use client";

import React, { Suspense, useState, useRef, useEffect } from "react";
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
  const [videoFailed, setVideoFailed] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);

  // Gracefully handle playback failures or prefers-reduced-motion
  useEffect(() => {
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
      if (mediaQuery.matches && videoRef.current) {
        videoRef.current.pause();
      }
    }
  }, []);

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
    <div className="relative min-h-screen w-full flex flex-col lg:flex-row bg-[#0B1A2F] overflow-hidden">
      {/* Left Column: Institutional Brand & Cinematic Vision (Desktop) */}
      <div className="relative z-10 hidden lg:flex flex-col justify-between w-7/12 p-16 xl:p-24 text-white overflow-hidden bg-[#0B1A2F]">
        {/* Dedicated Cinematic Background Video Container */}
        <div className="absolute inset-0 w-full h-full overflow-hidden pointer-events-none -z-10" aria-hidden="true">
          {!videoFailed ? (
            <video
              ref={videoRef}
              autoPlay
              muted
              loop
              playsInline
              poster="/videos/lens-auth-poster.jpg"
              onError={() => setVideoFailed(true)}
              data-testid="auth-video-bg"
              className="w-full h-full object-cover object-center opacity-75"
            >
              <source src="/videos/lens-auth-bg.mp4" type="video/mp4" />
            </video>
          ) : (
            <div
              className="w-full h-full bg-cover bg-center opacity-40"
              style={{ backgroundImage: "url('/videos/lens-auth-poster.jpg')" }}
            />
          )}
          {/* Calibrated Institutional Navy Overlay:
              Ensures high WCAG AAA contrast for typography while preserving
              vivid architectural reflections and natural sky movement */}
          <div className="absolute inset-0 bg-gradient-to-t from-[#0B1A2F]/90 via-[#0B1A2F]/60 to-[#0B1A2F]/45" />
          <div className="absolute inset-0 bg-[#0B1A2F]/20" />
        </div>

        <div>
          <Link href="/" className="inline-block group">
            <LensLogo size="lg" subtitle="Personal Knowledge" theme="dark" priority />
          </Link>
        </div>

        <div className="space-y-6 max-w-xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-[4px] bg-[#2075CC]/20 border border-[#2075CC]/30 text-[#7BB8FF] text-xs font-medium tracking-wider uppercase">
            Institutional Knowledge System
          </div>
          <h2 className="text-4xl xl:text-5xl font-normal tracking-tight text-white leading-[1.15]">
            Knowledge captured with precision.
          </h2>
          <p className="text-lg text-slate-300 font-normal leading-relaxed">
            A secure, private intelligence workspace designed for unstructured web research, document indexing, and enterprise-grade synthesis.
          </p>
        </div>

        <div className="pt-8 border-t border-white/10 flex items-center justify-between text-xs text-slate-400">
          <span>Enterprise End-to-End Encryption</span>
          <span>Single-Tenant Isolated Data Store</span>
        </div>
      </div>

      {/* Right Column: Clean White Authentication Surface */}
      <div className="relative z-10 flex-1 flex flex-col justify-center items-center p-6 sm:p-12 lg:p-16 lg:bg-white min-h-screen">
        <div className="w-full max-w-md mx-auto space-y-8 bg-white p-8 sm:p-10 rounded-[8px] lg:rounded-none border border-[#E5E7EB] lg:border-none shadow-xl lg:shadow-none">
          {/* Brand header on mobile / small screens */}
          <div className="flex flex-col items-center lg:items-start text-center lg:text-left space-y-3">
            <div className="lg:hidden mb-2">
              <Link href="/">
                <LensLogo size="md" subtitle="Personal Knowledge" theme="light" priority />
              </Link>
            </div>
            <h1 className="text-2xl sm:text-3xl font-normal text-[#000000] tracking-tight">
              Sign in to LENS
            </h1>
            <p className="text-sm text-[#5B6472] leading-normal">
              Access your private captures, search indices, and research notes.
            </p>
          </div>

          {/* Error notifications */}
          {(clientError || serverError) && (
            <div
              role="alert"
              className="p-3.5 rounded-[4px] bg-[#FFEBEE] border border-[#FFCDD2] text-[#C62828] text-sm flex items-start gap-2.5 animate-fadeIn"
            >
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
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <div className="flex-1 font-medium">{clientError || serverError}</div>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-5">
            <div>
              <label
                htmlFor="email"
                className="block text-xs font-medium uppercase tracking-wider text-[#5B6472] mb-1.5"
              >
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
                className="lens-input"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label
                  htmlFor="password"
                  className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]"
                >
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="text-xs text-[#115AA4] hover:text-[#2075CC] font-medium focus:outline-none focus-visible:underline"
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
                  className="lens-input"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="lens-button-primary w-full mt-4"
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

          <div className="pt-4 border-t border-[#E5E7EB] text-center text-sm text-[#5B6472]">
            Don&apos;t have an account?{" "}
            <Link
              href="/register"
              className="font-medium text-[#115AA4] hover:text-[#2075CC] underline underline-offset-2 transition-colors"
            >
              Create an account
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#0B1A2F] flex items-center justify-center p-4">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-[#2075CC]" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
