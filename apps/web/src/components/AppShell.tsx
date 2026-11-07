"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { LensLogo } from "./LensLogo";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState<"checking" | "connected" | "disconnected">("checking");

  useEffect(() => {
    let isMounted = true;
    apiClient
      .getHealth()
      .then((res) => {
        if (isMounted) {
          setBackendStatus(res.status === "ok" ? "connected" : "disconnected");
        }
      })
      .catch(() => {
        if (isMounted) {
          setBackendStatus("disconnected");
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // For dedicated auth pages, render clean centered layout without navigation chrome
  if (pathname === "/login" || pathname === "/register") {
    return (
      <div className="min-h-screen bg-[#0a0d14] text-slate-100 flex flex-col justify-center items-center p-4">
        {children}
      </div>
    );
  }

  const navItems = [
    {
      href: "/captures",
      label: "Captures",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      active: pathname === "/captures" || pathname.startsWith("/captures/"),
    },
    {
      href: "/search",
      label: "Search",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      ),
      active: pathname === "/search",
    },
    {
      href: "/captures/new",
      label: "New Capture",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
      ),
      active: pathname === "/captures/new",
    },
    {
      href: "/settings",
      label: "Settings",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
      active: pathname === "/settings" || pathname.startsWith("/settings/"),
    },
  ];

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#0a0d14] text-slate-100">
      {/* Mobile Top Header */}
      <header className="md:hidden flex items-center justify-between p-4 border-b border-white/10 bg-[#111726]/90 backdrop-blur sticky top-0 z-30">
        <Link href="/captures" className="flex items-center group">
          <LensLogo size="sm" subtitle="WORKSPACE" />
        </Link>
        <button
          type="button"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          aria-label="Toggle navigation menu"
          aria-expanded={mobileMenuOpen}
        >
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            {mobileMenuOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </header>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <nav
          className="md:hidden p-4 border-b border-white/10 bg-[#111726] space-y-1.5 z-20"
          aria-label="Mobile Navigation"
        >
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileMenuOpen(false)}
              className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                item.active
                  ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/30"
                  : "text-slate-300 hover:text-white hover:bg-slate-800/50"
              }`}
            >
              {item.icon}
              <span>{item.label}</span>
            </Link>
          ))}
          {/* Mobile Auth actions */}
          <div className="pt-3 border-t border-white/5 space-y-2">
            {isAuthenticated && user ? (
              <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-slate-900/60 border border-white/5">
                <span className="text-xs text-slate-300 truncate" title={user.email}>
                  {user.email}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    logout();
                  }}
                  className="text-xs text-rose-400 hover:text-rose-300 font-medium px-2 py-1 rounded bg-rose-950/40 border border-rose-800/30"
                >
                  Sign out
                </button>
              </div>
            ) : !isLoading ? (
              <Link
                href="/login"
                onClick={() => setMobileMenuOpen(false)}
                className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg text-xs font-medium bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600/30 border border-indigo-500/30 transition-colors"
              >
                Sign in
              </Link>
            ) : null}
          </div>

          <div className="pt-2 border-t border-white/5 flex items-center gap-2 text-xs text-slate-400">
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus === "connected"
                  ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]"
                  : backendStatus === "checking"
                  ? "bg-amber-400"
                  : "bg-rose-400"
              }`}
            />
            <span>
              Backend: {backendStatus === "connected" ? "Connected" : backendStatus === "checking" ? "Checking" : "Offline"}
            </span>
          </div>
        </nav>
      )}

      {/* Desktop Sidebar */}
      <aside className="hidden md:flex flex-col w-64 border-r border-white/10 bg-[#111726] p-5 shrink-0 sticky top-0 h-screen justify-between">
        <div className="space-y-6">
          {/* Logo / Branding */}
          <Link href="/captures" className="flex items-center group">
            <LensLogo size="lg" subtitle="Personal Knowledge" priority />
          </Link>

          {/* Nav links */}
          <nav className="space-y-1" aria-label="Main Navigation">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  item.active
                    ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 shadow-sm"
                    : "text-slate-300 hover:text-white hover:bg-slate-800/40"
                }`}
              >
                <span className={item.active ? "text-indigo-400" : "text-slate-400"}>{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>

        {/* User profile & Backend health footer */}
        <div className="pt-4 border-t border-white/10 space-y-3">
          {isAuthenticated && user ? (
            <div className="flex flex-col gap-2">
              <div className="px-2.5 py-2 rounded-lg bg-slate-900/60 border border-white/5 flex items-center justify-between">
                <div className="truncate text-xs">
                  <p className="text-slate-400 text-[10px] uppercase font-semibold tracking-wider">Signed in as</p>
                  <p className="text-slate-200 font-medium truncate" title={user.email}>{user.email}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => logout()}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs font-medium text-rose-300 hover:text-rose-200 hover:bg-rose-950/40 border border-transparent hover:border-rose-800/40 transition-colors"
                aria-label="Sign out"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                <span>Sign out</span>
              </button>
            </div>
          ) : !isLoading ? (
            <Link
              href="/login"
              className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg text-xs font-medium bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600/30 border border-indigo-500/30 transition-colors"
            >
              <span>Sign in</span>
            </Link>
          ) : null}

          <div className="flex items-center justify-between px-2 text-xs text-slate-400">
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  backendStatus === "connected"
                    ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]"
                    : backendStatus === "checking"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-rose-400"
                }`}
              />
              <span className="font-mono text-[11px]">
                {backendStatus === "connected"
                  ? "API Online"
                  : backendStatus === "checking"
                  ? "Connecting..."
                  : "API Offline"}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Workspace Viewport */}
      <main className="flex-1 p-4 sm:p-6 md:p-8 max-w-5xl w-full mx-auto overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
