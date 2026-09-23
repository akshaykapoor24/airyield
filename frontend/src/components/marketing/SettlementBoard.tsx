import FlipText from "./FlipText";
import { Reveal } from "./Reveal";

type Row = {
  carrier: string;
  doc: string;
  cycle: string;
  status: string;
  /** Settled status tint — green once it balances, amber while it is still working. */
  tone: string;
};

const ROWS: Row[] = [
  { carrier: "EK 176", doc: "BSP 14-3", cycle: "01-07 JUL", status: "RECONCILED", tone: "text-emerald-300" },
  { carrier: "QR 157", doc: "BSP 14-3", cycle: "01-07 JUL", status: "RECONCILED", tone: "text-emerald-300" },
  { carrier: "AI 098", doc: "LCC Q3", cycle: "01-07 JUL", status: "MATCHING", tone: "text-accent-300" },
  { carrier: "ET 071", doc: "BSP 14-3", cycle: "01-07 JUL", status: "RECONCILED", tone: "text-emerald-300" },
];

const CELL = "h-6 w-[0.92rem] text-[11px] sm:h-7 sm:w-[1.08rem] sm:text-[13px]";

/**
 * The settlement board — a Solari split-flap display, the one piece of furniture every
 * airport terminal shares. Each row turns over and settles as the section scrolls into
 * view, which is also exactly what the product does to a statement: shuffle, then settle.
 *
 * The figures are illustrative, not live data.
 */
export default function SettlementBoard() {
  return (
    <Reveal
      className="relative overflow-hidden rounded-3xl p-5 shadow-2xl shadow-brand-900/25 ring-1 ring-white/10 sm:p-8"
      as="section"
    >
      <div
        className="pointer-events-none absolute inset-0 -z-10"
        style={{ background: "var(--brand-deep)" }}
        aria-hidden="true"
      />
      <div className="grid-bg pointer-events-none absolute inset-0 -z-10 opacity-[0.14]" aria-hidden="true" />
      {/* radar sweep across the housing */}
      <div className="pointer-events-none absolute inset-y-0 -inset-x-1/3 -z-10 overflow-hidden" aria-hidden="true">
        <div className="animate-sweep h-full w-1/3 skew-x-12 bg-gradient-to-r from-transparent via-white/[0.07] to-transparent" />
      </div>

      {/* housing header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/15 pb-4">
        <div className="flex items-center gap-2.5">
          <span className="relative grid h-2 w-2 place-items-center">
            <span className="animate-pulse-ring absolute inset-0 rounded-full bg-emerald-400" />
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-white">
            Settlement board
          </p>
        </div>
        <p className="font-mono text-[11px] tracking-wider text-brand-200/70">
          PERIOD 14-3 · 2026
        </p>
      </div>

      {/* column headers — the middle two are the first to go on a narrow screen */}
      <div className="mt-5 grid grid-cols-[6rem_1fr] sm:grid-cols-[7.2rem_9.2rem_10.2rem_1fr] items-center gap-x-3 px-3 text-[9px] font-bold uppercase tracking-[0.18em] text-brand-200/60">
        <span>Carrier</span>
        <span className="hidden sm:block">Statement</span>
        <span className="hidden sm:block">Cycle</span>
        <span className="justify-self-end sm:justify-self-start">Status</span>
      </div>

      <div className="mt-2.5 space-y-2">
        {ROWS.map((r, i) => (
          <div
            key={r.carrier}
            className="grid grid-cols-[6rem_1fr] sm:grid-cols-[7.2rem_9.2rem_10.2rem_1fr] items-center gap-x-3 rounded-xl bg-white/[0.04] px-3 py-2.5 ring-1 ring-white/[0.06]"
          >
            <FlipText text={r.carrier} delay={i * 140} cellClassName={CELL} />
            {/* The narrow layout drops these two columns. `hidden` has to sit on a wrapper,
                not on FlipText: FlipText sets `inline-flex` on itself, and between two
                display utilities it is stylesheet order — not class order — that decides,
                so `hidden` on the same element loses. */}
            <span className="hidden sm:block">
              <FlipText
                text={r.doc}
                delay={i * 140 + 90}
                cellClassName={CELL}
                glyphClassName="text-brand-100"
              />
            </span>
            <span className="hidden sm:block">
              <FlipText
                text={r.cycle}
                delay={i * 140 + 180}
                cellClassName={CELL}
                glyphClassName="text-brand-100"
              />
            </span>
            <FlipText
              text={r.status}
              delay={i * 140 + 260}
              cellClassName={CELL}
              glyphClassName={r.tone}
              className="justify-self-end sm:justify-self-start"
            />
          </div>
        ))}
      </div>

    </Reveal>
  );
}
