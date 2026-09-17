import Image from "next/image";

// The brand artwork, as supplied — public/brand/. The width/height here are the files'
// intrinsic pixels: next/image reads them for the aspect ratio only, and the rendered size
// is whatever height the caller's className sets (`h-10 w-auto`). They must match the files
// exactly — a wrong ratio here stretches the logo, because `w-auto` derives the width from
// these numbers and the browser then squeezes the artwork into that box.
const FULL      = { src: "/brand/fareqube-logo.png",      width: 2400, height: 696 };
const MARK      = { src: "/brand/fareqube-mark.png",      width: 1024, height: 1024 };
// Reversed lockups for the deep-blue brand panels, derived from the artwork above by
// scripts/build-brand-assets.mjs: everything knocked out to white except the mark's orange
// chart segments, which stay orange so the accent survives.
const FULL_DARK = { src: "/brand/fareqube-logo-dark.png", width: 2400, height: 696 };
const MARK_DARK = { src: "/brand/fareqube-mark-dark.png", width: 1024, height: 1024 };

/**
 * The fareqube.com logo.
 *
 *   variant="full"  the mark, wordmark and "AUTOMATION THAT ASCENDS" tagline, side by side
 *   variant="mark"  the mark alone, for spaces too narrow for the wordmark (a collapsed
 *                   sidebar, a square badge)
 *
 * `onDark` swaps in the reversed artwork. The supplied logo is navy on transparent, so on
 * the deep-blue brand panels it needs the white-knockout version — never a white card behind
 * the navy one, which reads as a sticker sitting on the panel rather than as the brand.
 *
 * Size it with a HEIGHT class and `w-auto` — the tagline is baked into the image, so the
 * logo can only be made readable by giving it height, never by squeezing its width.
 */
export default function Logo({
  variant = "full",
  onDark = false,
  eager = false,
  className = "h-10 w-auto",
}: {
  variant?: "full" | "mark";
  onDark?: boolean;
  /**
   * For a logo that is above the fold on first paint — the home page header, the auth brand
   * panel. Those are the Largest Contentful Paint on their pages, and lazy-loading them
   * (the default) delays it. Next recommends eager loading over `preload` for this.
   */
  eager?: boolean;
  className?: string;
}) {
  const art =
    variant === "mark" ? (onDark ? MARK_DARK : MARK) : onDark ? FULL_DARK : FULL;
  return (
    <Image
      src={art.src}
      width={art.width}
      height={art.height}
      alt={variant === "mark" ? "fareqube" : "fareqube.com — Automation that ascends"}
      loading={eager ? "eager" : "lazy"}
      fetchPriority={eager ? "high" : "auto"}
      className={className}
    />
  );
}
