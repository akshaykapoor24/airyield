"use client";

import { ArrowRight, Info } from "lucide-react";
import { dashIfZero, inrCompact } from "@/lib/money";
import { CARD_NOTE, CARD_TITLE, SOURCE_COLOR } from "@/lib/revenueCharts";
import {
  SALE_SOURCES, SOURCE_SHORT, type AirlineRevenuePoint,
} from "@/lib/revenueBoard";

const HEAD =
  "px-2.5 py-2 text-[10px] font-semibold uppercase tracking-wide text-white/80 whitespace-nowrap";
const CELL = "px-2.5 py-1.5 whitespace-nowrap tabular-nums";

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
    <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="p-5 pb-3">
        <h2 className={CARD_TITLE}>Every airline, every statement type</h2>
        <p className={CARD_NOTE}>
          One carrier per row, whatever it was sold through. Click a row for its months
          and its incentive split.
        </p>
      </div>

      <div className={`overflow-x-auto ${loading ? "opacity-60" : ""}`}>
        <table className="w-full text-xs">
          <thead style={{ background: "#1e3a5f" }}>
            <tr>
              <th className={`${HEAD} text-left sticky left-0`} style={{ background: "#1e3a5f" }}>
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
                className="group hover:bg-blue-50/40 cursor-pointer"
                onClick={() => onOpen(r)}
              >
                <td className={`${CELL} sticky left-0 bg-white group-hover:bg-blue-50/40 font-medium text-gray-900`}>
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
                  {inrCompact(r.sale)}
                </td>
                <td className={`${CELL} text-right text-gray-700`}>
                  {r.incentive == null ? "—" : inrCompact(r.incentive)}
                </td>
                <td className={`${CELL} text-right text-gray-700`}>
                  {dashIfZero(r.by_incentive_type?.PLB, inrCompact)}
                </td>
                <td className={CELL}>
                  <ArrowRight
                    className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500"
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
    </section>
  );
}
