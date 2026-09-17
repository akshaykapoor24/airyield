import type { Metadata } from "next";
import "./globals.css";
import Providers from "./providers";

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
    <html lang="en" className="h-full">
      <body className="min-h-full antialiased bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
