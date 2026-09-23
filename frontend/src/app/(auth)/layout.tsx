import { Fragment } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import Logo from "@/components/marketing/Logo";
import PanelBackdrop from "@/components/marketing/PanelBackdrop";
import PlatformMap from "@/components/marketing/PlatformMap";

/** The same three words the home page leads with, split so each can rise on its own. */
const HEADLINE = ["Automation", "that", "Ascends"];

const TAGLINE = "Automation that ascends";
const SITE = "fareqube.com";

/**
 * The shell every auth screen sits in: a brand panel on the left, the form on the right.
 *
 * It carries the home page's language deliberately — the same headline and its word-by-word
 * rise, the same platform card, the same tinted bar on mobile — so signing in never feels
 * like it happened on a different product. The panel is the dark counterpart: the word the
 * brand is named for takes the light-on-dark sweep rather than the navy one, which would
 * disappear into the panel behind it.
 *
 * `marketing` is what puts the display face on every heading below, forms included.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="marketing flex min-h-screen bg-white">
      {/* ══ Left — brand panel (desktop only) ═══════════════════════════
          Sticky and exactly one viewport tall: the sign-up form is far longer than the
          panel's content, and without this the panel stretches to match it and pushes the
          card and footer below the fold. */}
      <aside
        className="relative hidden overflow-hidden lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-[46%] lg:flex-col lg:justify-between lg:self-start lg:p-10 xl:w-[48%] xl:p-12"
        style={{ background: "var(--brand-deep)" }}
      >
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
          <div className="grid-bg absolute inset-0 opacity-[0.10]" />
          <PanelBackdrop />
        </div>

        {/* The lockup is the mark plus live text, as in the site header — the full logo
            artwork bakes in the tagline, and the tagline is the headline right below it. */}
        <Link
          href="/"
          className="relative z-10 flex w-fit items-center gap-2.5"
          aria-label={`${SITE} home`}
        >
          <Logo variant="mark" onDark eager className="h-9 w-auto" />
          <span className="display text-[22px] font-semibold text-white">fareqube</span>
        </Link>

        <div className="relative z-10 space-y-8">
          <div>
            <h2 className="text-[2.4rem] font-semibold leading-[1.1] tracking-tight text-white xl:text-[2.7rem]">
              {HEADLINE.map((word, i) => (
                <Fragment key={word}>
                  <span
                    className="animate-fade-up inline-block"
                    style={{ animationDelay: `${i * 130}ms` }}
                  >
                    {i === HEADLINE.length - 1 ? (
                      <span className="text-gradient-dark">{word}</span>
                    ) : (
                      word
                    )}
                  </span>{" "}
                </Fragment>
              ))}
            </h2>
            <p
              className="animate-fade-up mt-5 max-w-md text-[15px] leading-relaxed text-brand-100/80"
              style={{ animationDelay: "440ms" }}
            >
              End-to-end booking, revenue and cost tracking across airlines, hotels, rail,
              bus and packages — with income, invoicing, payments and reconciliation
              automated, and MIS reporting you can stand behind.
            </p>
          </div>

          {/* The home page's hero card, reused. First thing to go on a short laptop
              screen, so the panel never needs to scroll. */}
          <div
            className="animate-fade-up [@media(max-height:860px)]:hidden"
            style={{ animationDelay: "560ms" }}
          >
            <PlatformMap />
          </div>
        </div>

        <div className="relative z-10 flex items-center justify-between gap-4 border-t border-white/10 pt-5">
          <Link
            href="/"
            className="text-xs font-semibold tracking-wide text-brand-100/85 transition-colors hover:text-white"
          >
            {SITE}
          </Link>
          <p className="text-xs text-brand-200/50">© 2026 fareqube · All rights reserved</p>
        </div>
      </aside>

      {/* ══ Right — form ════════════════════════════════════════════════ */}
      <main className="relative flex flex-1 flex-col">
        {/* Mobile bar — the site header, as it appears on the home page. */}
        <div className="nav-surface flex items-center justify-between gap-3 border-b border-brand-100 px-5 py-3 lg:hidden">
          <Link href="/" className="flex items-center gap-2.5" aria-label={`${SITE} home`}>
            <Logo variant="mark" eager className="h-8 w-auto" />
            <span className="display text-[19px] font-semibold text-brand-900">fareqube</span>
          </Link>
          <Link
            href="/"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border-2 border-brand-900 bg-white/70 px-3 py-1.5 text-xs font-semibold text-brand-900 transition-colors hover:bg-brand-900 hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Home
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8 [@media(max-height:820px)]:py-6">
          <div className="w-full max-w-lg">
            <Link
              href="/"
              className="mb-7 hidden w-fit items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-brand-700 lg:inline-flex"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to home
            </Link>
            {children}
          </div>
        </div>

        {/* The form side is signed too, so it never reads as a bare white column. */}
        <footer className="flex items-center justify-center gap-2.5 px-5 pb-6 pt-2 text-[11px] [@media(max-height:820px)]:pb-4">
          <Logo variant="mark" className="h-4 w-4 opacity-80" />
          <Link href="/" className="font-semibold text-slate-500 transition-colors hover:text-brand-700">
            {SITE}
          </Link>
          <span aria-hidden="true" className="text-slate-300">·</span>
          <span className="font-medium uppercase tracking-[0.12em] text-slate-400">{TAGLINE}</span>
        </footer>
      </main>
    </div>
  );
}
