"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plane, X } from "lucide-react";
import { inrCompact, rupees } from "@/lib/money";
import { INCENTIVE_COLORS, OTHER_COLOR, SOURCE_COLOR } from "@/lib/revenueCharts";
import { fetchAirlineDetail, type RevenueQuery } from "@/lib/revenueBoard";
import { SaleByMonthChart } from "./charts/ByMonthCharts";

/**
 * One carrier's whole picture, behind a row of the matrix.
 *
 * Its sale by statement type, its months, its incentive split, and — kept visually
 * apart and never added — the statements that RESTATE that business rather than adding
 * to it. A TGQ HMPR line is the same ticket as its BSP row; a Flown Report line is the
 * same booking as its LCC Detailed row. They are shown because "1,840 TGQ tickets" is
 * the context a sale figure is read against, and they are labelled under their own
 * measure so nobody mistakes one for revenue.
 */
export default function AirlineDrawer({
  airlineId,
  airlineName,
  query,
  onClose,
}: {
  airlineId: number;
  airlineName: string;
  query: RevenueQuery;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["revenue-airline", airlineId, query],
    queryFn: () => fetchAirlineDetail(airlineId, query),
  });
  const d = detail.data;
  const t = d?.totals;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/20" onClick={onClose} aria-hidden />
      <aside className="relative w-full max-w-2xl bg-gray-50 h-full overflow-y-auto shadow-xl">
        <header className="sticky top-0 bg-white border-b border-gray-200 px-5 py-4 flex items-start gap-3 z-10">
          <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Plane className="w-4 h-4 text-blue-600" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
              Total Revenue
            </p>
            <h2 className="text-base font-bold text-gray-900 truncate">
              {d?.airline ?? airlineName}
            </h2>
            {t && (
              <p className="text-xs text-gray-500 mt-0.5">
                {inrCompact(t.sale)} across {d!.by_source.length} statement type
                {d!.by_source.length === 1 ? "" : "s"}
                {t.incentive != null && ` · ${inrCompact(t.incentive)} earned`}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-700"
            aria-label="Close"
          >
            <X className="w-4 h-4" aria-hidden />
          </button>
        </header>

        <div className="p-5 space-y-4">
          {detail.isLoading && (
            <p className="text-xs text-gray-400 py-10 text-center">Loading…</p>
          )}

          {/* By statement type */}
          {!!d?.by_source.length && (
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">
                By statement type
              </h3>
              <ul className="space-y-2">
                {d.by_source.map((s) => (
                  <li key={s.source} className="flex items-center gap-2">
                    <span
                      className="w-2.5 h-2.5 rounded-sm shrink-0"
                      style={{ background: SOURCE_COLOR[s.source] }}
                      aria-hidden
                    />
                    <span className="text-xs text-gray-700 flex-1 min-w-0 truncate">
                      {s.label}
                    </span>
                    <span className="text-[11px] text-gray-400 tabular-nums shrink-0">
                      {s.rows.toLocaleString("en-IN")} lines
                    </span>
                    <span className="text-xs font-semibold text-gray-900 tabular-nums shrink-0 w-20 text-right">
                      {inrCompact(s.sale)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!!d?.by_month.length && <SaleByMonthChart data={d.by_month} />}

          {/* The incentive split — the question the board is asked most. */}
          {!!d?.by_incentive_type.length && (
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900">What it earned</h3>
              <p className="text-xs text-gray-500 mb-3">
                Per incentive type, over the lines a deal has been applied to.
              </p>
              <ul className="space-y-2">
                {d.by_incentive_type.map((i, idx) => (
                  <li key={i.incentive_type} className="flex items-center gap-2">
                    <span
                      className="w-2.5 h-2.5 rounded-sm shrink-0"
                      style={{
                        background: INCENTIVE_COLORS[idx] ?? OTHER_COLOR,
                      }}
                      aria-hidden
                    />
                    <span className="text-xs text-gray-700 flex-1 min-w-0 truncate">
                      {i.incentive_type}
                    </span>
                    <span className="text-[11px] text-gray-400 tabular-nums shrink-0">
                      {i.share_pct.toFixed(0)}%
                    </span>
                    <span className="text-xs font-semibold text-gray-900 tabular-nums shrink-0 w-20 text-right">
                      {rupees(i.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Linked statements. Visually separated and labelled, because the single
              easiest mistake a reader can make here is adding them to the sale above. */}
          {!!d?.linked.length && (
            <section className="rounded-xl bg-slate-50 ring-1 ring-slate-200 p-5">
              <h3 className="text-sm font-semibold text-slate-900">Linked statements</h3>
              <p className="text-xs text-slate-500 mb-3">
                The same business, recorded again — a TGQ ticket is its BSP row, a memo
                counts through the BSP row it was raised against, a flown line is its LCC
                booking. <strong>Not added to the sale above.</strong> Not date-filtered:
                these six types each keep their date in a different column.
              </p>
              <ul className="space-y-2">
                {d.linked.map((l) => (
                  <li key={l.source} className="flex items-center gap-2">
                    <span className="text-xs text-slate-700 flex-1 min-w-0 truncate">
                      {l.label}
                      {l.schema_unverified && (
                        <span
                          className="ml-1.5 inline-flex items-center align-middle"
                          title="This statement's layout was built without a real sample. Check the mapping before relying on the figure."
                        >
                          <AlertTriangle className="w-3 h-3 text-amber-500" aria-hidden />
                        </span>
                      )}
                    </span>
                    <span className="text-[11px] text-slate-400 tabular-nums shrink-0">
                      {l.rows.toLocaleString("en-IN")} · {l.measure_label}
                    </span>
                    <span className="text-xs font-semibold text-slate-800 tabular-nums shrink-0 w-20 text-right">
                      {inrCompact(l.measure)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {t && (t.unpriced_rows > 0 || t.not_counted_rows > 0) && (
            <p className="text-[11px] text-gray-400">
              {t.unpriced_rows > 0 &&
                `${t.unpriced_rows.toLocaleString("en-IN")} line(s) carry sale that no commission run has seen. `}
              {t.not_counted_rows > 0 &&
                `${t.not_counted_rows.toLocaleString("en-IN")} line(s) worth ${inrCompact(t.not_counted_sale)} are held out of the sale total — see the Not counted panel.`}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}
