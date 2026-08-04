"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Plus, Trash2 } from "lucide-react";

/** BSP statements carry Tax_Type1…Tax_Type20, so 20 is the real ceiling. */
const MAX_COMPONENTS = 20;
const COMMON_CODES = ["YQ", "YR", "K3", "IN", "WO", "OT", "XT"];

type Line = { code: string; amount: string };

/**
 * Repeatable tax-code / amount editor backing the `tax_breakup` JSONB.
 *
 * Kept as an array internally rather than a dict so a half-typed or duplicated
 * code doesn't collapse rows underneath the user. It serialises to a dict on
 * every change, dropping incomplete lines — matching _build_tax_breakup, which
 * also uppercases codes and lets a later duplicate win.
 */
export default function TaxBreakupEditor({
  value, onChange,
}: {
  value: Record<string, number> | null | undefined;
  onChange: (v: Record<string, number> | null) => void;
}) {
  const [lines, setLines] = useState<Line[]>(() =>
    Object.entries(value ?? {}).map(([code, amount]) => ({ code, amount: String(amount) })),
  );

  useEffect(() => {
    const dict: Record<string, number> = {};
    for (const l of lines) {
      const code = l.code.trim().toUpperCase();
      const n = parseFloat(l.amount);
      if (code && Number.isFinite(n)) dict[code] = n;
    }
    onChange(Object.keys(dict).length ? dict : null);
    // onChange is recreated per render by the parent; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines]);

  const set = (i: number, patch: Partial<Line>) =>
    setLines((prev) => prev.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const codes = lines.map((l) => l.code.trim().toUpperCase()).filter(Boolean);
  const dupes = [...new Set(codes.filter((c, i) => codes.indexOf(c) !== i))];
  const total = lines.reduce((sum, l) => {
    const n = parseFloat(l.amount);
    return Number.isFinite(n) ? sum + n : sum;
  }, 0);

  return (
    <div className="space-y-2">
      <datalist id="tax-code-options">
        {COMMON_CODES.map((c) => <option key={c} value={c} />)}
      </datalist>

      {lines.length > 0 && (
        <div className="flex items-center gap-2 px-1">
          <span className="w-28 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Tax Code</span>
          <span className="flex-1 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Amount</span>
          <span className="w-7" />
        </div>
      )}

      {lines.map((l, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            list="tax-code-options"
            value={l.code}
            maxLength={4}
            placeholder="YQ"
            onChange={(e) => set(i, { code: e.target.value.toUpperCase() })}
            className="w-28 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs font-mono uppercase focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <input
            type="number"
            step="0.01"
            value={l.amount}
            placeholder="0.00"
            onChange={(e) => set(i, { amount: e.target.value })}
            className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <button
            type="button"
            onClick={() => setLines((prev) => prev.filter((_, j) => j !== i))}
            className="p-1.5 rounded-lg text-red-400 hover:bg-red-50 shrink-0"
            title="Remove tax component"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          disabled={lines.length >= MAX_COMPONENTS}
          onClick={() => setLines((prev) => [...prev, { code: "", amount: "" }])}
          className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline disabled:text-gray-300 disabled:no-underline disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" /> Add tax component
        </button>
        {lines.length > 0 && (
          <span className="text-[11px] text-gray-500 tabular-nums">
            Total{" "}
            <span className="font-semibold text-gray-700">
              {total.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </span>
        )}
      </div>

      {dupes.length > 0 && (
        <div className="flex items-start gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
          <AlertCircle className="w-3 h-3 shrink-0 mt-px" />
          <span>Duplicate code{dupes.length > 1 ? "s" : ""} {dupes.join(", ")} — only the last amount for each is kept.</span>
        </div>
      )}

      {lines.length >= MAX_COMPONENTS && (
        <p className="text-[10px] text-gray-400">
          BSP statements carry at most 20 tax components (Tax_Type1…Tax_Type20).
        </p>
      )}

      <p className="text-[10px] text-gray-400 leading-snug">
        YR fills Sale YR, K3 fills K3 Tax and YQ fills YQ Tax automatically when those
        fields are left blank.
      </p>
    </div>
  );
}
