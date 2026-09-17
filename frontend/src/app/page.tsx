import Link from "next/link";
import type { Metadata } from "next";
import {
  ArrowRight, BarChart3, Calculator, CheckSquare, FileSpreadsheet,
  FileText, GitCompareArrows, Layers, Plane, ShieldCheck, TrendingUp, Upload, Zap,
} from "lucide-react";
import Logo from "@/components/marketing/Logo";
import SiteNav from "@/components/marketing/SiteNav";
import HeroVisual from "@/components/marketing/HeroVisual";
import RouteNetwork from "@/components/marketing/RouteNetwork";
import SettlementBoard from "@/components/marketing/SettlementBoard";
import SpotlightCard from "@/components/marketing/SpotlightCard";
import { Reveal } from "@/components/marketing/Reveal";

// The tab title is the brand lockup itself — "fareqube — Automation that ascends", the
// root layout's `title.default`. The searchable specifics stay in the description, which is
// what a search snippet shows anyway.
export const metadata: Metadata = {
  description:
    "Manage airline contracts, ingest BSP and LCC statements, reconcile tickets to zero variance, and calculate incentive income — in one platform built for travel agencies.",
};

const FEATURES = [
  {
    icon: FileText,
    title: "Deal & Contract Repository",
    desc: "Every airline contract, incentive slab, and validity window in one place — across B2B, B2C and B2E.",
  },
  {
    icon: FileSpreadsheet,
    title: "Vendor Statement Ingestion",
    desc: "Drop a 2,000-page BSP PDF, an LCC export or a third-party file. It is parsed page by page, in the background.",
  },
  {
    icon: Calculator,
    title: "Automated Income Calculation",
    desc: "Incentive slabs, PLB, exclusions and segment rules applied per ticket — no spreadsheet gymnastics.",
  },
  {
    icon: GitCompareArrows,
    title: "Ticket Reconciliation",
    desc: "Expected versus actual, per settlement event. ADMs, ACMs and refunds filtered and traceable to source.",
  },
  {
    icon: CheckSquare,
    title: "Approval Workflows",
    desc: "Route deals and overrides through role-based approval matrices, with an audit trail on every decision.",
  },
  {
    icon: BarChart3,
    title: "Live Dashboards",
    desc: "Income trends, supplier performance and pending actions — updated as statements land.",
  },
];

const STEPS = [
  {
    icon: Upload,
    step: "01",
    title: "Upload",
    desc: "BSP, LCC and third-party statements, plus your own ticket files.",
  },
  {
    icon: Layers,
    step: "02",
    title: "Match",
    desc: "Tickets are matched to deals and to their settlement rows automatically.",
  },
  {
    icon: Calculator,
    step: "03",
    title: "Calculate",
    desc: "Incentive slabs and exclusions applied to produce income per ticket.",
  },
  {
    icon: ShieldCheck,
    step: "04",
    title: "Reconcile",
    desc: "Uploaded totals meet calculated totals — variances surfaced, not buried.",
  },
];

const AIRLINES = [
  ["001", "AA"], ["006", "DL"], ["016", "UA"], ["020", "LH"], ["057", "AF"],
  ["071", "ET"], ["074", "KL"], ["098", "AI"], ["125", "BA"], ["131", "JL"],
  ["157", "QR"], ["176", "EK"], ["217", "TG"], ["232", "MH"], ["235", "TK"],
  ["607", "EY"], ["618", "SQ"], ["706", "KQ"],
];

const TRUST = [
  "Built for travel agencies & consolidators",
  "BSP · LCC · Third-party",
  "PAN & GST ready",
  "Role-based approvals",
];

/** The logo's tagline, set in live text so the promise is on the page, not just in pixels. */
const TAGLINE = "Automation that ascends";

/** Mirrors the section anchors in SiteNav. */
const FOOTER_LINKS = [
  { href: "#pipeline", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#reconciliation", label: "Reconciliation" },
];

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <SiteNav />

      {/* ══ Hero ═══════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        {/* backdrop */}
        <div className="pointer-events-none absolute inset-0 -z-10">
          <div className="grid-bg grid-mask absolute inset-0" />
          <div className="animate-blob animate-aurora absolute -left-24 -top-24 h-[26rem] w-[26rem] bg-brand-400/25 blur-3xl" />
          <div
            className="animate-blob animate-aurora absolute -right-16 top-10 h-[22rem] w-[22rem] bg-brand-300/25 blur-3xl"
            style={{ animationDelay: "3s" }}
          />
          <div
            className="animate-blob animate-aurora absolute bottom-0 left-1/3 h-[18rem] w-[18rem] bg-accent-300/25 blur-3xl"
            style={{ animationDelay: "6s" }}
          />
        </div>

        <div className="mx-auto grid max-w-5xl items-center gap-12 px-5 pb-16 pt-10 sm:px-6 lg:grid-cols-[1.08fr_1fr] lg:gap-10 lg:pb-24 lg:pt-16">
          {/* copy */}
          <div className="text-center lg:text-left">
            <div className="animate-fade-up inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50/90 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-brand-700 backdrop-blur">
              <TrendingUp className="h-3.5 w-3.5" strokeWidth={2.5} />
              {TAGLINE}
            </div>

            <h1
              className="animate-fade-up mt-6 text-4xl font-bold leading-[1.1] tracking-tight sm:text-5xl lg:text-[2.9rem] xl:text-[3.15rem]"
              style={{ animationDelay: "80ms" }}
            >
              Every rupee of airline{" "}
              <span className="text-gradient">incentive, accounted for.</span>
            </h1>

            <p
              className="animate-fade-up mx-auto mt-5 max-w-xl text-lg leading-relaxed text-slate-500 lg:mx-0"
              style={{ animationDelay: "160ms" }}
            >
              fareqube turns airline contracts and vendor statements into reconciled,
              auditable income — from a 2,000-page BSP file to a zero-variance
              summary, without a single spreadsheet.
            </p>

            <div
              className="animate-fade-up mt-9 flex flex-col items-center gap-3 sm:flex-row lg:justify-start"
              style={{ animationDelay: "240ms" }}
            >
              <Link
                href="/signup"
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-brand-700/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brand-700/40 sm:w-auto"
                style={{ background: "var(--brand-grad)" }}
              >
                Sign up
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
              <Link
                href="/login"
                className="inline-flex w-full items-center justify-center rounded-xl border border-slate-200 bg-white/70 px-7 py-3.5 text-base font-semibold text-slate-700 backdrop-blur transition-all hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white sm:w-auto"
              >
                Sign in
              </Link>
            </div>

            <div
              className="animate-fade-up mt-8 flex flex-wrap justify-center gap-x-4 gap-y-2 text-[13px] text-slate-500 lg:justify-start"
              style={{ animationDelay: "320ms" }}
            >
              {TRUST.map((t) => (
                <span key={t} className="inline-flex items-center gap-1.5">
                  <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  {t}
                </span>
              ))}
            </div>
          </div>

          {/* artwork */}
          <div className="lg:pl-6">
            <HeroVisual />
          </div>
        </div>

        {/* ── Network band — the route map, then the carriers it settles ──── */}
        <div className="relative overflow-hidden border-y border-slate-100 bg-slate-50/60 py-7">
          <p className="text-center text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
            Reconciles settlement data across carriers
          </p>
          <div className="mx-auto mb-1 h-[160px] w-full max-w-5xl px-5 sm:h-[215px] sm:px-6">
            <RouteNetwork />
          </div>
          <div className="marquee-mask overflow-hidden">
            <div className="animate-marquee flex w-max gap-3">
              {[...AIRLINES, ...AIRLINES].map(([code, iata], i) => (
                <span
                  key={`${code}-${i}`}
                  className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 shadow-sm"
                >
                  <span className="font-mono text-xs font-semibold text-slate-400">{code}</span>
                  <span className="text-base font-bold text-slate-700">{iata}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ══ Settlement board ═══════════════════════════════════════════ */}
      <div className="mx-auto max-w-5xl px-5 py-16 sm:px-6 sm:py-20">
        <SettlementBoard />
      </div>

      {/* ══ How it works ═══════════════════════════════════════════════ */}
      <section
        id="pipeline"
        className="relative scroll-mt-20 overflow-hidden border-y border-slate-100 bg-slate-50/70"
      >
        <div className="mx-auto max-w-5xl px-5 py-16 sm:px-6 sm:py-24">
          <Reveal className="mx-auto max-w-2xl text-center">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-brand-700 ring-1 ring-brand-100">
              <Zap className="h-3.5 w-3.5" /> The pipeline
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Statement in. Reconciled income out.
            </h2>
            <p className="mt-3.5 text-base leading-relaxed text-slate-500 sm:text-lg">
              Four steps run end to end — the heavy parsing happens in the background,
              so a thousand-page file never blocks your day.
            </p>
          </Reveal>

          <div className="relative mt-14">
            {/* connector — a dashed rule stretches reliably; an inline SVG would
                fall back to its 300px intrinsic width instead of filling the row. It
                draws itself left to right once the section is on screen. */}
            <Reveal className="pointer-events-none absolute inset-x-[12%] top-9 hidden lg:block">
              <div className="line-draw border-t-2 border-dashed border-brand-300" />
            </Reveal>

            <ol className="relative grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
              {STEPS.map(({ icon: Icon, step, title, desc }, i) => (
                <Reveal key={step} as="li" delay={i * 120} className="text-center">
                  <div className="relative mx-auto grid h-[72px] w-[72px] place-items-center">
                    <span className="absolute inset-0 rounded-2xl bg-white shadow-lg shadow-slate-900/5 ring-1 ring-slate-200" />
                    <Icon className="relative h-7 w-7 text-brand-600" />
                    <span
                      className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-lg text-[10px] font-bold text-white shadow-md shadow-brand-700/30"
                      style={{ background: "var(--brand-grad)" }}
                    >
                      {step}
                    </span>
                  </div>
                  <h3 className="mt-5 text-xl font-semibold text-slate-900">{title}</h3>
                  <p className="mx-auto mt-2.5 max-w-72 text-base leading-relaxed text-slate-500">
                    {desc}
                  </p>
                </Reveal>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ══ Features ═══════════════════════════════════════════════════ */}
      <section id="features" className="mx-auto max-w-5xl scroll-mt-20 px-5 py-16 sm:px-6 sm:py-24">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            One platform, the whole incentive lifecycle
          </h2>
          <p className="mt-3.5 text-base leading-relaxed text-slate-500 sm:text-lg">
            From the contract you signed to the rupee you can prove you earned.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, desc }, i) => (
            <Reveal key={title} delay={i * 80} className="h-full">
              <SpotlightCard className="h-full rounded-2xl">
                <article className="group h-full rounded-2xl border border-slate-200 bg-white p-6 transition-[border-color,box-shadow] duration-300 hover:border-brand-200 hover:shadow-xl hover:shadow-brand-900/10">
                  <div className="mb-4 grid h-12 w-12 place-items-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 transition-all duration-300 group-hover:scale-110 group-hover:bg-brand-600 group-hover:text-white group-hover:ring-brand-600">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
                  <p className="mt-2 text-base leading-relaxed text-slate-500">{desc}</p>
                </article>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ══ Reconciliation showcase ════════════════════════════════════ */}
      <section id="reconciliation" className="scroll-mt-20 border-y border-slate-100 bg-slate-50/70">
        <div className="mx-auto grid max-w-5xl items-center gap-12 px-5 py-16 sm:px-6 sm:py-24 lg:grid-cols-2">
          <Reveal>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-700">
              <GitCompareArrows className="h-3.5 w-3.5" /> Reconciliation
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              The summary should equal the detail. Always.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-slate-500 sm:text-lg">
              fareqube recomputes the per-airline summary straight from the detailed
              rows and puts it beside the one the vendor printed. When they disagree,
              the exact line is flagged — never rounded away.
            </p>

            <ul className="mt-7 space-y-3.5">
              {[
                "Cancellation charges distributed to the exact tickets they belong to",
                "Every derived row traceable back to its source document",
                "Debit and credit memos kept in the bucket the vendor billed them in",
              ].map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <span className="mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-emerald-500">
                    <CheckSquare className="h-3 w-3 text-white" />
                  </span>
                  <span className="text-base leading-relaxed text-slate-600">{t}</span>
                </li>
              ))}
            </ul>

            <Link
              href="/signup"
              className="group mt-8 inline-flex items-center gap-2 text-base font-semibold text-brand-700 hover:text-brand-800"
            >
              See it on your own statement
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
          </Reveal>

          <Reveal delay={120}>
            <div className="relative rounded-2xl border border-slate-200 bg-white p-5 shadow-xl shadow-slate-900/5 sm:p-6">
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-700">Summary comparison</p>
                <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
                  0 mismatches
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[19rem]">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400">
                      <th className="pb-2 font-semibold">Airline</th>
                      <th className="pb-2 text-right font-semibold">Uploaded</th>
                      <th className="pb-2 text-right font-semibold">Calculated</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono text-xs tabular-nums">
                    {[
                      ["071 ET", "44,20,412", "44,20,412"],
                      ["157 QR", "22,13,601", "22,13,601"],
                      ["176 EK", "46,54,961", "46,54,961"],
                      ["098 AI", "1,24,93,977", "1,24,93,977"],
                    ].map(([air, up, calc], i) => (
                      <tr
                        key={air}
                        className="animate-fade-up border-t border-slate-100"
                        style={{ animationDelay: `${i * 110}ms` }}
                      >
                        <td className="py-2.5 font-sans text-xs font-semibold text-slate-600">
                          {air}
                        </td>
                        <td className="py-2.5 text-right text-slate-500">{up}</td>
                        <td className="py-2.5 text-right font-semibold text-emerald-600">{calc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* bar motif — decorative */}
              <div className="mt-5 flex items-end gap-1.5 border-t border-slate-100 pt-5">
                {[40, 65, 48, 82, 58, 91, 70, 96].map((h, i) => (
                  <span
                    key={i}
                    className="animate-bar flex-1 origin-bottom rounded-t bg-gradient-to-t from-brand-600/80 to-brand-300/70"
                    style={{ height: `${h * 0.5}px`, animationDelay: `${i * 70}ms` }}
                  />
                ))}
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ══ CTA ════════════════════════════════════════════════════════ */}
      <section className="px-5 py-16 sm:px-6 sm:py-24">
        <Reveal className="mx-auto max-w-5xl">
          <div
            className="relative overflow-hidden rounded-3xl px-7 py-14 text-center sm:px-14 sm:py-20"
            style={{ background: "var(--brand-deep)" }}
          >
            {/* decorative flight arc */}
            <svg
              className="pointer-events-none absolute inset-0 h-full w-full opacity-30"
              viewBox="0 0 800 300"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path
                d="M-20 250 Q 400 20 820 180"
                fill="none"
                stroke="rgba(180,208,238,0.55)"
                strokeWidth="2"
                strokeDasharray="8 10"
                className="animate-draw"
              />
            </svg>
            <div className="animate-aurora pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-brand-400/25 blur-3xl" />
            <div
              className="animate-aurora pointer-events-none absolute -bottom-24 -left-16 h-64 w-64 rounded-full bg-accent-500/15 blur-3xl"
              style={{ animationDelay: "5s" }}
            />

            <div className="relative">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-accent-300 ring-1 ring-white/20 backdrop-blur">
                <Plane className="h-4 w-4 -rotate-45" />
                {TAGLINE}
              </span>
              <h2 className="mt-5 text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Close your next BSP period with zero variance
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-brand-100/85 sm:text-lg">
                Create your account in minutes. The first person to sign up with a
                company email becomes the admin for their workspace.
              </p>

              <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Link
                  href="/signup"
                  className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-brand-800 shadow-lg transition-all hover:-translate-y-0.5 hover:shadow-xl sm:w-auto"
                >
                  Create your account
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Link>
                <Link
                  href="/login"
                  className="inline-flex w-full items-center justify-center rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10 sm:w-auto"
                >
                  Sign in
                </Link>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* ══ Footer ═════════════════════════════════════════════════════ */}
      <footer className="border-t border-slate-200/80 bg-slate-50/60">
        <div className="mx-auto max-w-5xl px-5 py-12 sm:px-6 sm:py-14">
          <div className="flex flex-col gap-10 sm:flex-row sm:justify-between">
            <div className="max-w-xs">
              <Logo className="h-12 w-auto" />
              <p className="mt-4 text-sm leading-relaxed text-slate-500">
                Contracts, vendor statements, reconciliation and approvals — one
                platform, built for travel agencies and consolidators.
              </p>
              <Link
                href="/"
                className="mt-4 inline-block text-sm font-semibold text-brand-700 transition-colors hover:text-brand-800"
              >
                fareqube.com
              </Link>
            </div>

            <div className="grid grid-cols-2 gap-x-12 gap-y-3 sm:gap-x-16">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
                  Product
                </p>
                <ul className="mt-3.5 space-y-2.5 text-sm">
                  {FOOTER_LINKS.map((l) => (
                    <li key={l.href}>
                      <a
                        href={l.href}
                        className="text-slate-600 transition-colors hover:text-brand-700"
                      >
                        {l.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
                  Account
                </p>
                <ul className="mt-3.5 space-y-2.5 text-sm">
                  <li>
                    <Link href="/login" className="text-slate-600 transition-colors hover:text-brand-700">
                      Log in
                    </Link>
                  </li>
                  <li>
                    <Link href="/signup" className="text-slate-600 transition-colors hover:text-brand-700">
                      Sign up
                    </Link>
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <div className="mt-10 flex flex-col items-center justify-between gap-3 border-t border-slate-200 pt-6 sm:flex-row">
            <p className="text-sm text-slate-400">© 2026 fareqube · All rights reserved</p>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-400">
              {TAGLINE}
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
