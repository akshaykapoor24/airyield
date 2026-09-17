import Link from "next/link";
import { ArrowLeft, Check, TrendingUp } from "lucide-react";
import FlipText from "@/components/marketing/FlipText";
import Logo from "@/components/marketing/Logo";
import PanelBackdrop from "@/components/marketing/PanelBackdrop";
import { Counter } from "@/components/marketing/Reveal";

const POINTS = [
  "Parse 2,000-page BSP statements in the background",
  "Match every ticket to its deal and settlement row",
  "Close each period at zero variance — provably",
];

const STATS = [
  { value: 200, suffix: "+", label: "Airline codes" },
  { value: 15, suffix: "K+", label: "Rows / statement" },
  { value: 99.9, suffix: "%", decimals: 1, label: "Accuracy" },
];

/** The tagline, as it is set in the logo artwork — repeated in live text so it reads as a
 *  promise on the page, not just as pixels inside the lockup. */
const TAGLINE = "Automation that ascends";
const SITE = "fareqube.com";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* ══ Left — brand panel (desktop only) ═══════════════════════════
          Sticky and exactly one viewport tall: the sign-up form is far longer than the
          panel's content, and without this the panel stretches to match it and pushes the
          stats and footer below the fold. */}
      <aside
        className="relative hidden overflow-hidden lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-[46%] lg:flex-col lg:justify-between lg:self-start lg:p-10 xl:w-[50%] xl:p-12"
        style={{ background: "var(--brand-deep)" }}
      >
        {/* animated backdrop */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
          <div className="grid-bg absolute inset-0 opacity-[0.10]" />
          <PanelBackdrop />
        </div>

        <Link href="/" className="relative z-10 w-fit" aria-label={`${SITE} home`}>
          <Logo onDark eager className="h-16 w-auto xl:h-20" />
        </Link>

        <div className="relative z-10 space-y-7">
          <div>
            {/* the logo's tagline, promoted to an eyebrow — "ascends" is the promise the
                headline below then cashes out */}
            <span className="animate-fade-up inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.07] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-orange-300 backdrop-blur-sm">
              <TrendingUp className="h-3 w-3" strokeWidth={2.5} />
              {TAGLINE}
            </span>

            <h2
              className="animate-fade-up mt-5 text-[2.4rem] font-bold leading-[1.1] tracking-tight text-white xl:text-[2.6rem]"
              style={{ animationDelay: "60ms" }}
            >
              Every rupee of
              <br />
              airline incentive,
              <br />
              <span className="text-orange-400">accounted for.</span>
            </h2>
            <p
              className="animate-fade-up mt-4 max-w-sm text-sm leading-relaxed text-brand-100/75"
              style={{ animationDelay: "120ms" }}
            >
              Contracts, vendor statements, reconciliation and approvals — one
              platform, built for travel agencies and consolidators.
            </p>
          </div>

          <ul className="space-y-3">
            {POINTS.map((p, i) => (
              <li
                key={p}
                className="animate-fade-up flex items-start gap-3"
                style={{ animationDelay: `${200 + i * 90}ms` }}
              >
                <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-emerald-400/20 ring-1 ring-emerald-400/40">
                  <Check className="h-3 w-3 text-emerald-300" strokeWidth={3} />
                </span>
                <span className="text-sm leading-relaxed text-brand-50/85">{p}</span>
              </li>
            ))}
          </ul>

          {/* boarding-pass stub — the first thing to go on a short laptop screen, so the
              panel never needs to scroll */}
          <div
            className="animate-fade-up relative max-w-sm overflow-hidden rounded-2xl border border-white/15 bg-white/[0.07] p-4 backdrop-blur-sm [@media(max-height:800px)]:hidden"
            style={{ animationDelay: "500ms" }}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-brand-200/70">
                  Period
                </p>
                {/* the same split-flap the home page's settlement board uses, so the
                    two brand surfaces move in the same language */}
                <FlipText
                  text="01 JUL 07 JUL 26"
                  delay={620}
                  className="mt-1.5"
                  cellClassName="h-5 w-[0.72rem] text-[10px]"
                />
              </div>

              <svg viewBox="0 0 90 26" className="h-6 w-24 overflow-visible" aria-hidden="true">
                <path
                  d="M2 20 Q 45 -4 88 14"
                  fill="none"
                  stroke="rgba(191,219,254,0.45)"
                  strokeWidth="1.2"
                  strokeDasharray="4 4"
                  strokeLinecap="round"
                  className="animate-draw"
                />
                <g className="smil-motion">
                  <path d="M0 -3.4 L3.2 2.6 L0 1.2 L-3.2 2.6 Z" fill="#fdba74" transform="rotate(90)" />
                  <animateMotion
                    dur="4s"
                    repeatCount="indefinite"
                    rotate="auto"
                    path="M2 20 Q 45 -4 88 14"
                  />
                </g>
              </svg>
            </div>

            <div className="my-3 border-t border-dashed border-white/20" />

            <div className="flex items-center justify-between">
              <p className="text-[10px] text-brand-200/70">Variance</p>
              <p className="font-mono text-sm font-bold text-emerald-300">₹0.00</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 border-t border-white/15 pt-6">
            {STATS.map((s, i) => (
              <div
                key={s.label}
                className="animate-fade-up"
                style={{ animationDelay: `${600 + i * 80}ms` }}
              >
                <p className="text-2xl font-bold text-white">
                  <Counter value={s.value} suffix={s.suffix} decimals={s.decimals ?? 0} />
                </p>
                <p className="mt-0.5 text-[11px] text-brand-200/70">{s.label}</p>
              </div>
            ))}
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
        {/* mobile brand bar */}
        <div
          className="relative flex items-center justify-between gap-3 overflow-hidden px-5 py-3.5 lg:hidden"
          style={{ background: "var(--brand-deep)" }}
        >
          <div className="animate-aurora pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-brand-400/25 blur-2xl" />
          <Link href="/" className="relative z-10" aria-label={`${SITE} home`}>
            <Logo onDark eager className="h-11 w-auto" />
          </Link>
          <Link
            href="/"
            className="relative z-10 inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-brand-100 transition-colors hover:bg-white/10"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Home
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-8 sm:px-8 sm:py-10 [@media(max-height:820px)]:py-6">
          <div className="w-full max-w-lg">
            {/* back link, desktop */}
            <Link
              href="/"
              className="mb-6 hidden w-fit items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700 lg:inline-flex"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to home
            </Link>
            {children}
          </div>
        </div>

        {/* brand footer — the mark, the address and the tagline, so the form side is
            signed too and not just a white column */}
        <footer className="flex items-center justify-center gap-2.5 px-5 pb-6 pt-2 text-[11px] [@media(max-height:820px)]:pb-4">
          <Logo variant="mark" className="h-4 w-4 opacity-80" />
          <Link href="/" className="font-semibold text-slate-500 transition-colors hover:text-slate-700">
            {SITE}
          </Link>
          <span aria-hidden="true" className="text-slate-300">·</span>
          <span className="font-medium uppercase tracking-[0.12em] text-slate-400">
            {TAGLINE}
          </span>
        </footer>
      </main>
    </div>
  );
}
