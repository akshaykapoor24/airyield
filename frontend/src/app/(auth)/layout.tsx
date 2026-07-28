import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import Logo from "@/components/marketing/Logo";

const POINTS = [
  "Parse 2,000-page BSP statements in the background",
  "Match every ticket to its deal and settlement row",
  "Close each period at zero variance — provably",
];

const STATS = [
  { value: "200+", label: "Airline codes" },
  { value: "15K+", label: "Rows / statement" },
  { value: "99.9%", label: "Accuracy" },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* ══ Left — brand panel (desktop only) ═══════════════════════════ */}
      <aside
        className="relative hidden overflow-hidden lg:flex lg:w-[46%] xl:w-[50%] lg:flex-col lg:justify-between lg:p-12"
        style={{ background: "var(--brand-deep)" }}
      >
        {/* animated backdrop */}
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <div className="grid-bg absolute inset-0 opacity-[0.13]" />
          <div className="animate-blob animate-aurora absolute -left-24 top-8 h-80 w-80 bg-sky-400/25 blur-3xl" />
          <div
            className="animate-blob animate-aurora absolute -right-20 bottom-16 h-72 w-72 bg-blue-500/30 blur-3xl"
            style={{ animationDelay: "4s" }}
          />
          <div
            className="animate-blob animate-aurora absolute bottom-1/3 left-1/4 h-56 w-56 bg-orange-400/15 blur-3xl"
            style={{ animationDelay: "8s" }}
          />
        </div>

        <Link href="/" className="relative z-10 w-fit">
          <Logo light tagline="Revenue Intelligence" />
        </Link>

        <div className="relative z-10 space-y-8">
          <div>
            <h2 className="animate-fade-up text-[2.6rem] font-bold leading-[1.1] tracking-tight text-white">
              Every rupee of
              <br />
              airline incentive,
              <br />
              <span className="text-orange-400">accounted for.</span>
            </h2>
            <p
              className="animate-fade-up mt-4 max-w-sm text-sm leading-relaxed text-blue-100/75"
              style={{ animationDelay: "100ms" }}
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
                <span className="text-sm leading-relaxed text-blue-50/85">{p}</span>
              </li>
            ))}
          </ul>

          {/* boarding-pass stub */}
          <div
            className="animate-fade-up relative max-w-sm overflow-hidden rounded-2xl border border-white/15 bg-white/[0.07] p-4 backdrop-blur-sm"
            style={{ animationDelay: "500ms" }}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-blue-200/70">
                  Period
                </p>
                <p className="mt-1 font-mono text-xs font-semibold text-white">
                  01 JUL → 07 JUL 2026
                </p>
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
              <p className="text-[10px] text-blue-200/70">Variance</p>
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
                <p className="text-2xl font-bold text-white">{s.value}</p>
                <p className="mt-0.5 text-[11px] text-blue-200/70">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 text-xs text-blue-200/50">
          © 2026 FareQube · All rights reserved
        </p>
      </aside>

      {/* ══ Right — form ════════════════════════════════════════════════ */}
      <main className="relative flex flex-1 flex-col">
        {/* mobile brand bar */}
        <div
          className="relative flex items-center justify-between overflow-hidden px-5 py-4 lg:hidden"
          style={{ background: "var(--brand-deep)" }}
        >
          <div className="animate-aurora pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-sky-400/25 blur-2xl" />
          <Link href="/" className="relative z-10">
            <Logo light />
          </Link>
          <Link
            href="/"
            className="relative z-10 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-blue-100 transition-colors hover:bg-white/10"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Home
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-8 sm:px-8 sm:py-12">
          <div className="w-full max-w-md">
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
      </main>
    </div>
  );
}
