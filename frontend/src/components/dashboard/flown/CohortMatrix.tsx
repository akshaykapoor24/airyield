"use client";

import { CalendarX2 } from "lucide-react";
import { EmptyState, TH } from "@/components/dashboard/ui/Board";
import { HEAT_RAMP } from "@/lib/accrual";
import { dashIfZero, inr, inrCompact, monthLabel, pct, rupees } from "@/lib/money";
import type { CohortRow } from "@/lib/salesFlown";

export type CohortMode = "pct" | "amount";

/**
 * Sale month down the side, flown month across the top — the finance sheet's grid.
 *
 * A cell is how much of THAT sale month's sale flew in THAT travel month, as a share of
 * the month's sale (or as the amount). Shading is a sequential ramp on the share, so the
 * diagonal "most of it flies within three months" pattern reads at a glance; every cell
 * also prints its value, so the table is its own accessible view.
 *
 * Travel months after "as of" are BOOKED, not flown. Their header says so and their
 * cells are set in italic without fill, because shading them like flown months would
 * make a forward booking look earned.
 *
 * The right-hand block is the sheet's last four columns — flown %, exclusion, payout
 * flown % and eligible — computed properly: eligible is flown × (1 − exclusion), never
 * "flown % − exclusion %", which goes negative for any month that has not flown yet.
 */
export default function CohortMatrix({
  rows,
  months,
  asOfYm,
  exclusionPct,
  mode,
}: {
  rows: CohortRow[];
  months: string[];
  asOfYm: string;
  exclusionPct: number | null;
  mode: CohortMode;
}) {
  if (!rows.length) {
    return (
      <EmptyState icon={CalendarX2}>No sale in this window.</EmptyState>
    );
  }
  const anyUndated = rows.some((r) => Math.abs(r.no_travel_date) >= 0.5);
  const cols: (string | null)[] = [...months, ...(anyUndated ? [null] : [])];
  const keep = exclusionPct == null ? null : 1 - exclusionPct / 100;

  const cellOf = (r: CohortRow, ym: string | null) =>
    r.cells.find((c) => c.flown_ym === ym)?.amount ?? 0;

  const shade = (share: number) => {
    if (share < 1) return undefined;
    return HEAT_RAMP[Math.min(HEAT_RAMP.length - 1, Math.floor(share / 20))];
  };

  const render = (amount: number, base: number) => {
    if (Math.abs(amount) < 0.5) return "—";
    if (mode === "amount" || !base) return inr(amount);
    return pct((amount / base) * 100, 0);
  };

  const colTotal = (ym: string | null) => rows.reduce((a, r) => a + cellOf(r, ym), 0);
  const sold = rows.reduce((a, r) => a + r.sold, 0);
  const flown = rows.reduce((a, r) => a + r.flown, 0);

  return (
    <div className="max-h-[620px] overflow-auto">
      <table className="w-full min-w-max text-xs tabular-nums">
        <thead>
          <tr>
            <th className={`${TH} left-0 z-[2] text-left`}>Sold in</th>
            <th className={`${TH} text-right`}>Sold</th>
            {cols.map((ym) => {
              const future = ym != null && ym > asOfYm;
              return (
                <th key={ym ?? "none"} className={`${TH} text-right`}>
                  {ym ? monthLabel(ym) : "No date"}
                  {future && (
                    <span className="block normal-case tracking-normal font-normal text-gray-400">
                      booked
                    </span>
                  )}
                </th>
              );
            })}
            <th className={`${TH} text-right border-l`}>Flown</th>
            <th className={`${TH} text-right`}>Exclusion</th>
            <th className={`${TH} text-right`}>Payout flown</th>
            <th className={`${TH} text-right`}>Eligible</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const flownShare = r.sold ? (r.flown / r.sold) * 100 : 0;
            return (
              <tr key={r.sale_ym} className="border-t border-gray-100 hover:bg-gray-50/60">
                <td className="sticky left-0 z-[1] bg-white px-3 py-2 font-medium text-gray-900 whitespace-nowrap">
                  {r.label}
                </td>
                <td className="text-right px-3 text-gray-900" title={rupees(r.sold)}>
                  {inrCompact(r.sold)}
                </td>
                {cols.map((ym) => {
                  const amt = cellOf(r, ym);
                  const future = ym != null && ym > asOfYm;
                  const share = r.sold ? (amt / r.sold) * 100 : 0;
                  return (
                    <td
                      key={ym ?? "none"}
                      className={`text-right px-3 py-2 ${
                        future || ym == null ? "italic text-gray-500" : "text-gray-900"
                      }`}
                      style={{
                        background: future || ym == null ? undefined : shade(share),
                      }}
                      title={`${rupees(amt)} · ${pct(share, 1)} of ${r.label} sale`}
                    >
                      {render(amt, r.sold)}
                    </td>
                  );
                })}
                <td className="text-right px-3 font-semibold text-gray-900 border-l border-line bg-paper/60">
                  {pct(flownShare, 0)}
                </td>
                <td className="text-right px-3 text-gray-600 bg-paper/60">{pct(exclusionPct, 0)}</td>
                <td className="text-right px-3 text-gray-600 bg-paper/60">
                  {keep == null ? "—" : pct(flownShare * keep, 0)}
                </td>
                <td className="text-right px-3 font-semibold text-emerald-700 bg-paper/60">
                  {keep == null ? "—" : dashIfZero(r.flown * keep)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-line bg-paper font-semibold text-gray-900">
            <td className="sticky left-0 z-[1] bg-paper px-3 py-2.5">Total</td>
            <td className="text-right px-3">{inrCompact(sold)}</td>
            {cols.map((ym) => (
              <td key={ym ?? "none"} className="text-right px-3">
                {render(colTotal(ym), sold)}
              </td>
            ))}
            <td className="text-right px-3 border-l border-line">
              {pct(sold ? (flown / sold) * 100 : 0, 0)}
            </td>
            <td className="text-right px-3">{pct(exclusionPct, 0)}</td>
            <td className="text-right px-3">
              {keep == null ? "—" : pct(sold ? (flown / sold) * 100 * keep : 0, 0)}
            </td>
            <td className="text-right px-3 text-emerald-700">{keep == null ? "—" : inr(flown * keep)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
