import React from "react";
import Image from "next/image";

export interface LensLogoProps {
  /** Size variant of the mark */
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  /** Whether to show the "LENS" wordmark alongside the symbol */
  showWordmark?: boolean;
  /** Optional secondary subtitle text beneath or beside wordmark */
  subtitle?: string;
  /** Custom additional className for the wrapper */
  className?: string;
  /** Next.js Image priority loading */
  priority?: boolean;
  /** Whether to render only the symbol without any text container */
  markOnly?: boolean;
  /** Version tag displayed alongside the wordmark (defaults to v1.0) */
  versionText?: string;
  /** Visual surface theme: light (institutional white/neutral surfaces) or dark (overlay/cinematic) */
  theme?: "light" | "dark";
}

const SIZE_CONFIGS = {
  xs: { height: 18, width: 43, imgClass: "h-[18px] w-auto", textClass: "text-xs tracking-[0.14em]", subClass: "text-[9px]" },
  sm: { height: 24, width: 57, imgClass: "h-6 w-auto", textClass: "text-sm tracking-[0.14em]", subClass: "text-[10px]" },
  md: { height: 32, width: 76, imgClass: "h-8 w-auto", textClass: "text-base tracking-[0.14em]", subClass: "text-[11px]" },
  lg: { height: 40, width: 95, imgClass: "h-10 w-auto", textClass: "text-lg tracking-[0.14em]", subClass: "text-xs" },
  xl: { height: 56, width: 133, imgClass: "h-14 w-auto", textClass: "text-xl tracking-[0.14em]", subClass: "text-xs" },
};

/**
 * Official LENS Logo Component
 *
 * Refined institutional presentation with balanced proportions,
 * crisp typography, and surface-aware theming.
 */
export function LensLogo({
  size = "md",
  showWordmark = true,
  subtitle,
  className = "",
  priority = false,
  markOnly = false,
  versionText = "v1.0",
  theme = "light",
}: LensLogoProps) {
  const config = SIZE_CONFIGS[size] || SIZE_CONFIGS.md;
  const isDark = theme === "dark";

  const symbolElement = (
    <div className="relative inline-flex items-center shrink-0">
      <Image
        src="/branding/lens-symbol.svg"
        alt="LENS Official Symbol"
        width={config.width}
        height={config.height}
        className={`${config.imgClass} object-contain select-none transition-transform duration-150 group-hover:scale-[1.02]`}
        priority={priority}
        unoptimized
        data-testid="lens-symbol-img"
      />
    </div>
  );

  if (markOnly || !showWordmark) {
    return (
      <div className={`inline-flex items-center ${className}`} data-testid="lens-logo">
        {symbolElement}
      </div>
    );
  }

  const textColor = isDark ? "text-white" : "text-[#0B1A2F]";
  const badgeClasses = isDark
    ? "bg-white/10 text-slate-200 border-white/20"
    : "bg-slate-100 text-[#5B6472] border-slate-200";
  const subColor = isDark ? "text-slate-300" : "text-[#5B6472]";

  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`} data-testid="lens-logo">
      {symbolElement}
      <div className="flex flex-col justify-center leading-tight" data-testid="lens-wordmark">
        <div className="flex items-center gap-1.5">
          <span className={`font-semibold uppercase font-sans ${textColor} ${config.textClass}`}>
            LENS
          </span>
          {versionText && (
            <span
              className={`text-[9px] px-1.5 py-0.5 rounded-[3px] font-mono font-medium border uppercase tracking-wider ${badgeClasses}`}
            >
              {versionText}
            </span>
          )}
        </div>
        {subtitle && (
          <span className={`mt-0.5 font-sans uppercase tracking-[0.14em] font-medium ${subColor} ${config.subClass}`}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
