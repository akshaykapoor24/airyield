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
    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 ${loading ? "opacity-60" : ""}`}>
      {shown.map((cat) => {
        const c = categories.find((x) => x.category === cat)!;
        const members = sources.filter((s) => s.category === cat);
        return (
          <section key={cat} className="rounded-xl bg-white border border-gray-200 p-5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-gray-900">{cat}</h2>
              <span className="text-[11px] text-gray-400 tabular-nums">
                {c.share_pct.toFixed(0)}% of sale
              </span>
            </div>
            <p className="text-2xl font-bold text-gray-900 mt-1">
              {inrCompact(c.sale)}
            </p>
            <p className="text-[11px] text-gray-500">
              {c.rows.toLocaleString("en-IN")} lines
              {c.incentive != null && ` · ${inrCompact(c.incentive)} earned`}
            </p>

            <ul className="mt-3 space-y-2 border-t border-gray-100 pt-3">
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
