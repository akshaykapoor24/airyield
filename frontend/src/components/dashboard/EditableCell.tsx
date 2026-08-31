"use client";

import { useEffect, useRef, useState } from "react";
import { Lock, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A grid cell that is normally DERIVED and can be LOCKED to a typed value.
 *
 * The badge is the point of the component: a reader must be able to tell at a
 * glance whether a number came out of the statements or out of somebody's
 * negotiation, because those two carry very different confidence. Locked cells
 * get a lock glyph and a heavier weight; derived cells stay quiet.
 *
 * Enter or blur commits, Escape reverts. Backspacing to empty clears the override
 * and hands the cell back to the derived value.
 */
export default function EditableCell({
  value,
  derived,
  locked,
  suffix = "",
  format,
  onCommit,
  disabled = false,
  align = "right",
  title,
}: {
  value: number;
  derived?: number | null;
  locked: boolean;
  suffix?: string;
  format: (v: number) => string;
  onCommit: (next: number | null) => void;
  disabled?: boolean;
  align?: "right" | "left";
  title?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) ref.current?.select();
  }, [editing]);

  const start = () => {
    if (disabled) return;
    setDraft(String(value ?? ""));
    setEditing(true);
  };

  const commit = () => {
    setEditing(false);
    const t = draft.trim();
    if (t === "") {
      if (locked) onCommit(null);   // cleared → back to derived
      return;
    }
    const n = Number(t);
    if (!Number.isNaN(n) && n !== value) onCommit(n);
  };

  if (editing) {
    return (
      <input
        ref={ref}
        className="w-full bg-white border border-blue-400 rounded px-1 py-0.5 text-xs text-right tabular-nums outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
      />
    );
  }

  const text = format(value);
  const hint =
    title ??
    (locked
      ? derived != null
        ? `Locked. Statements suggest ${format(derived)}${suffix}. Clear the cell to go back to it.`
        : "Locked to a typed value. Clear the cell to go back to the derived one."
      : "Derived from the uploaded statements. Click to lock a value.");

  return (
    <button
      type="button"
      onClick={start}
      title={hint}
      className={cn(
        "w-full inline-flex items-center gap-1 px-1 py-0.5 rounded text-xs tabular-nums",
        align === "right" ? "justify-end" : "justify-start",
        locked ? "font-semibold text-gray-900" : "text-gray-600",
        !disabled && "hover:bg-blue-50 hover:ring-1 hover:ring-blue-200 cursor-text",
        disabled && "cursor-default",
      )}
    >
      {locked ? (
        <Lock className="w-2.5 h-2.5 text-blue-500 shrink-0" aria-label="Locked value" />
      ) : (
        // The provenance glyph earns its place beside a number; beside an empty
        // cell it is just clutter across a whole column of them.
        text !== "—" && (
          <Wand2 className="w-2.5 h-2.5 text-gray-300 shrink-0" aria-label="Derived value" />
        )
      )}
      {text}{text === "—" ? "" : suffix}
    </button>
  );
}
