import type { Metadata } from "next";
import { Inter, Sora } from "next/font/google";
import "./globals.css";
import Providers from "./providers";

/**
 * The two typefaces the brand runs on, self-hosted by `next/font` so there is no
 * render-blocking request to Google and no layout shift when they land.
 *
 *   Sora  — the display face. Headlines, the stat figures, the split-flap board.
 *   Inter — everything that is read rather than scanned.
 *
 * They are exposed as CSS variables rather than class names because the theme in
 * globals.css maps `--font-display` / `--font-sans` onto them, which is what makes
 * `font-display` and the default body face available as Tailwind utilities.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const sora = Sora({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sora",
  display: "swap",
});

/**
 * Site-wide metadata. `title.default` is what a route gets when it sets no title of its
 * own, and `title.template` wraps the titles that child routes do set — so a tab reads
 * "Sign in — fareqube", and never a bare localhost URL.
 *
 * The brand is lowercase "fareqube", as it is set in the logo artwork, and the tagline is
 * the one in the lockup.
 */
export const metadata: Metadata = {
  title: {
    default: "fareqube — Automation that ascends",
    template: "%s — fareqube",
  },
  description:
    "Contracts, vendor statements, reconciliation and approvals — one platform, built for travel agencies and consolidators.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`h-full ${inter.variable} ${sora.variable}`}>
      <body className="min-h-full antialiased bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
