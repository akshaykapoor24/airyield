import Image from "next/image";

// The brand artwork, as supplied — public/brand/. The width/height here are the files'
// intrinsic pixels: next/image reads them for the aspect ratio only, and the rendered size
// is whatever height the caller's className sets (`h-10 w-auto`).
const FULL = { src: "/brand/fareqube-logo.png", width: 2400, height: 521 };
const MARK = { src: "/brand/fareqube-mark.png", width: 1024, height: 1024 };

/**
 * The fareqube.com logo.
 *
 *   variant="full"  the mark, wordmark and "AUTOMATION THAT ASCENDS" tagline, side by side
 *   variant="mark"  the mark alone, for spaces too narrow for the wordmark (a collapsed
 *                   sidebar, a square badge)
 *
 * `onDark` puts it on a white card. The artwork is navy on transparent and has no light
 * version, so on the deep-blue brand panels it would otherwise all but disappear.
 *
 * Size it with a HEIGHT class and `w-auto` — the tagline is baked into the image, so the
 * logo can only be made readable by giving it height, never by squeezing its width.
 */
export default function Logo({
  variant = "full",
  onDark = false,
  preload = false,
  className = "h-10 w-auto",
}: {
  variant?: "full" | "mark";
  onDark?: boolean;
  /** For the one logo that is above the fold on first paint — the home page header. */
  preload?: boolean;
  className?: string;
}) {
  const art = variant === "mark" ? MARK : FULL;
  const image = (
    <Image
      src={art.src}
      width={art.width}
      height={art.height}
      alt={variant === "mark" ? "fareqube" : "fareqube.com — Automation that ascends"}
      preload={preload}
      className={className}
    />
  );
  if (!onDark) return image;
  return <span className="inline-flex rounded-xl bg-white px-3 py-2 shadow-sm ring-1 ring-white/40">{image}</span>;
}
