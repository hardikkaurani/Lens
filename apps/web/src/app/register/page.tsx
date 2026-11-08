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

function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawRedirect = searchParams.get("redirect");
  const redirectTarget = getSafeRedirect(rawRedirect);

  const { register, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [accountCreated, setAccountCreated] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);

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
    if (password.length < 8) {
      setClientError("Password must be at least 8 characters long.");
      return false;
    }

    if (password !== confirmPassword) {
      setClientError("Passwords do not match.");
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

    let created = false;
    try {
      await register(email.trim(), password);
      created = true;
      setAccountCreated(true);
      await login(email.trim(), password);
      router.push(redirectTarget);
      router.refresh();
    } catch (err) {
      if (created) {
        setServerError(
          "Your account has been created successfully, but automatic sign-in could not be completed. Please sign in below."
        );
      } else if (err instanceof ApiClientError) {
        if (err.status === 409) {
          setServerError("An account with this email address already exists. Please sign in instead.");
        } else if (err.status === 422) {
          setServerError(err.message || "Invalid registration details. Please verify your email and password.");
        } else {
          setServerError(err.message || "Failed to create account. Please try again.");
        }
      } else if (err instanceof Error) {
        setServerError(err.message);
      } else {
        setServerError("An unexpected error occurred during registration. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full flex flex-col lg:flex-row bg-[#0B1A2F] overflow-hidden">
      {/* Left Column: Brand & Value Proposition (Desktop) */}
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
            Private Architecture
          </div>
          <h2 className="text-4xl xl:text-5xl font-normal tracking-tight text-white leading-[1.15]">
            Create your private knowledge vault.
          </h2>
          <p className="text-lg text-slate-300 font-normal leading-relaxed">
            Every capture is encrypted, vector-indexed, and partitioned by tenant isolation. Build your institutional research repository with absolute security.
          </p>
        </div>

        <div className="pt-8 border-t border-white/10 flex items-center justify-between text-xs text-slate-400">
          <span>Row-Level Tenant Isolation</span>
          <span>Zero Third-Party Training</span>
        </div>
      </div>

      {/* Right Column: Registration Card */}
      <div className="relative z-10 flex-1 flex flex-col justify-center items-center p-6 sm:p-12 lg:p-16 lg:bg-white min-h-screen">
        <div className="w-full max-w-md mx-auto space-y-7 bg-white p-8 sm:p-10 rounded-[8px] lg:rounded-none border border-[#E5E7EB] lg:border-none shadow-xl lg:shadow-none">
          {/* Header */}
          <div className="flex flex-col items-center lg:items-start text-center lg:text-left space-y-2">
            <div className="lg:hidden mb-2">
              <Link href="/">
                <LensLogo size="md" subtitle="Personal Knowledge" theme="light" priority />
              </Link>
            </div>
            <h1 className="text-2xl sm:text-3xl font-normal text-[#000000] tracking-tight">
              Create your LENS Account
            </h1>
            <p className="text-sm text-[#5B6472] leading-normal">
              Private, isolated personal knowledge archive with end-to-end multi-tenancy.
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
              <div className="flex-1 font-medium">
                <p>{clientError || serverError}</p>
                {accountCreated && (
                  <div className="mt-2.5">
                    <Link
                      href={`/login?redirect=${encodeURIComponent(redirectTarget)}`}
                      className="inline-flex items-center px-3 py-1.5 bg-[#2075CC] hover:bg-[#115AA4] text-white text-xs font-semibold rounded-[4px] transition-colors"
                      data-testid="signin-after-register-btn"
                    >
                      Sign In with Credentials
                    </Link>
                  </div>
                )}
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div>
              <label
                htmlFor="register-email"
                className="block text-xs font-medium uppercase tracking-wider text-[#5B6472] mb-1.5"
              >
                Email Address
              </label>
              <input
                id="register-email"
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
                  htmlFor="register-password"
                  className="block text-xs font-medium uppercase tracking-wider text-[#5B6472]"
                >
                  Password (min. 8 characters)
                </label>
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="text-xs text-[#115AA4] hover:text-[#2075CC] font-medium focus:outline-none focus-visible:underline"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <input
                id="register-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={submitting}
                className="lens-input"
              />
            </div>

            <div>
              <label
                htmlFor="register-confirm-password"
                className="block text-xs font-medium uppercase tracking-wider text-[#5B6472] mb-1.5"
              >
                Confirm Password
              </label>
              <input
                id="register-confirm-password"
                name="confirmPassword"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                disabled={submitting}
                className="lens-input"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="lens-button-primary w-full mt-3"
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
                  <span>Creating account...</span>
                </>
              ) : (
                <span>Create account</span>
              )}
            </button>
          </form>

          <div className="pt-4 border-t border-[#E5E7EB] text-center text-sm text-[#5B6472]">
            Already have an account?{" "}
            <Link
              href={`/login${rawRedirect ? `?redirect=${encodeURIComponent(rawRedirect)}` : ""}`}
              className="font-medium text-[#115AA4] hover:text-[#2075CC] underline underline-offset-2 transition-colors"
            >
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#0B1A2F] flex items-center justify-center p-4">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-[#2075CC]" />
        </div>
      }
    >
      <RegisterForm />
    </Suspense>
  );
}
