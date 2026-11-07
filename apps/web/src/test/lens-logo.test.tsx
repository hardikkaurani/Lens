import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import React from "react";
import { LensLogo } from "@/components/LensLogo";
import { metadata } from "@/app/layout";

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

  it("applies sizing configurations correctly across all variants", () => {
    const { rerender } = render(<LensLogo size="xs" />);
    let symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "18");
    expect(symbol).toHaveAttribute("width", "43");

    rerender(<LensLogo size="sm" />);
    symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "24");
    expect(symbol).toHaveAttribute("width", "57");

    rerender(<LensLogo size="md" />);
    symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "32");
    expect(symbol).toHaveAttribute("width", "76");

    rerender(<LensLogo size="lg" />);
    symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "40");
    expect(symbol).toHaveAttribute("width", "95");

    rerender(<LensLogo size="xl" />);
    symbol = screen.getByAltText("LENS Official Symbol");
    expect(symbol).toHaveAttribute("height", "56");
    expect(symbol).toHaveAttribute("width", "133");
  });

  it("renders custom version badge and passes unoptimized image prop", () => {
    render(<LensLogo versionText="v2.0-beta" />);

    expect(screen.getByText("v2.0-beta")).toBeInTheDocument();
    const symbolImg = screen.getByTestId("lens-symbol-img");
    expect(symbolImg).toBeInTheDocument();
  });

  it("supports priority loading for critical branding in viewport", () => {
    render(<LensLogo priority />);
    const symbolImg = screen.getByTestId("lens-symbol-img");
    expect(symbolImg).toBeInTheDocument();
  });
});

describe("Application Layout Branding Metadata", () => {
  it("declares complete favicon, apple touch icon, and openGraph image specifications", () => {
    expect(metadata.title).toBe("LENS — Personal Knowledge Workspace");
    expect(metadata.icons).toBeDefined();

    // @ts-expect-error icons object inspection
    const iconList = metadata.icons?.icon;
    expect(Array.isArray(iconList)).toBe(true);
    expect(iconList).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ url: "/favicon.ico" }),
        expect.objectContaining({ url: "/branding/favicon-32x32.png" }),
        expect.objectContaining({ url: "/branding/favicon-16x16.png" }),
      ])
    );

    // @ts-expect-error apple touch icon inspection
    const appleList = metadata.icons?.apple;
    expect(Array.isArray(appleList)).toBe(true);
    expect(appleList).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ url: "/apple-touch-icon.png", sizes: "180x180" }),
      ])
    );

    // OpenGraph branding preview image
    expect(metadata.openGraph?.images).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          url: "/branding/lens-logo-preview.png",
          width: 1600,
          height: 960,
          alt: "LENS Official Brand Identity System",
        }),
      ])
    );
  });
});
