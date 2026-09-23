import { Fragment } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import {
  ArrowRight, BarChart3, Calculator, CheckSquare, History, Layers,
  ShieldCheck, Upload,
} from "lucide-react";
import Logo from "@/components/marketing/Logo";
import SiteNav from "@/components/marketing/SiteNav";
import PaperPlane from "@/components/marketing/PaperPlane";
import PlatformMap from "@/components/marketing/PlatformMap";
import RouteNetwork from "@/components/marketing/RouteNetwork";
import SettlementBoard from "@/components/marketing/SettlementBoard";
import SpotlightCard from "@/components/marketing/SpotlightCard";
import ContactModal, { ContactButton } from "@/components/marketing/ContactModal";
import { CONTACT_EMAIL } from "@/lib/contact";
import { Counter, Reveal } from "@/components/marketing/Reveal";

// The tab title is the brand lockup itself — "fareqube — Automation that ascends", the
// root layout's `title.default`. The searchable specifics stay in the description, which is
// what a search snippet shows anyway.
export const metadata: Metadata = {
  description:
    "Manage airline contracts, ingest BSP and LCC statements, reconcile tickets to zero variance, and calculate incentive income — in one platform built for travel agencies.",
};

/** The logo's tagline, set in live text so the promise is on the page, not just in pixels. */
const TAGLINE = "Automation that ascends";

/** The headline, split so each word can be animated on its own. */
const HEADLINE = ["Automation", "that", "Ascends"];

/** The content column. 1180px — wide enough for a two-up pillar without the copy
 *  stretching past a comfortable measure. */
const WRAP = "mx-auto w-full max-w-[1180px] px-6 sm:px-8";

/** Everything the platform covers, as the navy band lists it. */
const ONE_STOP = [
  "Booking engine",
  "Revenue recording across airlines, hotels, rail, bus, and packages",
  "Accurate income calculations",
  "Deposits, collections, and invoicing",
  "Supplier bookings, cost tracking, invoice verification, and payment processing",
  "Profit calculations, from gross margin to net profit per booking",
  "Bank and account reconciliations",
  "Refunds, chargebacks, and cancellations",
  "Compliance, financial, and MIS reporting",
];

const STEPS = [
  { icon: Upload, step: "01", title: "Upload", desc: "BSP, LCC and third-party statements, plus your own ticket files." },
  { icon: Layers, step: "02", title: "Match", desc: "Tickets are matched to deals and to their settlement rows automatically." },
  { icon: Calculator, step: "03", title: "Calculate", desc: "Incentive slabs and exclusions applied to produce income per ticket." },
  { icon: ShieldCheck, step: "04", title: "Reconcile", desc: "Uploaded totals meet calculated totals — variances surfaced, not buried." },
];

/** The lifecycle pieces that sit around the three pillars below. */
const ALSO = [
  { icon: Calculator, title: "Income calculation", desc: "Slabs, PLB, exclusions and segment rules applied per ticket." },
  { icon: CheckSquare, title: "Approval workflows", desc: "Deals and overrides routed through a role-based matrix." },
  { icon: BarChart3, title: "Live dashboards", desc: "Income trends and pending actions, updated as statements land." },
  { icon: History, title: "Audit trail", desc: "Every decision and derived figure traceable to who and what." },
];

/**
 * PLACEHOLDER FIGURES — verify before launch.
 *
 * These are capability claims about the platform, not customer outcomes, which is the
 * safer thing to put on a home page you cannot yet cite a case study for. Swap them for
 * measured numbers (or real customer outcomes) once you have them, and keep the labels
 * honest about which kind of number each one is.
 */
const STATS = [
  { value: 2000, suffix: "+", label: "Pages in a single BSP statement, parsed unattended in the background." },
  { value: 200, suffix: "+", label: "Airline codes covered, across BSP, LCC and third-party settlement." },
  { value: 0, prefix: "₹", label: "Variance on a period that closes clean — the only number worth shipping." },
];

const EYEBROW =
  "text-[13px] font-semibold uppercase tracking-[0.14em] text-brand-600";

/* ══════════════════════════════════════════════════════════════════════════
   Pillar artwork — the one visual that did not already exist
   ════════════════════════════════════════════════════════════════════════ */

/**
 * A contract as the platform holds it: slabs, a validity window, and the exclusions
 * that would otherwise live in a footnote nobody applies. Illustrative, not live data.
 */
function DealCard() {
  const SLABS = [
    ["₹0 – 50 L", "2.00%", false],
    ["₹50 L – 1 Cr", "2.50%", false],
    ["₹1 Cr and above", "3.00%", true],
  ] as const;

  return (
    <div className="rounded-2xl border border-line bg-white p-5 shadow-xl shadow-brand-900/5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Incentive deal
          </p>
          <p className="display mt-1 text-lg font-semibold text-brand-900">Emirates · 176 EK</p>
          <p className="mt-0.5 text-[13px] text-slate-500">B2B · International · 01 Apr 26 → 31 Mar 27</p>
        </div>
        <span className="shrink-0 rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
          Active
        </span>
      </div>

      <div className="mt-5 overflow-hidden rounded-xl border border-line">
        <div className="flex items-center justify-between bg-paper px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          <span>Net sales slab</span>
          <span>Incentive</span>
        </div>
        <ul>
          {SLABS.map(([band, rate, current]) => (
            <li
              key={band}
              className={`flex items-center justify-between border-t border-line px-4 py-2.5 text-sm ${
                current ? "bg-accent-50" : "bg-white"
              }`}
            >
              <span className={current ? "font-semibold text-brand-900" : "text-slate-600"}>
                {band}
              </span>
              <span className="flex items-center gap-2">
                {current && (
                  <span className="rounded-md bg-accent-500 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                    Current
                  </span>
                )}
                <span
                  className={`font-mono text-sm tabular-nums ${
                    current ? "font-semibold text-accent-600" : "text-slate-500"
                  }`}
                >
                  {rate}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-4 text-[13px] leading-relaxed text-slate-500">
        <span className="font-semibold text-slate-600">Excludes</span> — ADMs, refunded
        coupons, infant fares and YQ on codeshare segments.
      </p>
    </div>
  );
}

/**
 * A statement mid-ingestion. The point it makes is the progress bar: the file is being
 * read page by page on a worker, not in the tab the user is waiting in. Illustrative.
 */
function IngestionCard() {
  const COUNTS = [
    ["Tickets found", "15,204"],
    ["ADM / ACM rows", "38"],
    ["Refunds", "412"],
  ];

  return (
    <div className="rounded-2xl border border-line bg-white p-5 shadow-xl shadow-brand-900/5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Statement batch
          </p>
          <p className="display mt-1 text-lg font-semibold text-brand-900">BSP 14-3</p>
          <p className="mt-0.5 text-[13px] text-slate-500">01 Jul → 07 Jul 2026 · 176 EK</p>
        </div>
        <span className="shrink-0 rounded-full bg-accent-50 px-3 py-1 text-[11px] font-semibold text-accent-600 ring-1 ring-accent-200">
          Parsing
        </span>
      </div>

      <div className="mt-5 rounded-xl border border-line bg-paper p-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="truncate font-mono text-[12px] text-slate-500">
            emirates-bsp-14-3.pdf
          </span>
          <span className="shrink-0 font-mono text-[12px] tabular-nums text-brand-700">
            1,203 / 1,842
          </span>
        </div>
        <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-brand-100">
          <div
            className="h-full rounded-full"
            style={{ width: "65%", background: "var(--brand-grad)" }}
          />
        </div>
        <p className="mt-2.5 text-[12px] text-slate-400">
          Parsed on a background worker — close the tab if you like.
        </p>
      </div>

      <dl className="mt-4 divide-y divide-line">
        {COUNTS.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between py-2.5">
            <dt className="text-[14px] text-slate-600">{label}</dt>
            <dd className="font-mono text-[14px] font-semibold tabular-nums text-brand-900">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The reconciliation proof: what the vendor printed, beside what the detail adds up to. */
function ReconciliationCard() {
  const ROWS = [
    ["071 ET", "44,20,412", "44,20,412"],
    ["157 QR", "22,13,601", "22,13,601"],
    ["176 EK", "46,54,961", "46,54,961"],
    ["098 AI", "1,24,93,977", "1,24,93,977"],
  ];

  return (
    <div className="relative rounded-2xl border border-line bg-white p-5 shadow-xl shadow-brand-900/5 sm:p-6">
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
            {ROWS.map(([air, up, calc], i) => (
              <tr
                key={air}
                className="animate-fade-up border-t border-line"
                style={{ animationDelay: `${i * 110}ms` }}
              >
                <td className="py-2.5 font-sans text-xs font-semibold text-slate-600">{air}</td>
                <td className="py-2.5 text-right text-slate-500">{up}</td>
                <td className="py-2.5 text-right font-semibold text-emerald-600">{calc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* bar motif — decorative */}
      <div className="mt-5 flex items-end gap-1.5 border-t border-line pt-5">
        {[40, 65, 48, 82, 58, 91, 70, 96].map((h, i) => (
          <span
            key={i}
            className="animate-bar flex-1 origin-bottom rounded-t bg-gradient-to-t from-brand-600/80 to-brand-300/70"
            style={{ height: `${h * 0.5}px`, animationDelay: `${i * 70}ms` }}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * One alternating capability block: copy on one side, artwork on the other. `flip` puts
 * the artwork on the left — done with grid column placement rather than `direction: rtl`,
 * so the order the screen reader hears stays copy-then-artwork either way.
 */
function Pillar({
  eyebrow,
  title,
  body,
  points,
  art,
  flip = false,
}: {
  eyebrow: string;
  title: string;
  body: string;
  points: string[];
  art: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <div className="grid items-center gap-12 py-14 lg:grid-cols-2 lg:gap-16 lg:py-20">
      <Reveal className={flip ? "lg:col-start-2" : undefined}>
        <p className={EYEBROW}>{eyebrow}</p>
        <h2 className="mt-3 max-w-md text-[28px] font-semibold leading-[1.2] text-brand-900 sm:text-[32px]">
          {title}
        </h2>
        <p className="mt-4 max-w-md text-base leading-relaxed text-slate-500 sm:text-[17px]">
          {body}
        </p>
        <ul className="tick-list mt-6 space-y-3">
          {points.map((p) => (
            <li key={p} className="text-[15px] leading-relaxed text-slate-600">
              {p}
            </li>
          ))}
        </ul>
      </Reveal>

      <Reveal delay={120} className={flip ? "lg:col-start-1 lg:row-start-1" : undefined}>
        {art}
      </Reveal>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Page
   ════════════════════════════════════════════════════════════════════════ */

export default function HomePage() {
  return (
    <div className="marketing min-h-screen bg-white text-slate-900">
      <SiteNav />
      {/* One dialog for the whole page; every Contact trigger opens this instance. */}
      <ContactModal />

      {/* ══ Hero ═══════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        {/* Positioned but not at a negative z-index: `-z-10` would put this underneath
            the page wrapper's own white background — the wrapper is a non-positioned
            block, and those paint after negative-z layers — so the plane would never
            show. It sits at the default layer and the copy is lifted to `z-10`. */}
        <div className="pointer-events-none absolute inset-0">
          <PaperPlane className="absolute left-0 top-[2%] hidden w-[52%] lg:block" />
        </div>

        <div className={`${WRAP} relative z-10`}>
          <div className="grid items-center gap-14 pb-20 pt-14 lg:grid-cols-2 lg:gap-16 lg:pb-28 lg:pt-20">
            <div>
              {/* Each word rises on its own beat, and the last one keeps moving after it
                  lands — the gradient sweep loops, so the line the brand is named for is
                  never completely still. The rise and the sweep sit on nested spans
                  because both are `animation`, and one element can only run the last one
                  the stylesheet declares. */}
              <h1 className="max-w-xl text-[40px] font-semibold leading-[1.08] tracking-tight text-brand-900 sm:text-[52px] lg:text-[60px]">
                {HEADLINE.map((word, i) => (
                  <Fragment key={word}>
                    <span
                      className="animate-fade-up inline-block"
                      style={{ animationDelay: `${i * 130}ms` }}
                    >
                      {i === HEADLINE.length - 1 ? (
                        <span className="text-gradient">{word}</span>
                      ) : (
                        word
                      )}
                    </span>{" "}
                  </Fragment>
                ))}
              </h1>

              <p
                className="animate-fade-up mt-7 max-w-lg text-[17px] leading-[1.65] text-slate-500"
                style={{ animationDelay: "440ms" }}
              >
                fareqube streamlines travel business operations with end-to-end booking,
                revenue, and cost tracking across airlines, hotels, rail, bus, and packages.
                It automates income and profit calculations, invoicing, payments, and
                reconciliations, while enabling accurate MIS reporting on margins, refunds,
                cancellations, and compliance.
              </p>

              <div
                className="animate-fade-up mt-9 flex flex-col gap-4 sm:flex-row sm:items-center"
                style={{ animationDelay: "560ms" }}
              >
                <Link
                  href="/signup"
                  className="btn-sheen group inline-flex w-full items-center justify-center gap-2 rounded-lg px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-brand-700/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brand-700/30 sm:w-auto"
                  style={{ background: "var(--brand-grad)" }}
                >
                  Create an account
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Link>
                <Link
                  href="/login"
                  className="inline-flex w-full items-center justify-center rounded-lg border-2 border-line px-7 py-3.5 text-base font-semibold text-brand-900 transition-colors hover:border-brand-300 hover:bg-brand-50 sm:w-auto"
                >
                  Sign in
                </Link>
              </div>
            </div>

            <div className="lg:pl-4">
              <PlatformMap />
            </div>
          </div>
        </div>
      </section>

      {/* ══ Network band — the route map ══════════════════════════════
          The airline-code marquee that used to run under this is gone; the map alone
          carries the band. */}
      <section className="relative overflow-hidden border-y border-line bg-paper py-10">
        <p className="text-center text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
          Reconciles settlement data across line of business
        </p>
        <div className="mx-auto mt-2 h-[160px] w-full max-w-[1180px] px-6 sm:h-[215px] sm:px-8">
          <RouteNetwork />
        </div>
      </section>

      {/* ══ About — what we do, vision, mission ════════════════════════ */}
      <section id="about" className="scroll-mt-20 border-b border-line bg-paper">
        <div className={`${WRAP} py-16 sm:py-24`}>
          <Reveal className="mx-auto max-w-3xl text-center">
            {/* "About us", not "About fareqube": EYEBROW sets `uppercase`, which would
                render the brand as FAREQUBE. The wordmark is lowercase. */}
            <p className={EYEBROW}>About us</p>
            <h2 className="mt-3 text-[30px] font-semibold leading-tight text-brand-900 sm:text-[36px]">
              What we do
            </h2>
            <p className="mt-5 text-[17px] leading-relaxed text-slate-500">
              fareqube is the income layer for travel agencies and consolidators. It holds
              every airline contract you have signed, reads the statements your suppliers
              send, and turns the two into incentive income you can prove — per ticket, per
              settlement event, per period. The contract, the calculation and the evidence
              stay in one place, so the number you report is the number you can defend.
            </p>
          </Reveal>

          <div className="mx-auto mt-14 grid max-w-4xl gap-6 md:grid-cols-2">
            {[
              {
                eyebrow: "Vision",
                body: "A travel business should never have to guess what it earned. We are building the system of record for airline incentive income — one where the figure on the dashboard and the figure in the contract are the same figure, every cycle.",
              },
              {
                eyebrow: "Mission",
                body: "Retire the spreadsheet chain. Every slab, exclusion and memo applied by the platform rather than by memory; every derived figure traceable to the document it came from; every period closed at zero variance.",
              },
            ].map(({ eyebrow, body }, i) => (
              <Reveal key={eyebrow} delay={i * 120} className="h-full">
                <div className="h-full rounded-2xl border border-line bg-white p-7">
                  <p className={EYEBROW}>{eyebrow}</p>
                  <p className="mt-3.5 text-base leading-relaxed text-slate-600">{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ══ Platform — the three pillars ═══════════════════════════════ */}
      <section id="platform" className={`${WRAP} scroll-mt-20 py-16 sm:py-20`}>
        <Reveal className="mx-auto max-w-2xl text-center">
          <p className={EYEBROW}>The platform</p>
          <h2 className="mt-3 text-[30px] font-semibold leading-tight text-brand-900 sm:text-[36px]">
            From the contract you signed to the rupee you can prove you earned
          </h2>
        </Reveal>

        <div className="divide-y divide-line">
          <Pillar
            eyebrow="Deals & contracts"
            title="Your contracts, turned into rules the system can run"
            body="Incentive slabs, PLB, validity windows and exclusions captured once — across B2B, B2C and B2E — then applied to every ticket that touches them, without anyone having to remember the footnotes."
            points={[
              "Slab, PLB and flat-rate structures, each with its own validity window",
              "Carrier, route, class and segment exclusions held as rules, not footnotes",
              "Overrides routed through a role-based approval matrix, with the reason kept",
            ]}
            art={<DealCard />}
          />

          <Pillar
            flip
            eyebrow="Statement ingestion"
            title="A two-thousand-page statement, read for you"
            body="Drop a BSP PDF, an LCC export or a third-party file. It is parsed page by page in the background, so a heavy file never blocks the day — and every row it produces still points back to the page it came from."
            points={[
              "BSP, LCC and third-party statements through one pipeline",
              "Background parsing with per-batch progress, not a frozen tab",
              "ADMs, ACMs and refunds kept in the bucket the vendor billed them in",
            ]}
            art={<IngestionCard />}
          />

          <Pillar
            eyebrow="Reconciliation"
            title="The summary should equal the detail. Always."
            body="fareqube recomputes the per-airline summary straight from the detailed rows and puts it beside the one the vendor printed. When they disagree, the exact line is flagged — never rounded away."
            points={[
              "Cancellation charges distributed to the exact tickets they belong to",
              "Every derived row traceable back to its source document",
              "Variances surfaced as work to do, not buried in a total",
            ]}
            art={<ReconciliationCard />}
          />
        </div>
      </section>

      {/* ══ Settlement board ═══════════════════════════════════════════
          Full width on purpose: the board carries four columns of split-flap cells and
          clips to two inside a half-width pillar. */}
      <div className={`${WRAP} pb-16 sm:pb-20`}>
        <SettlementBoard />
      </div>

      {/* ══ The rest of the lifecycle ══════════════════════════════════ */}
      <section className="border-y border-line bg-paper">
        <div className={`${WRAP} py-16 sm:py-20`}>
          <Reveal className="mx-auto max-w-2xl text-center">
            <h2 className="text-[26px] font-semibold leading-tight text-brand-900 sm:text-[30px]">
              And everything that surrounds it
            </h2>
          </Reveal>

          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {ALSO.map(({ icon: Icon, title, desc }, i) => (
              <Reveal key={title} delay={i * 80} className="h-full">
                <SpotlightCard className="h-full rounded-2xl">
                  <article className="lift group h-full rounded-2xl border border-line bg-white p-6 hover:border-brand-200 hover:shadow-xl hover:shadow-brand-900/10">
                    <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 transition-all duration-300 group-hover:bg-brand-600 group-hover:text-white group-hover:ring-brand-600">
                      <Icon className="h-5 w-5" />
                    </div>
                    <h3 className="text-[17px] font-semibold text-brand-900">{title}</h3>
                    <p className="mt-2 text-[15px] leading-relaxed text-slate-500">{desc}</p>
                  </article>
                </SpotlightCard>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ══ How it works ═══════════════════════════════════════════════ */}
      <section id="pipeline" className={`${WRAP} scroll-mt-20 py-16 sm:py-24`}>
        <Reveal className="max-w-xl">
          <p className={EYEBROW}>How it works</p>
          <h2 className="mt-3 text-[30px] font-semibold leading-tight text-brand-900 sm:text-[36px]">
            Statement in. Reconciled income out.
          </h2>
          <p className="mt-4 text-[17px] leading-relaxed text-slate-500">
            Four steps run end to end, and the heavy parsing happens in the background — so a
            thousand-page file never blocks your day.
          </p>
        </Reveal>

        <div className="relative mt-14">
          {/* The rule the step markers sit on. A dashed border stretches reliably where an
              inline SVG would fall back to its intrinsic width; it draws itself left to
              right once the section scrolls into view. */}
          <Reveal className="pointer-events-none absolute inset-x-0 top-[19px] hidden lg:block">
            <div className="line-draw border-t-2 border-dashed border-brand-200" />
          </Reveal>

          <ol className="relative grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
            {STEPS.map(({ icon: Icon, step, title, desc }, i) => (
              <Reveal key={step} as="li" delay={i * 120} className="lg:pr-6">
                {/* The marker row carries the page background so the dashed rule passes
                    behind it rather than straight through the number and the icon. */}
                <div className="relative z-10 flex w-fit items-center gap-3 bg-white pr-4">
                  <span className="display grid h-[38px] w-[38px] shrink-0 place-items-center rounded-full border-2 border-brand-500 text-[15px] font-semibold text-brand-600">
                    {step}
                  </span>
                  <Icon className="h-5 w-5 text-brand-400" />
                </div>
                <h3 className="mt-5 text-[19px] font-semibold text-brand-900">{title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-500">{desc}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ══ Stats ══════════════════════════════════════════════════════ */}
      <section className="border-y border-line bg-white">
        <div className={`${WRAP} grid gap-10 py-16 sm:py-20 md:grid-cols-3 md:gap-12`}>
          {STATS.map(({ value, prefix, suffix, label }, i) => (
            <Reveal key={label} delay={i * 120}>
              <Counter
                value={value}
                prefix={prefix}
                suffix={suffix}
                className="display block text-[52px] font-bold leading-none text-accent-500"
              />
              <p className="mt-4 max-w-[17rem] text-[15px] leading-relaxed text-slate-500">
                {label}
              </p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ══ One-stop solution ══════════════════════════════════════════ */}
      <section className="relative overflow-hidden" style={{ background: "var(--brand-deep)" }}>
        <div className="animate-aurora pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-brand-400/20 blur-3xl" />
        <div className={`${WRAP} relative py-14 sm:py-16`}>
          <Reveal>
            <h2 className="text-[28px] font-semibold leading-tight text-white sm:text-[34px]">
              Your one-stop solution for
            </h2>
          </Reveal>

          {/* Two columns from `sm` up. Stacked and indented, nine items ran the band to
              roughly 900px tall while leaving the right half of the page empty; paired
              up it is half the height and uses the full measure.

              CSS columns rather than a grid: a two-column grid fills across, so scanning
              one column gives every other item, and a wrapped item leaves a gap opposite
              it because the row takes the taller height. Columns flow top to bottom, so
              each one reads in order and packs tight. */}
          <ul className="mt-8 sm:columns-2 sm:gap-x-12">
            {ONE_STOP.map((item, i) => (
              <Reveal
                as="li"
                key={item}
                delay={i * 60}
                className="mb-4 flex break-inside-avoid items-start gap-3 text-[15px] leading-relaxed text-brand-50/90 sm:mb-5 sm:text-[16px]"
              >
                <span
                  aria-hidden="true"
                  className="mt-[0.6em] h-1.5 w-1.5 shrink-0 rounded-full bg-brand-200"
                />
                {item}
              </Reveal>
            ))}
          </ul>
        </div>
      </section>

      {/* ══ CTA ════════════════════════════════════════════════════════ */}
      <section className={`${WRAP} py-20 text-center sm:py-28`}>
        <Reveal className="mx-auto max-w-3xl">
          <h2 className="text-[30px] font-semibold leading-[1.28] text-brand-900 sm:text-[38px]">
            See fareqube on your own booking, revenue, and reconciliation data
          </h2>

          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <ContactButton
              className="btn-sheen inline-flex w-full items-center justify-center rounded-lg px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-brand-700/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brand-700/30 sm:w-auto"
              style={{ background: "var(--brand-grad)" }}
            >
              Contact us
            </ContactButton>
            {/* A plain mailto, so this is a genuinely different route from the button
                beside it rather than a second door onto the same dialog. */}
            <a
              href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Sales enquiry")}`}
              className="inline-flex w-full items-center justify-center border-b-2 border-line px-1.5 py-3 text-base font-semibold text-brand-900 transition-colors hover:border-brand-400 sm:w-auto"
            >
              Talk to sales
            </a>
          </div>
        </Reveal>
      </section>

      {/* ══ Footer ═════════════════════════════════════════════════════ */}
      <footer className="border-t border-line bg-paper">
        <div className={`${WRAP} py-9`}>
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              {/* The lockup is the mark plus live text, as in the header — the full logo
                  artwork bakes in the tagline, which is set as its own line below. */}
              <Link href="/" className="flex w-fit items-center gap-2.5" aria-label="fareqube.com home">
                <Logo variant="mark" className="h-7 w-auto" />
                <span className="display text-[19px] font-semibold text-brand-900">fareqube</span>
              </Link>
              <p className="mt-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-brand-600">
                {TAGLINE}
              </p>
            </div>

            {/* Links and the copyright stack on the right, so the footer stays two
                lines tall on either side rather than growing a third row. */}
            <div className="sm:text-right">
              {/* Privacy and Terms are not links yet: neither route exists, and a footer
                  link that 404s is worse than one that waits. Wrap them in <Link> once
                  the pages are there. */}
              <p className="flex items-center gap-2 text-sm text-slate-400 sm:justify-end">
                <span>Privacy</span>
                <span aria-hidden="true">·</span>
                <span>Terms</span>
                <span aria-hidden="true">·</span>
                <ContactButton className="transition-colors hover:text-brand-700">
                  Contact
                </ContactButton>
              </p>
              <p className="mt-2.5 text-[13px] text-slate-400">
                © 2026 fareqube · All rights reserved
              </p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
