import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { AppShell } from "@/components/AppShell";
import { apiClient } from "@/lib/api-client";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  usePathname: () => "/captures",
}));

describe("Application Shell & Navigation (Tests 1-3)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("1. renders app shell identity and branding", async () => {
    vi.spyOn(apiClient, "getHealth").mockResolvedValue({ status: "ok" });

    render(
      <AppShell>
        <div data-testid="test-content">Main Workspace Content</div>
      </AppShell>
    );

    expect(screen.getAllByText("LENS").length).toBeGreaterThan(0);
    expect(screen.getByText("Personal Knowledge")).toBeInTheDocument();
    expect(screen.getByTestId("test-content")).toHaveTextContent("Main Workspace Content");

    await waitFor(() => {
      expect(screen.getByText("API Online")).toBeInTheDocument();
    });
  });

  it("2. navigation renders accessible links for Captures, Search, and New Capture", () => {
    vi.spyOn(apiClient, "getHealth").mockResolvedValue({ status: "ok" });

    render(
      <AppShell>
        <div>Content</div>
      </AppShell>
    );

    const capturesLinks = screen.getAllByRole("link", { name: /Captures/i });
    expect(capturesLinks.length).toBeGreaterThan(0);
    expect(capturesLinks[0]).toHaveAttribute("href", "/captures");

    const searchLinks = screen.getAllByRole("link", { name: /Search/i });
    expect(searchLinks.length).toBeGreaterThan(0);
    expect(searchLinks[0]).toHaveAttribute("href", "/search");

    const newCaptureLinks = screen.getAllByRole("link", { name: /New Capture/i });
    expect(newCaptureLinks.length).toBeGreaterThan(0);
    expect(newCaptureLinks[0]).toHaveAttribute("href", "/captures/new");
  });

  it("3. responsive layout provides interactive mobile navigation toggle", () => {
    vi.spyOn(apiClient, "getHealth").mockResolvedValue({ status: "ok" });

    render(
      <AppShell>
        <div>Content</div>
      </AppShell>
    );

    const toggleBtn = screen.getByRole("button", { name: /Toggle navigation menu/i });
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveAttribute("aria-expanded", "false");

    // Open mobile menu
    fireEvent.click(toggleBtn);
    expect(toggleBtn).toHaveAttribute("aria-expanded", "true");

    const mobileNav = screen.getByRole("navigation", { name: /Mobile Navigation/i });
    expect(mobileNav).toBeInTheDocument();

    // Close mobile menu
    fireEvent.click(toggleBtn);
    expect(toggleBtn).toHaveAttribute("aria-expanded", "false");
  });
});
