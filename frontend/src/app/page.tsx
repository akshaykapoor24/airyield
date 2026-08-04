import Link from "next/link";
import type { Metadata } from "next";
import {
  ArrowRight, BarChart3, Calculator, CheckSquare, FileSpreadsheet,
  FileText, GitCompareArrows, Layers, Plane, ShieldCheck, Sparkles, Upload, Zap,
} from "lucide-react";
import Logo from "@/components/marketing/Logo";
import SiteNav from "@/components/marketing/SiteNav";
import HeroVisual from "@/components/marketing/HeroVisual";
import { Counter, Reveal } from "@/components/marketing/Reveal";

export const metadata: Metadata = {
  title: "FareQube — Airline Deal & Incentive Income Platform",
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

type Stat = {
  value: number;
  label: string;
  prefix?: string;
  suffix?: string;
  decimals?: number;
};

const STATS: Stat[] = [
  { value: 200, suffix: "+", label: "Airline codes supported" },
  { value: 2000, suffix: "+", label: "Pages parsed per statement" },
  { value: 99.9, suffix: "%", decimals: 1, label: "Reconciliation accuracy" },
  { value: 0, prefix: "₹", label: "Variance, when it's right" },
];

const TRUST = ["BSP · LCC · Third-party", "PAN & GST ready", "Role-based approvals"];

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <SiteNav />

      {/* ══ Hero ═══════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        {/* backdrop */}
        <div className="pointer-events-none absolute inset-0 -z-10">
          <div className="grid-bg grid-mask absolute inset-0" />
          <div className="animate-blob animate-aurora absolute -left-24 -top-24 h-[26rem] w-[26rem] bg-blue-400/25 blur-3xl" />
          <div
            className="animate-blob animate-aurora absolute -right-16 top-10 h-[22rem] w-[22rem] bg-sky-300/25 blur-3xl"
            style={{ animationDelay: "3s" }}
          />
          <div
            className="animate-blob animate-aurora absolute bottom-0 left-1/3 h-[18rem] w-[18rem] bg-orange-300/20 blur-3xl"
            style={{ animationDelay: "6s" }}
          />
        </div>

        <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-12 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:pb-28 lg:pt-20">
          {/* copy */}
          <div className="text-center lg:text-left">
            <div className="animate-fade-up inline-flex items-center gap-2 rounded-full border border-blue-200/70 bg-blue-50/80 px-4 py-1.5 text-sm font-semibold text-blue-700 backdrop-blur">
              <Sparkles className="h-4 w-4" />
              Built for travel agencies &amp; consolidators
            </div>

            <h1
              className="animate-fade-up mt-6 text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl lg:text-[3.4rem]"
              style={{ animationDelay: "80ms" }}
            >
              Every rupee of airline
              <br className="hidden sm:block" />{" "}
              <span className="text-gradient">incentive, accounted for.</span>
            </h1>

            <p
              className="animate-fade-up mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-slate-500 sm:text-xl lg:mx-0"
              style={{ animationDelay: "160ms" }}
            >
              FareQube turns airline contracts and vendor statements into reconciled,
              auditable income — from a 2,000-page BSP file to a zero-variance
              summary, without a single spreadsheet.
            </p>

            <div
              className="animate-fade-up mt-9 flex flex-col items-center gap-3 sm:flex-row lg:justify-start"
              style={{ animationDelay: "240ms" }}
            >
              <Link
                href="/signup"
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-blue-500/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-500/40 sm:w-auto"
                style={{ background: "var(--brand-grad)" }}
              >
                Start free
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
              className="animate-fade-up mt-8 flex flex-wrap justify-center gap-x-5 gap-y-2 text-sm text-slate-500 lg:justify-start"
              style={{ animationDelay: "320ms" }}
            >
              {TRUST.map((t) => (
                <span key={t} className="inline-flex items-center gap-1.5">
                  <ShieldCheck className="h-4 w-4 text-emerald-500" />
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

        {/* airline code marquee */}
        <div className="relative border-y border-slate-100 bg-slate-50/60 py-5">
          <p className="mb-4 text-center text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
            Reconciles settlement data across carriers
          </p>
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

      {/* ══ Stats ══════════════════════════════════════════════════════ */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-20">
        <div className="grid grid-cols-2 gap-6 lg:grid-cols-4">
          {STATS.map((s, i) => (
            <Reveal key={s.label} delay={i * 90} className="text-center">
              <p className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                <Counter
                  value={s.value}
                  prefix={s.prefix}
                  suffix={s.suffix}
                  decimals={s.decimals ?? 0}
                />
              </p>
              <p className="mx-auto mt-2 max-w-48 text-sm leading-relaxed text-slate-500">
                {s.label}
              </p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ══ How it works ═══════════════════════════════════════════════ */}
      <section className="relative overflow-hidden border-y border-slate-100 bg-slate-50/70">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
          <Reveal className="mx-auto max-w-2xl text-center">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-blue-700">
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
                fall back to its 300px intrinsic width instead of filling the row */}
            <div
              className="pointer-events-none absolute inset-x-[12%] top-9 hidden border-t-2 border-dashed border-slate-300 lg:block"
              aria-hidden="true"
            />

            <ol className="relative grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
              {STEPS.map(({ icon: Icon, step, title, desc }, i) => (
                <Reveal key={step} as="li" delay={i * 120} className="text-center">
                  <div className="relative mx-auto grid h-[72px] w-[72px] place-items-center">
                    <span className="absolute inset-0 rounded-2xl bg-white shadow-lg shadow-slate-900/5 ring-1 ring-slate-200" />
                    <Icon className="relative h-7 w-7 text-blue-600" />
                    <span
                      className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-lg text-[10px] font-bold text-white shadow-md shadow-blue-500/30"
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
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
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
            <Reveal key={title} delay={i * 80}>
              <article className="lift group h-full rounded-2xl border border-slate-200 bg-white p-6 hover:border-blue-200 hover:shadow-xl hover:shadow-blue-900/5">
                <div className="mb-4 grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-blue-600 transition-all duration-300 group-hover:scale-110 group-hover:bg-blue-600 group-hover:text-white">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
                <p className="mt-2 text-base leading-relaxed text-slate-500">{desc}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ══ Reconciliation showcase ════════════════════════════════════ */}
      <section className="border-y border-slate-100 bg-slate-50/70">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 sm:px-6 sm:py-24 lg:grid-cols-2">
          <Reveal>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-700">
              <GitCompareArrows className="h-3.5 w-3.5" /> Reconciliation
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              The summary should equal the detail. Always.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-slate-500 sm:text-lg">
              FareQube recomputes the per-airline summary straight from the detailed
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
              className="group mt-8 inline-flex items-center gap-2 text-base font-semibold text-blue-600 hover:text-blue-700"
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
                    className="animate-bar flex-1 origin-bottom rounded-t bg-gradient-to-t from-blue-500/70 to-sky-400/70"
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
        <Reveal className="mx-auto max-w-6xl">
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
                stroke="rgba(191,219,254,0.5)"
                strokeWidth="2"
                strokeDasharray="8 10"
                className="animate-draw"
              />
            </svg>
            <div className="animate-aurora pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-sky-400/20 blur-3xl" />

            <div className="relative">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-4 py-1.5 text-sm font-semibold text-blue-100 ring-1 ring-white/20">
                <Plane className="h-4 w-4 -rotate-45" />
                Ready when you are
              </span>
              <h2 className="mt-5 text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Close your next BSP period with zero variance
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-blue-100/80 sm:text-lg">
                Create your account in minutes. The first person to sign up with a
                company email becomes the admin for their workspace.
              </p>

              <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Link
                  href="/signup"
                  className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-blue-700 shadow-lg transition-all hover:-translate-y-0.5 hover:shadow-xl sm:w-auto"
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
      <footer className="border-t border-slate-100">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-5 px-5 py-9 sm:flex-row sm:px-6">
          <Logo />
          <p className="order-last text-sm text-slate-400 sm:order-none">
            © 2026 FareQube · All rights reserved
          </p>
          <div className="flex items-center gap-5 text-base font-medium">
            <Link href="/login" className="text-slate-600 transition-colors hover:text-slate-900">
              Log in
            </Link>
            <Link href="/signup" className="text-slate-600 transition-colors hover:text-slate-900">
              Sign up
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
