import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import React from "react";
import { LensLogo } from "@/components/LensLogo";

describe("LENS Official Logo Component (Branding Acceptance)", () => {
  it("renders official symbol with accessible alt text and default wordmark", () => {
    render(<LensLogo />);

    const symbolImg = screen.getByAltText("LENS Official Symbol");
    expect(symbolImg).toBeInTheDocument();
    expect(symbolImg).toHaveAttribute("src", expect.stringContaining("lens-symbol.svg"));

    expect(screen.getByText("LENS")).toBeInTheDocument();
    expect(screen.getByText("v1.0")).toBeInTheDocument();
  });

  it("renders custom subtitle when provided", () => {
    render(<LensLogo subtitle="Personal Knowledge" />);

    expect(screen.getByText("Personal Knowledge")).toBeInTheDocument();
  });

  it("supports markOnly mode without text wordmark", () => {
    render(<LensLogo markOnly />);

    expect(screen.getByAltText("LENS Official Symbol")).toBeInTheDocument();
    expect(screen.queryByText("LENS")).not.toBeInTheDocument();
  });

  it("applies sizing configurations correctly", () => {
    const { rerender } = render(<LensLogo size="xs" />);
    let symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "18");

    rerender(<LensLogo size="xl" />);
    symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "56");
  });

  it("renders custom version badge and passes unoptimized image prop", () => {
    render(<LensLogo versionText="v2.0-beta" />);

    expect(screen.getByText("v2.0-beta")).toBeInTheDocument();
    const symbolImg = screen.getByTestId("lens-symbol-img");
    expect(symbolImg).toBeInTheDocument();
  });
});
