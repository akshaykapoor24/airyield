"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ArrowRight, Menu, X } from "lucide-react";
import { isAuthenticated } from "@/lib/auth";
import Logo from "./Logo";

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

/** Section anchors on the home page. The ids live on the <section> elements in page.tsx. */
const LINKS = [
  { href: "#pipeline", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#reconciliation", label: "Reconciliation" },
];

export default function SiteNav() {
  const authed = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthServerSnapshot);
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Don't leave the page scrollable behind the open mobile sheet.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const cta = "text-white shadow-md shadow-brand-700/25 hover:shadow-lg hover:shadow-brand-700/30";

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-300 ${
        scrolled
          ? "glass border-b border-slate-200/70 shadow-sm"
          : "border-b border-transparent bg-transparent"
      }`}
    >
      {/* Full-bleed: the header spans the page, while the content below sits in a
          narrower column. Only the horizontal padding holds the logo off the edge. */}
      <div className="flex h-20 w-full items-center justify-between gap-6 px-5 sm:px-8 lg:px-12">
        <Link href="/" aria-label="fareqube.com home" className="shrink-0">
          <Logo eager className="h-12 w-auto sm:h-14" />
        </Link>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Sections">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="rounded-lg px-3.5 py-2 text-[15px] font-medium text-slate-600 transition-colors hover:bg-brand-50 hover:text-brand-800"
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {authed ? (
            <Link
              href="/dashboard"
              className={`group hidden items-center gap-1.5 rounded-xl px-5 py-2.5 text-[15px] font-semibold transition-all sm:inline-flex ${cta}`}
              style={{ background: "var(--brand-grad)" }}
            >
              Go to Dashboard
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="hidden rounded-xl px-4 py-2.5 text-[15px] font-semibold text-slate-700 transition-colors hover:bg-slate-100 sm:inline-flex"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className={`group hidden items-center gap-1.5 rounded-xl px-5 py-2.5 text-[15px] font-semibold transition-all sm:inline-flex ${cta}`}
                style={{ background: "var(--brand-grad)" }}
              >
                Sign up
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </>
          )}

          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 bg-white/70 text-slate-700 transition-colors hover:bg-slate-50 lg:hidden"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile sheet — carries the section links at every width below `lg`, and the auth
          buttons only below `sm`, where they drop out of the bar. */}
      {open && (
        <div className="animate-fade-in border-t border-slate-200/70 bg-white/95 backdrop-blur lg:hidden">
          <nav className="w-full px-5 py-4 sm:px-8">
            <div className="grid gap-1">
              {LINKS.map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className="rounded-xl px-4 py-3 text-sm font-semibold text-slate-700 transition-colors hover:bg-brand-50 hover:text-brand-800"
                >
                  {l.label}
                </a>
              ))}
            </div>

            <div className="mt-3 grid gap-2 border-t border-slate-200/70 pt-3 sm:hidden">
              {authed ? (
                <Link
                  href="/dashboard"
                  onClick={() => setOpen(false)}
                  className="rounded-xl px-4 py-3 text-center text-sm font-semibold text-white"
                  style={{ background: "var(--brand-grad)" }}
                >
                  Go to Dashboard
                </Link>
              ) : (
                <>
                  <Link
                    href="/login"
                    onClick={() => setOpen(false)}
                    className="rounded-xl border border-slate-200 px-4 py-3 text-center text-sm font-semibold text-slate-700"
                  >
                    Log in
                  </Link>
                  <Link
                    href="/signup"
                    onClick={() => setOpen(false)}
                    className="rounded-xl px-4 py-3 text-center text-sm font-semibold text-white"
                    style={{ background: "var(--brand-grad)" }}
                  >
                    Sign up
                  </Link>
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
