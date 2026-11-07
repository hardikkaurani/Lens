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
}

const SIZE_CONFIGS = {
  xs: { height: 18, width: 43, imgClass: "h-[18px] w-auto", textClass: "text-sm", subClass: "text-[9px]" },
  sm: { height: 24, width: 57, imgClass: "h-6 w-auto", textClass: "text-base", subClass: "text-[10px]" },
  md: { height: 32, width: 76, imgClass: "h-8 w-auto", textClass: "text-lg", subClass: "text-[10px]" },
  lg: { height: 40, width: 95, imgClass: "h-10 w-auto", textClass: "text-xl", subClass: "text-xs" },
  xl: { height: 56, width: 133, imgClass: "h-14 w-auto", textClass: "text-2xl", subClass: "text-sm" },
};

/**
 * Official LENS Logo Component
 *
 * Renders the official metallic chrome ribbon & dot symbol based strictly
 * on the non-negotiable brand identity system.
 */
export function LensLogo({
  size = "md",
  showWordmark = true,
  subtitle,
  className = "",
  priority = false,
  markOnly = false,
  versionText = "v1.0",
}: LensLogoProps) {
  const config = SIZE_CONFIGS[size] || SIZE_CONFIGS.md;

  const symbolElement = (
    <div className="relative inline-flex items-center shrink-0">
      <Image
        src="/branding/lens-symbol.svg"
        alt="LENS Official Symbol"
        width={config.width}
        height={config.height}
        className={`${config.imgClass} object-contain select-none transition-transform duration-200 group-hover:scale-105`}
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

  return (
    <div className={`inline-flex items-center gap-3 ${className}`} data-testid="lens-logo">
      {symbolElement}
      <div className="flex flex-col leading-none" data-testid="lens-wordmark">
        <div className="flex items-center gap-2">
          <span className={`font-black tracking-wider text-slate-100 uppercase ${config.textClass}`}>
            LENS
          </span>
          {versionText && (
            <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-medium bg-slate-800 text-slate-300 border border-slate-700/60 uppercase">
              {versionText}
            </span>
          )}
        </div>
        {subtitle && (
          <span className={`mt-1 font-mono uppercase tracking-widest text-slate-400 ${config.subClass}`}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
