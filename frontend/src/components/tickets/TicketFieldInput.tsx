"use client";

import type { TicketField } from "@/lib/ticketFields";

/** One labelled input driven entirely by its catalog entry. */
export default function TicketFieldInput({
  field, value, onChange, invalid, required,
}: {
  field: TicketField;
  value: string | number | null | undefined;
  onChange: (raw: string) => void;
  invalid?: boolean;
  required?: boolean;
}) {
  const str = value === null || value === undefined ? "" : String(value);
  const base =
    "w-full border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 transition-colors";
  const cls = invalid
    ? `${base} border-red-300 bg-red-50 focus:ring-red-400`
    : `${base} border-gray-200 bg-white focus:ring-blue-400`;

  return (
    <div className="min-w-0">
      <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
        {field.label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>

      {field.type === "select" ? (
        <select value={str} onChange={(e) => onChange(e.target.value)} className={cls}>
          <option value="">— select —</option>
          {field.options?.map((o) => (
            <option key={o} value={o}>
              {o.charAt(0).toUpperCase() + o.slice(1)}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
          step={field.type === "number" ? "any" : undefined}
          value={str}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          onClick={
            field.type === "date"
              ? (e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }
              : undefined
          }
          className={cls}
        />
      )}

      {field.hint && (
        <p className="text-[10px] text-gray-400 mt-1 leading-snug">{field.hint}</p>
      )}
    </div>
  );
}
