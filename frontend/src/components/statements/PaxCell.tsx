"use client";

/**
 * The Pax cell of a billing worklist — shared by LCC Detailed and Third Party API.
 *
 * A party's FIXED markup is charged per passenger (backend services/party_markup.line_markup),
 * so this is a price input, not a label, and it follows the party picker's rules on both
 * screens: editable until the row is in billing, then locked. Saved on blur or Enter; Escape
 * abandons the edit.
 *
 * The caller keys it on the value (e.g. `${row.id}-${pax}-${source}`), so a reload with a
 * new figure — a save, a reset, a re-match — remounts it with a fresh draft instead of
 * syncing state inside an effect.
 */

import { useState } from "react";
import { X } from "lucide-react";

export default function PaxCell({
  pax, source, inFile, label, editable, onSave,
}: {
  pax: number;
  /** "file" (read off the statement), "default" (nothing usable there → 1), "user" (edited). */
  source: string;
  /** What the statement itself says, so an edited figure can show what it replaced. */
  inFile: number;
  /** Who the row is for, for the input's accessible name. */
  label: string;
  editable: boolean;
  /** A number corrects the pax; null puts it back on the statement's own figure. */
  onSave: (pax: number | null) => Promise<void>;
}) {
  const [draft, setDraft] = useState(String(pax));
  const [saving, setSaving] = useState(false);

  const edited = source === "user";
  const hint = (edited
    ? `Edited — the statement says ${inFile}.`
    : source === "default"
      ? "The statement gives no usable pax count, so this bills as 1 passenger."
      : "From the statement.")
    + " A fixed markup is charged per passenger.";

  if (!editable) {
    return (
      <span className={`tabular-nums ${edited ? "text-violet-700 font-semibold" : "text-slate-600"}`} title={hint}>
        {pax}
      </span>
    );
  }

  const commit = async () => {
    const n = Number(draft);
    if (!Number.isInteger(n) || n < 1 || n > 99) { setDraft(String(pax)); return; }
    if (n === pax) return;
    setSaving(true);
    try { await onSave(n); } finally { setSaving(false); }
  };

  return (
    <div className="flex items-center gap-1">
      <input
        type="number" min={1} max={99} step={1} value={draft} disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setDraft(String(pax));
        }}
        aria-label={`Pax for ${label}`}
        title={hint}
        className={`w-12 px-1.5 py-1 border rounded text-xs tabular-nums text-right bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:opacity-50 ${
          edited ? "border-violet-300 text-violet-700 font-semibold" : "border-slate-200 text-slate-700"}`}
      />
      {edited && (
        <button type="button" onClick={() => onSave(null)} disabled={saving}
          title={`Reset to the statement's ${inFile}`}
          className="text-slate-400 hover:text-slate-700 disabled:opacity-50">
          <X className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}
