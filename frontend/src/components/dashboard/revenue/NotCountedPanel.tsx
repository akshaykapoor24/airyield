"use client";

import { Panel } from "@/components/dashboard/ui/Board";
import { inrCompact } from "@/lib/money";
import { SOURCE_COLOR } from "@/lib/revenueCharts";
import { SOURCE_SHORT, type NotCountedPoint } from "@/lib/revenueBoard";

/**
 * Why the total is smaller than the sum of the statements.
 *
 * THIS PANEL IS THE POINT OF STORING A REASON RATHER THAN A BOOLEAN. A de-duplicated
 * figure invites exactly one question — "my BSP statement says 6.4 crore and this says
 * 6.1" — and a dashboard that cannot answer it gets stopped being trusted. Every line
 * held out of the sale total is here, with what it was worth and the rule that held it.
 *
 * The wording is the Report Download's own NET_* vocabulary, not a phrasing invented
 * for this screen, so the same row gives the same answer in the workbook.
 */
export default function NotCountedPanel({ rows }: { rows: NotCountedPoint[] }) {
  if (!rows.length) return null;

  const total = rows.reduce((a, r) => a + Math.abs(r.amount ?? 0), 0);

  return (
    <Panel
      title="Not counted as sale"
      subtitle={
        <>
          Loaded, visible and deliberately outside the total above — because the same
          business is already counted on another statement, or because the line was never
          a sale. This is the difference between your statements&rsquo; own totals and this
          board&rsquo;s.
        </>
      }
      actions={
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600 tabular-nums">
          {inrCompact(total)} · {rows.reduce((a, r) => a + r.rows, 0).toLocaleString("en-IN")} lines
        </span>
      }
    >
      <ul className="space-y-3">
        {rows.map((r) => (
          <li key={r.reason}>
            <div className="flex items-start gap-3">
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium text-gray-800">{r.reason}</span>
                <span className="mt-1 flex flex-wrap items-center gap-1.5">
                  {r.sources.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center gap-1 rounded-full bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-500 ring-1 ring-line"
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-sm"
                        style={{ background: SOURCE_COLOR[s] ?? "#94a3b8" }}
                        aria-hidden
                      />
                      {SOURCE_SHORT[s] ?? s}
                    </span>
                  ))}
                </span>
              </span>
              <span className="text-right shrink-0">
                <span className="block text-xs font-semibold text-gray-900 tabular-nums">
                  {inrCompact(r.amount)}
                </span>
                <span className="block text-[10px] text-gray-400 tabular-nums">
                  {r.rows.toLocaleString("en-IN")} {r.rows === 1 ? "line" : "lines"}
                </span>
              </span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-gray-100" aria-hidden>
              <div
                className="h-full rounded-full bg-slate-400"
                style={{ width: `${total ? (Math.abs(r.amount ?? 0) / total) * 100 : 0}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
