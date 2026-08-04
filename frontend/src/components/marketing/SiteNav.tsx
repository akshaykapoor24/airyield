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

  const cta = "text-white shadow-md shadow-blue-500/25 hover:shadow-lg hover:shadow-blue-500/30";

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-300 ${
        scrolled
          ? "glass border-b border-slate-200/70 shadow-sm"
          : "border-b border-transparent bg-transparent"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-6">
        <Link href="/" aria-label="FareQube home">
          <Logo />
        </Link>

        <div className="flex items-center gap-2">
          {authed ? (
            <Link
              href="/dashboard"
              className={`group hidden items-center gap-1.5 rounded-xl px-4 py-2 text-[15px] font-semibold transition-all sm:inline-flex ${cta}`}
              style={{ background: "var(--brand-grad)" }}
            >
              Go to Dashboard
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="hidden rounded-xl px-4 py-2 text-[15px] font-semibold text-slate-700 transition-colors hover:bg-slate-100 sm:inline-flex"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className={`group hidden items-center gap-1.5 rounded-xl px-4 py-2 text-[15px] font-semibold transition-all sm:inline-flex ${cta}`}
                style={{ background: "var(--brand-grad)" }}
              >
                Start free
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </>
          )}

          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 bg-white/70 text-slate-700 transition-colors hover:bg-slate-50 sm:hidden"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile sheet — the inline auth buttons appear from `sm` up, so this only
          has to cover the narrowest widths. */}
      {open && (
        <div className="animate-fade-in border-t border-slate-200/70 bg-white/95 backdrop-blur sm:hidden">
          <nav className="mx-auto max-w-6xl px-5 py-4">
            <div className="grid gap-2">
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
                    Start free
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
