"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Plus, Trash2 } from "lucide-react";

export type PaymentTerm = {
  due_date?: string | null;
  percent?: number | null;
  amount?: number | null;
};

const MAX_TERMS = 12;

type Line = { due_date: string; percent: string };

const inr = (n: number) =>
  n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Repeatable due-date / percentage editor backing the `payment_terms` JSONB.
 *
 * Kept as an array of strings internally rather than the serialised shape, so a
 * half-typed percentage doesn't reorder or drop rows underneath the user. It
 * serialises on every change, dropping incomplete lines and stamping each row
 * with the rupee amount its percentage works out to — the amount is stored
 * alongside so the schedule still reads correctly if the total is renegotiated
 * later. Same contract as TaxBreakupEditor, which this is modelled on.
 */
export default function PaymentTermsEditor({
  value, totalFare, onChange,
}: {
  value: PaymentTerm[] | null | undefined;
  /** Contract total, used to turn each percentage into an amount. */
  totalFare: number | null;
  onChange: (v: PaymentTerm[] | null) => void;
}) {
  const [lines, setLines] = useState<Line[]>(() =>
    (value ?? []).map((t) => ({
      due_date: t.due_date ?? "",
      percent: t.percent != null ? String(t.percent) : "",
    })),
  );

  useEffect(() => {
    const out: PaymentTerm[] = [];
    for (const l of lines) {
      const pct = parseFloat(l.percent);
      if (!l.due_date && !Number.isFinite(pct)) continue;
      out.push({
        due_date: l.due_date || null,
        percent: Number.isFinite(pct) ? pct : null,
        amount:
          Number.isFinite(pct) && totalFare != null
            ? Math.round(((totalFare * pct) / 100) * 100) / 100
            : null,
      });
    }
    onChange(out.length ? out : null);
    // onChange is recreated per render by the parent; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, totalFare]);

  const set = (i: number, patch: Partial<Line>) =>
    setLines((prev) => prev.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const totalPct = lines.reduce((sum, l) => {
    const n = parseFloat(l.percent);
    return Number.isFinite(n) ? sum + n : sum;
  }, 0);
  const offBy100 = lines.length > 0 && Math.abs(totalPct - 100) > 0.01;

  return (
    <div className="space-y-2">
      {lines.length > 0 && (
        <div className="flex items-center gap-2 px-1">
          <span className="w-40 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Due Date</span>
          <span className="w-24 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">%</span>
          <span className="flex-1 text-[10px] font-semibold text-gray-500 uppercase tracking-wide text-right">Amount</span>
          <span className="w-7" />
        </div>
      )}

      {lines.map((l, i) => {
        const pct = parseFloat(l.percent);
        const amount =
          Number.isFinite(pct) && totalFare != null ? (totalFare * pct) / 100 : null;
        return (
          <div key={i} className="flex items-center gap-2">
            <input
              type="date"
              value={l.due_date}
              onChange={(e) => set(i, { due_date: e.target.value })}
              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
              className="w-40 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <input
              type="number"
              step="0.01"
              value={l.percent}
              placeholder="25"
              onChange={(e) => set(i, { percent: e.target.value })}
              className="w-24 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <span className="flex-1 text-right text-[11px] tabular-nums text-gray-600">
              {amount != null ? inr(amount) : <span className="text-gray-300">—</span>}
            </span>
            <button
              type="button"
              onClick={() => setLines((prev) => prev.filter((_, j) => j !== i))}
              className="p-1.5 rounded-lg text-red-400 hover:bg-red-50 shrink-0"
              title="Remove payment term"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          disabled={lines.length >= MAX_TERMS}
          onClick={() => setLines((prev) => [...prev, { due_date: "", percent: "" }])}
          className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline disabled:text-gray-300 disabled:no-underline disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" /> Add payment term
        </button>
        {lines.length > 0 && (
          <span className="text-[11px] text-gray-500 tabular-nums">
            Total{" "}
            <span className={`font-semibold ${offBy100 ? "text-amber-700" : "text-gray-700"}`}>
              {totalPct.toLocaleString("en-IN", { maximumFractionDigits: 2 })}%
            </span>
            {totalFare != null && (
              <span className="text-gray-400"> · {inr((totalFare * totalPct) / 100)}</span>
            )}
          </span>
        )}
      </div>

      {offBy100 && (
        <div className="flex items-start gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
          <AlertCircle className="w-3 h-3 shrink-0 mt-px" />
          <span>
            The instalments add up to {totalPct.toLocaleString("en-IN", { maximumFractionDigits: 2 })}%, not 100% — saved as entered, but
            the schedule won&apos;t cover the contract total.
          </span>
        </div>
      )}

      {lines.length === 0 && (
        <p className="text-[11px] text-gray-400 italic py-1">
          No payment terms yet. Add one per instalment — a due date and the share of the total due by then.
        </p>
      )}

      {lines.length >= MAX_TERMS && (
        <p className="text-[10px] text-gray-400">A schedule cannot carry more than {MAX_TERMS} instalments.</p>
      )}
    </div>
  );
}
