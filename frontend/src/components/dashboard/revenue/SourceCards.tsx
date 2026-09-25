"use client";

import { AlertTriangle } from "lucide-react";
import { inrCompact } from "@/lib/money";
import { CATEGORY_ORDER, SOURCE_COLOR } from "@/lib/revenueCharts";
import { SOURCE_SHORT, type CategoryPoint, type SourcePoint } from "@/lib/revenueBoard";

/**
 * Sale by statement family — BSP, LCC, Third Party — with the types inside each.
 *
 * GROUPED THE WAY THE STATEMENTS HUB IS, because that is where these uploads came from
 * and a reader chasing a number will go looking for it there. BSP holds the BSP
 * settlement and NDC; Third Party holds GDS, LCC and API.
 *
 * The colour swatch beside each type is the one that type wears in every chart on the
 * page. It is also the relief the palette's contrast WARN obligates: three of the six
 * hues sit below 3:1 on white, so the figure is always written out rather than left to
 * the colour to carry.
 */
export default function SourceCards({
  categories,
  sources,
  loading,
}: {
  categories: CategoryPoint[];
  sources: SourcePoint[];
  loading?: boolean;
}) {
  const shown = CATEGORY_ORDER.filter((c) => categories.some((x) => x.category === c));

  return (
    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 transition-opacity ${loading ? "opacity-60" : ""}`}>
      {shown.map((cat) => {
        const c = categories.find((x) => x.category === cat)!;
        const members = sources.filter((s) => s.category === cat);
        const memberTotal = members.reduce((a, s) => a + Math.abs(s.sale ?? 0), 0);
        return (
          <section key={cat} className="rounded-2xl bg-white ring-1 ring-line shadow-sm p-5">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">{cat}</h2>
              <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 tabular-nums">
                {c.share_pct.toFixed(0)}% of sale
              </span>
            </div>
            <p className="font-display text-[28px] font-semibold leading-none tracking-tight text-gray-900 mt-3">
              {inrCompact(c.sale)}
            </p>
            <p className="text-[11px] text-gray-500 mt-1.5">
              {c.rows.toLocaleString("en-IN")} lines
              {c.incentive != null && ` · ${inrCompact(c.incentive)} earned`}
            </p>

            {/* The family's make-up in one bar — each type in the colour it wears in
                every chart on the page, with the figures written out below. */}
            {memberTotal > 0 && (
              <div className="mt-4 flex h-2 gap-0.5 overflow-hidden rounded-full bg-gray-100" aria-hidden>
                {members.map((s) => (
                  <span
                    key={s.source}
                    className="h-full first:rounded-l-full last:rounded-r-full"
                    style={{
                      width: `${(Math.abs(s.sale ?? 0) / memberTotal) * 100}%`,
                      background: SOURCE_COLOR[s.source],
                    }}
                  />
                ))}
              </div>
            )}

            <ul className="mt-4 space-y-2.5">
              {members.map((s) => (
                <li key={s.source} className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-sm shrink-0"
                    style={{ background: SOURCE_COLOR[s.source] }}
                    aria-hidden
                  />
                  <span className="text-xs text-gray-700 flex-1 min-w-0 truncate">
                    {SOURCE_SHORT[s.source] ?? s.label}
                  </span>
                  <span className="text-right shrink-0">
                    <span className="block text-xs font-semibold text-gray-900 tabular-nums">
                      {inrCompact(s.sale)}
                    </span>
                    <span className="block text-[10px] text-gray-400 tabular-nums">
                      {s.unpriced_rows > 0 ? (
                        // Not an error, and not zero income. The statement is loaded and
                        // sold; nobody has run commission on it yet, and the remedy is a
                        // button rather than a missing column.
                        <span className="text-amber-600">
                          {s.unpriced_rows.toLocaleString("en-IN")} not priced
                        </span>
                      ) : s.incentive != null ? (
                        `${inrCompact(s.incentive)} earned`
                      ) : (
                        `${s.rows.toLocaleString("en-IN")} lines`
                      )}
                    </span>
                  </span>
                  {s.not_counted_rows > 0 && (
                    <AlertTriangle
                      className="w-3 h-3 text-gray-300 shrink-0"
                      aria-hidden
                      // Hovering explains the gap between this figure and the
                      // statement's own total, which is the first thing anyone asks.
                      // See the "Not counted" panel for the full reason breakdown.
                    />
                  )}
                </li>
              ))}
              {!members.length && (
                <li className="text-[11px] text-gray-400">Nothing loaded.</li>
              )}
            </ul>
          </section>
        );
      })}
      {!shown.length && !loading && (
        <p className="text-xs text-gray-400 py-10 text-center col-span-full">
          No statements in this period. Upload one under Vendors data → Statements.
        </p>
      )}
    </div>
  );
}
