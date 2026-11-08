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

  // For dedicated auth pages, render full-bleed without navigation chrome
  if (pathname === "/login" || pathname === "/register") {
    return <div className="min-h-screen w-full bg-[#0B1A2F] text-slate-100">{children}</div>;
  }

  const navItems = [
    {
      href: "/captures",
      label: "Captures",
      icon: (
        <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      active: pathname === "/captures" || pathname.startsWith("/captures/"),
    },
    {
      href: "/search",
      label: "Search",
      icon: (
        <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      ),
      active: pathname === "/search",
    },
    {
      href: "/captures/new",
      label: "New Capture",
      icon: (
        <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 4v16m8-8H4" />
        </svg>
      ),
      active: pathname === "/captures/new",
    },
    {
      href: "/settings",
      label: "Settings",
      icon: (
        <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
      active: pathname === "/settings" || pathname.startsWith("/settings/"),
    },
  ];

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#F8FAFC] text-[#000000]">
      {/* Mobile Top Header */}
      <header className="md:hidden flex items-center justify-between px-5 py-3.5 border-b border-[#E5E7EB] bg-white sticky top-0 z-30 shadow-xs">
        <Link href="/captures" className="flex items-center group">
          <LensLogo size="sm" subtitle="WORKSPACE" theme="light" />
        </Link>
        <button
          type="button"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-[4px] text-[#5B6472] hover:text-[#000000] hover:bg-[#F1F5F9] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#2075CC]"
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
          className="md:hidden p-5 border-b border-[#E5E7EB] bg-white space-y-1.5 z-20 shadow-sm"
          aria-label="Mobile Navigation"
        >
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileMenuOpen(false)}
              className={`flex items-center gap-3 px-3.5 py-2.5 rounded-[4px] text-sm font-medium transition-colors ${
                item.active
                  ? "bg-[#EFF6FF] text-[#2075CC] font-semibold"
                  : "text-[#5B6472] hover:text-[#000000] hover:bg-[#F8FAFC]"
              }`}
            >
              {item.icon}
              <span>{item.label}</span>
            </Link>
          ))}

          {/* Mobile Auth actions */}
          <div className="pt-4 mt-2 border-t border-[#E5E7EB] space-y-2">
            {isAuthenticated && user ? (
              <div className="flex items-center justify-between p-2.5 rounded-[4px] bg-[#F8FAFC] border border-[#E5E7EB]">
                <span className="text-xs text-[#5B6472] truncate max-w-[200px]" title={user.email}>
                  {user.email}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    logout();
                  }}
                  className="text-xs text-[#C62828] hover:underline font-medium px-2 py-1 rounded-[4px] border border-[#FFCDD2] bg-[#FFEBEE]"
                >
                  Sign out
                </button>
              </div>
            ) : !isLoading ? (
              <Link
                href="/login"
                onClick={() => setMobileMenuOpen(false)}
                className="lens-button-primary w-full text-xs h-10"
              >
                Sign in
              </Link>
            ) : null}
          </div>

          <div className="pt-3 border-t border-[#E5E7EB] flex items-center gap-2 text-xs text-[#5B6472]">
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus === "connected"
                  ? "bg-[#10B981]"
                  : backendStatus === "checking"
                  ? "bg-[#F59E0B]"
                  : "bg-[#C62828]"
              }`}
            />
            <span className="font-mono text-[11px]">
              {backendStatus === "connected" ? "API Online" : backendStatus === "checking" ? "Connecting..." : "API Offline"}
            </span>
          </div>
        </nav>
      )}

      {/* Desktop Sidebar: Clean, Institutional, White Surface */}
      <aside className="hidden md:flex flex-col w-64 border-r border-[#E5E7EB] bg-white p-6 shrink-0 sticky top-0 h-screen justify-between z-20">
        <div className="space-y-8">
          {/* Logo / Branding */}
          <Link href="/captures" className="flex items-center group">
            <LensLogo size="md" subtitle="Personal Knowledge" theme="light" priority />
          </Link>

          {/* Nav links */}
          <nav className="space-y-1" aria-label="Main Navigation">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3.5 py-2.5 rounded-[4px] text-sm transition-colors ${
                  item.active
                    ? "bg-[#EFF6FF] text-[#2075CC] font-semibold border-l-2 border-[#2075CC]"
                    : "text-[#5B6472] hover:text-[#000000] hover:bg-[#F8FAFC] font-medium"
                }`}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>

        {/* User Session & System Health */}
        <div className="pt-6 border-t border-[#E5E7EB] space-y-4">
          {isAuthenticated && user ? (
            <div className="space-y-2">
              <div className="px-2">
                <p className="text-[11px] font-medium uppercase tracking-wider text-[#5B6472]">Signed in as</p>
                <p className="text-xs font-semibold text-[#0B1A2F] truncate" title={user.email}>
                  {user.email}
                </p>
              </div>
              <button
                type="button"
                onClick={() => logout()}
                className="flex items-center gap-2 w-full px-2.5 py-1.5 rounded-[4px] text-xs font-medium text-[#5B6472] hover:text-[#C62828] hover:bg-[#FFEBEE] transition-colors"
                aria-label="Sign out"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                <span>Sign out</span>
              </button>
            </div>
          ) : !isLoading ? (
            <Link
              href="/login"
              className="lens-button-primary w-full text-xs h-10"
            >
              <span>Sign in</span>
            </Link>
          ) : null}

          {/* System Health */}
          <div className="flex items-center justify-between px-2 pt-2 border-t border-[#E5E7EB] text-xs text-[#5B6472]">
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  backendStatus === "connected"
                    ? "bg-[#10B981]"
                    : backendStatus === "checking"
                    ? "bg-[#F59E0B] animate-pulse"
                    : "bg-[#C62828]"
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
      <main className="flex-1 p-6 sm:p-8 md:p-10 max-w-6xl w-full mx-auto overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
