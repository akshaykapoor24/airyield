"use client";

import { ChevronRight } from "lucide-react";
import EditableCell from "@/components/dashboard/EditableCell";
import StatusBadge from "@/components/dashboard/StatusBadge";
import { STATUS, type AccrualBoard, type AccrualRow, type CellPatch } from "@/lib/accrual";
import { dashIfZero, inr, monthLabel } from "@/lib/money";
import { cn } from "@/lib/utils";

/**
 * The board, laid out in the same column order as the spreadsheet it replaces:
 * identity, PLB period, confirmation, base, deflator, rate, a column per month,
 * then the final figure.
 *
 * The red and amber that were applied by hand in Excel are now a computed status
 * on a left edge, paired with a labelled badge — the colour reinforces, it never
 * carries the message on its own.
 */

const HEAD =
  "px-2.5 py-2 text-[10px] font-semibold uppercase tracking-wide text-white/80 whitespace-nowrap";
const CELL = "px-2.5 py-1.5 whitespace-nowrap";
/** Left identity block stays put while the month columns scroll under it. */
const STICKY = "sticky bg-white group-hover:bg-blue-50/40";

export default function AccrualGrid({
  board,
  onPatch,
  onOpenRow,
  frozen,
  busy,
}: {
  board: AccrualBoard;
  onPatch: (patches: CellPatch[]) => void;
  onOpenRow: (row: AccrualRow) => void;
  frozen: boolean;
  busy?: boolean;
}) {
  const { rows, months, totals } = board;

  const patchFor = (r: AccrualRow, ym: string, part: Partial<CellPatch>): CellPatch => ({
    airline_name: r.airline_name,
    entity: r.entity,
    channel: r.channel,
    lob: r.lob,
    ym,
    ...part,
  });

  // A deflator or rate lock applies to the row, so it is written to every month in
  // the window — otherwise the effective figure would only shift for one month and
  // the displayed row value would disagree with the total it produced.
  //
  // Sent as ONE request. Looping onPatch per month would fire a round trip and a
  // cache invalidation each, so the grid would visibly recompute two or three
  // times for a single edit — and a failure halfway through would leave the row's
  // months disagreeing with each other.
  const patchAllMonths = (r: AccrualRow, part: Partial<CellPatch>) =>
    onPatch(months.map((ym) => patchFor(r, ym, part)));

  if (!rows.length) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
        <p className="text-sm text-gray-500">No deal lines match these filters.</p>
        <p className="text-xs text-gray-400 mt-1">
          The board is built from approved, active airline deals carrying a PLB incentive.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "bg-white rounded-xl border border-gray-200 overflow-hidden transition-opacity",
        busy && "opacity-60",
      )}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-xs">
          <thead style={{ background: "#1e3a5f" }}>
            <tr>
              <th className={cn(HEAD, STICKY, "left-0 text-left")} style={{ background: "#1e3a5f" }}>
                Airline
              </th>
              <th className={cn(HEAD, "text-left")}>GDS/LCC</th>
              <th className={cn(HEAD, "text-left")}>Entity</th>
              <th className={cn(HEAD, "text-left")}>LOB</th>
              <th className={cn(HEAD, "text-left")}>PLB Period</th>
              <th className={cn(HEAD, "text-left")}>Flown Confirmed</th>
              <th className={cn(HEAD, "text-left")}>Basic</th>
              <th className={cn(HEAD, "text-right")}>Deflator</th>
              <th className={cn(HEAD, "text-right")}>PLB rate</th>
              {months.map((ym) => (
                <th key={ym} className={cn(HEAD, "text-right")}>{monthLabel(ym)}</th>
              ))}
              <th className={cn(HEAD, "text-right")}>{board.period.label} Final PLB</th>
              <th className={cn(HEAD, "text-left")}>Status</th>
              <th className={cn(HEAD, "w-6")} aria-label="Open" />
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-100">
            {rows.map((r) => {
              const meta = STATUS[r.status];
              return (
                <tr
                  key={r.key}
                  className="group hover:bg-blue-50/40 cursor-pointer"
                  onClick={() => onOpenRow(r)}
                >
                  <td
                    className={cn(CELL, STICKY, "left-0 font-medium text-gray-900")}
                    style={{ boxShadow: `inset 3px 0 0 0 ${meta.bar}` }}
                  >
                    {r.airline_name}
                  </td>
                  <td className={cn(CELL, "text-gray-500")}>{r.channel}</td>
                  <td className={cn(CELL, "text-gray-700 font-medium")}>{r.entity || "—"}</td>
                  <td className={cn(CELL, "text-gray-500")}>{r.lob || "—"}</td>
                  <td className={cn(CELL, "text-gray-600")}>{r.plb_period_label}</td>
                  <td className={cn(CELL, "text-gray-500")}>
                    {r.flown_confirmed_through
                      ? monthLabel(r.flown_confirmed_through.slice(0, 7))
                      : "—"}
                  </td>
                  <td className={cn(CELL, "text-gray-600")}>{r.basis_label}</td>

                  <td className={cn(CELL, "text-right")} onClick={(e) => e.stopPropagation()}>
                    {/* A row with no flown revenue has no ratio to show. Printing
                        0.00% there would read as a negotiated zero rather than as
                        "nothing to derive it from" — the sheet leaves it blank. */}
                    <EditableCell
                      value={r.deflator_pct}
                      locked={r.deflator_source === "locked"}
                      suffix={r.flown_total === 0 ? "" : "%"}
                      format={(v) => (r.flown_total === 0 ? "—" : v.toFixed(2))}
                      disabled={frozen || r.deal_id == null}
                      onCommit={(v) => patchAllMonths(r, { deflator_pct: v })}
                    />
                  </td>
                  <td className={cn(CELL, "text-right")} onClick={(e) => e.stopPropagation()}>
                    <EditableCell
                      value={r.plb_rate_pct}
                      locked={r.plb_rate_source === "locked"}
                      suffix="%"
                      format={(v) => v.toFixed(2)}
                      disabled={frozen || r.deal_id == null}
                      onCommit={(v) => patchAllMonths(r, { plb_rate_pct: v })}
                      title={r.plb_rate_explain}
                    />
                  </td>

                  {months.map((ym) => {
                    const c = r.months[ym];
                    return (
                      <td
                        key={ym}
                        className={cn(
                          CELL, "text-right",
                          c && !c.in_period && "bg-gray-50/70",
                        )}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {c ? (
                          <EditableCell
                            value={c.flown}
                            locked={c.source === "manual"}
                            format={(v) => (Math.abs(v) < 0.5 ? "—" : inr(v))}
                            disabled={frozen || r.deal_id == null}
                            onCommit={(v) => onPatch([patchFor(r, ym, { manual_flown: v })])}
                            title={
                              c.source === "pooled"
                                ? `Not attributed to an entity. ${inr(c.pool)} is pooled across the entities holding a deal for this airline — type this entity's share.`
                                : c.source === "manual"
                                  ? "Typed in. Clear the cell to fall back to the statements."
                                  : !c.in_period
                                    ? "Outside the PLB period — counted, but at risk."
                                    : c.confirmed
                                      ? "From the statements, and the airline has confirmed this month."
                                      : "From the statements. The airline has not confirmed this month yet."
                            }
                          />
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                    );
                  })}

                  <td className={cn(CELL, "text-right font-semibold text-gray-900 tabular-nums")}>
                    {dashIfZero(r.accrual)}
                    {r.accrual_at_risk !== 0 && (
                      <span className="block text-[10px] font-normal text-red-600">
                        {inr(Math.abs(r.accrual_at_risk))} at risk
                      </span>
                    )}
                  </td>
                  <td className={CELL}>
                    <span className="flex flex-wrap gap-1">
                      {r.status_flags
                        .filter((f) => f !== "OK" || r.status_flags.length === 1)
                        .map((f) => <StatusBadge key={f} code={f} />)}
                    </span>
                  </td>
                  <td className={cn(CELL, "text-gray-300 group-hover:text-blue-500")}>
                    <ChevronRight className="w-3.5 h-3.5" aria-hidden />
                  </td>
                </tr>
              );
            })}
          </tbody>

          <tfoot className="bg-gray-50 border-t-2 border-gray-200">
            <tr className="font-semibold text-gray-900">
              <td className={cn(CELL, STICKY, "left-0 bg-gray-50")}>
                TOTAL · {totals.rows} {totals.rows === 1 ? "line" : "lines"}
              </td>
              <td className={CELL} colSpan={6} />
              <td className={cn(CELL, "text-right tabular-nums text-gray-500 font-normal")}>
                {totals.effective_deflator_pct.toFixed(2)}%
              </td>
              <td className={cn(CELL, "text-right tabular-nums text-gray-500 font-normal")}>
                {totals.effective_yield_pct.toFixed(2)}%
              </td>
              {months.map((ym) => (
                <td key={ym} className={cn(CELL, "text-right tabular-nums")}>
                  {dashIfZero(totals.by_month[ym])}
                </td>
              ))}
              <td className={cn(CELL, "text-right tabular-nums text-sm")}>
                {inr(totals.accrual)}
              </td>
              <td className={CELL} colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="px-4 py-2.5 border-t border-gray-100 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
        <span className="font-semibold text-gray-600">Legend</span>
        {(Object.keys(STATUS) as (keyof typeof STATUS)[])
          .filter((k) => k !== "OK")
          .map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: STATUS[k].bar }} aria-hidden />
              {STATUS[k].label}
            </span>
          ))}
        <span className="ml-auto">Shaded month = outside the PLB period.</span>
      </div>
    </div>
  );
}
