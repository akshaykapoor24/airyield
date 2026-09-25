"use client";

import { inrCompact, pct, rupees } from "@/lib/money";
import { CARD, CARD_NOTE, CARD_TITLE } from "@/lib/revenueCharts";
import { SERIES } from "@/lib/accrual";
import type { PlbDealLine } from "@/lib/salesFlown";

const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" }) : "open";

/**
 * Where the selected carrier's flown sits against its PLB slabs.
 *
 * The sheet's last block — slab thresholds, "% of slab achieved", rate and payout — read
 * off the approved deal rather than typed in. Achievement is flown inside the deal's own
 * PLB period (not the page's window) × the deal's commissionable share, and the band and
 * rate come from the same resolver the PLB Accrual board uses, so the two agree.
 */
export default function PlbSlabPanel({
  airline,
  lines,
  loading,
}: {
  airline: string | null;
  lines: PlbDealLine[];
  loading?: boolean;
}) {
  return (
    <section className={`${CARD} ${loading ? "opacity-60" : ""}`}>
      <h2 className={CARD_TITLE}>PLB slab progress{airline ? ` · ${airline}` : ""}</h2>
      <p className={`${CARD_NOTE} mb-4`}>
        Flown in the deal&apos;s PLB period × its commissionable share, against its slab
        bands. Same rate resolution as the PLB Accrual board.
      </p>

      {!airline ? (
        <p className="rounded-xl border border-dashed border-line py-10 px-6 text-sm text-gray-500 text-center">
          Pick exactly one airline in the filter row (or click one in the table below) to
          see its PLB slabs.
        </p>
      ) : !lines.length ? (
        <p className="rounded-xl border border-dashed border-amber-200 bg-amber-50/50 py-10 px-6 text-sm text-amber-800 text-center">
          No approved, active PLB deal on file for {airline}. Flown revenue on this carrier
          is earning no PLB.
        </p>
      ) : (
        <div className="space-y-4">
          {lines.map((l) => <DealLineCard key={`${l.deal_id}`} line={l} />)}
        </div>
      )}
    </section>
  );
}

function DealLineCard({ line: l }: { line: PlbDealLine }) {
  const achieved = l.achieved ?? 0;
  const top = l.bands.length ? l.bands[l.bands.length - 1].threshold : 0;
  const scale = Math.max(top * 1.1, achieved, 1);
  const pos = (v: number) => `${Math.min(100, Math.max(0, (v / scale) * 100))}%`;

  return (
    <div className="rounded-xl bg-paper ring-1 ring-line p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-sm font-semibold text-gray-900">{l.deal_no}</p>
        <p className="text-xs text-gray-500">
          {[l.entity, l.channel, l.segment, l.basis_label].filter(Boolean).join(" · ")}
        </p>
        <p className="text-xs text-gray-500 ml-auto">
          PLB period {fmtDate(l.period_start)} – {fmtDate(l.period_end)}
        </p>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-3 text-xs">
        <Stat label="Flown in period" value={inrCompact(l.flown)} />
        <Stat
          label="Commissionable"
          value={l.deflator_pct == null ? "—" : pct(l.deflator_pct, 1)}
          hint={l.deflator_pct == null ? "No fare breakdown on the flown lines" : `on ${l.basis_label}`}
        />
        <Stat label="Achieved" value={l.achieved == null ? "—" : inrCompact(l.achieved)} />
        <Stat label="Rate" value={pct(l.rate_pct, 2)} hint={l.target_based} />
        <Stat label="PLB payout" value={l.payout == null ? "—" : rupees(l.payout)} strong />
      </dl>

      {l.bands.length > 0 && (
        <div className="mt-5">
          <div className="relative h-2.5 rounded-full bg-gray-100">
            <div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ width: pos(achieved), background: SERIES.confirmed }}
            />
            {l.bands.map((b) => (
              <span
                key={b.threshold}
                className="absolute -top-1 h-4.5 w-0.5 bg-gray-500"
                style={{ left: pos(b.threshold) }}
                aria-hidden
              />
            ))}
          </div>
          <div className="relative h-8 mt-1 text-[10px] text-gray-500">
            {l.bands.map((b) => (
              <span
                key={b.threshold}
                className="absolute -translate-x-1/2 text-center whitespace-nowrap"
                style={{ left: pos(b.threshold) }}
              >
                {inrCompact(b.threshold)}
                <span className="block font-semibold text-gray-700">
                  {b.rate_pct == null ? "no rate" : pct(b.rate_pct, 2)}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-gray-500 mt-2">
        {l.rate_explain}
        {l.next_band && l.gap_to_next != null && (
          <>
            {" · "}
            <span className="font-semibold text-gray-800">{inrCompact(l.gap_to_next)}</span>{" "}
            more commissionable flown reaches the {inrCompact(l.next_band.threshold)} band
            {l.achieved_pct_of_next != null && ` (${pct(l.achieved_pct_of_next, 0)} of it achieved)`}.
          </>
        )}
      </p>
    </div>
  );
}

function Stat({
  label, value, hint, strong,
}: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-gray-500 font-semibold">{label}</dt>
      <dd className={`mt-0.5 ${strong ? "text-base font-bold" : "text-sm font-semibold"} text-gray-900`}>
        {value}
      </dd>
      {hint && <dd className="text-[10px] text-gray-400">{hint}</dd>}
    </div>
  );
}
