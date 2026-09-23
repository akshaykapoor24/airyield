"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { isAuthenticated } from "@/lib/auth";
import Logo from "./Logo";
import { openContact } from "./ContactModal";

// Auth lives in localStorage — an external store. `useSyncExternalStore` reads it
// without a setState-in-effect, and the server snapshot keeps the first client
// render identical to the SSR output (no hydration mismatch). Subscribing to
// `storage` also picks up a sign-in that happened in another tab.
const subscribeAuth = (onChange: () => void) => {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
};
const getAuthSnapshot = () => isAuthenticated();
const getAuthServerSnapshot = () => false;

/**
 * The header: the lockup, and one thing to do.
 *
 * No section links and no hamburger — at this width the bar is two items, so the mobile
 * sheet that used to carry the links has nothing left to carry. The section anchors and
 * the sign-in links live in the footer.
 *
 * The lockup is built from the mark plus live text rather than the full logo artwork,
 * because the artwork bakes in the tagline, and the tagline is the headline on this page.
 */
export default function SiteNav() {
  const authed = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthServerSnapshot);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      // The tint is always on, so the bar is its own strip from the first paint rather
      // than appearing once you scroll. Only the depth cues change on scroll.
      className={`nav-surface sticky top-0 z-50 border-b transition-all duration-300 ${
        scrolled ? "border-brand-200 shadow-md shadow-brand-900/5" : "border-brand-100"
      }`}
    >
      <div className="mx-auto flex h-20 w-full max-w-[1180px] items-center justify-between gap-6 px-6 sm:px-8">
        <Link href="/" aria-label="fareqube.com home" className="flex shrink-0 items-center gap-2.5">
          <Logo variant="mark" eager className="h-8 w-auto sm:h-9" />
          <span className="display text-[20px] font-semibold text-brand-900 sm:text-[23px]">
            fareqube
          </span>
        </Link>

        {authed ? (
          <Link
            href="/dashboard"
            className="group inline-flex items-center gap-1.5 rounded-lg px-5 py-2.5 text-[15px] font-semibold text-white shadow-md shadow-brand-700/25 transition-all hover:shadow-lg hover:shadow-brand-700/30"
            style={{ background: "var(--brand-grad)" }}
          >
            Go to Dashboard
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        ) : (
          <button
            type="button"
            onClick={openContact}
            className="rounded-lg border-2 border-brand-900 bg-white/70 px-5 py-2.5 text-[15px] font-semibold text-brand-900 transition-colors hover:bg-brand-900 hover:text-white sm:px-6"
          >
            Contact us
          </button>
        )}
      </div>
    </header>
  );
}
