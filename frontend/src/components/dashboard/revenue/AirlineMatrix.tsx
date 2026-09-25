"use client";

import { ArrowRight, Info } from "lucide-react";
import { dashIfZero, inrCompact } from "@/lib/money";
import { SOURCE_COLOR } from "@/lib/revenueCharts";
import { Panel, TD, TH } from "@/components/dashboard/ui/Board";
import {
  SALE_SOURCES, SOURCE_SHORT, type AirlineRevenuePoint,
} from "@/lib/revenueBoard";

const HEAD = TH;
const CELL = TD;

/**
 * Every airline, every statement type, one row each.
 *
 * THE POINT OF THE WHOLE BOARD. Air India's BSP settlement, its NDC export and its
 * consolidator business are three uploads under three tabs; this is the one place they
 * sit on one line and add up. A column per type, the total at the end, and the row
 * opens into that carrier's month-by-month detail and its incentive split.
 *
 * ALSO THE TABLE VIEW the palette's contrast warning obligates. Three of the six hues
 * are below 3:1 on white, so every figure the charts encode in colour is also written
 * out here in ink. Do not remove it and keep the donuts.
 *
 * Grouped on `airline_id`, never on the name — BSP's carrier name is free text, and
 * grouping on it splits one airline across several rows. A row with no id is the
 * unattributed bucket, which is deliberately NOT where Third Party API lands: an
 * aggregator's hotel line has no carrier by nature, which is a different sentence from
 * a carrier that could not be resolved.
 */
export default function AirlineMatrix({
  rows,
  onOpen,
  loading,
}: {
  rows: AirlineRevenuePoint[];
  onOpen: (row: AirlineRevenuePoint) => void;
  loading?: boolean;
}) {
  // Only the columns this filter actually has business in — a table of six columns
  // where four are empty dashes reads as missing data rather than as nothing loaded.
  const cols = SALE_SOURCES.filter((s) => rows.some((r) => r.by_source[s]));

  return (
    <Panel
      flush
      loading={loading}
      title="Every airline, every statement type"
      subtitle="One carrier per row, whatever it was sold through. Click a row for its months and its incentive split."
      actions={
        rows.length ? (
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-medium text-gray-600">
            {rows.length} airline{rows.length === 1 ? "" : "s"}
          </span>
        ) : null
      }
    >
      <div className="max-h-[560px] overflow-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className={`${HEAD} text-left left-0 z-[2]`}>
                Airline
              </th>
              {cols.map((s) => (
                <th key={s} className={`${HEAD} text-right`}>
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="w-2 h-2 rounded-sm"
                      style={{ background: SOURCE_COLOR[s] }}
                      aria-hidden
                    />
                    {SOURCE_SHORT[s]}
                  </span>
                </th>
              ))}
              <th className={`${HEAD} text-right`}>Sale</th>
              <th className={`${HEAD} text-right`}>Earned</th>
              <th className={`${HEAD} text-right`}>PLB</th>
              <th className={HEAD} aria-label="Open" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((r) => (
              <tr
                key={String(r.airline_id ?? "none")}
                className="group hover:bg-brand-50/60 cursor-pointer"
                onClick={() => onOpen(r)}
              >
                <td className={`${CELL} sticky left-0 bg-white group-hover:bg-brand-50/60 font-medium text-gray-900`}>
                  {r.airline}
                  {r.airline_id === null && (
                    <span
                      className="ml-1.5 inline-flex items-center"
                      title="These lines carry no carrier the master could resolve. Their sale counts; it is simply not attributed."
                    >
                      <Info className="w-3 h-3 text-amber-500" aria-hidden />
                    </span>
                  )}
                </td>
                {cols.map((s) => (
                  <td key={s} className={`${CELL} text-right text-gray-700`}>
                    {dashIfZero(r.by_source[s], inrCompact)}
                  </td>
                ))}
                <td className={`${CELL} text-right font-semibold text-gray-900`}>
                  <span className="inline-flex items-center justify-end gap-2">
                    <span className="hidden sm:block h-1.5 w-14 overflow-hidden rounded-full bg-gray-100" aria-hidden>
                      <span
                        className="block h-full rounded-full bg-brand-600"
                        style={{ width: `${Math.min(100, Math.max(2, r.share_pct))}%` }}
                      />
                    </span>
                    {inrCompact(r.sale)}
                  </span>
                </td>
                <td className={`${CELL} text-right text-gray-700`}>
                  {r.incentive == null ? "—" : inrCompact(r.incentive)}
                </td>
                <td className={`${CELL} text-right text-gray-700`}>
                  {dashIfZero(r.by_incentive_type?.PLB, inrCompact)}
                </td>
                <td className={CELL}>
                  <ArrowRight
                    className="w-3.5 h-3.5 text-gray-300 group-hover:text-brand-600"
                    aria-hidden
                  />
                </td>
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr>
                <td colSpan={cols.length + 5} className="px-5 py-10 text-center text-xs text-gray-400">
                  No carrier-attributed sale in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
