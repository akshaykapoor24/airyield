"use client";

import { Plus, Trash2 } from "lucide-react";
import type { TicketSegment } from "@/lib/ticketFields";

export type Segment = TicketSegment;

const COLUMNS: { key: keyof Segment; label: string; width: string; placeholder: string }[] = [
  { key: "origin",      label: "Origin",      width: "w-20",  placeholder: "DEL" },
  { key: "destination", label: "Dest",        width: "w-20",  placeholder: "BOM" },
  { key: "flight_no",   label: "Flight No",   width: "w-24",  placeholder: "AI101" },
  { key: "class",       label: "Class",       width: "w-16",  placeholder: "Y" },
  { key: "travel_date", label: "Travel Date", width: "w-24",  placeholder: "16MAY" },
];

/**
 * Editor for the `segments` JSONB.
 *
 * Auto mode is the default and the one to prefer: the server builds segments
 * from sector + flight number + travel date + class, and this just displays what
 * came back. The manual override exists for itineraries the parser can't express,
 * and the page re-applies it over the preview response — see `override` handling
 * in the create page, since the server would otherwise rebuild and win.
 */
export default function SegmentsEditor({
  derived, override, segments, onToggleOverride, onChange,
}: {
  /** Segments the server derived for the current draft. */
  derived: Segment[];
  override: boolean;
  segments: Segment[];
  onToggleOverride: (on: boolean) => void;
  onChange: (v: Segment[]) => void;
}) {
  const rows = override ? segments : derived;

  const set = (i: number, key: keyof Segment, val: string) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, [key]: val || null } : r)));

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
        <input
          type="checkbox"
          checked={override}
          onChange={(e) => {
            // Seed the manual list from whatever the server derived, so turning
            // the toggle on never wipes what the user is looking at.
            if (e.target.checked) onChange(derived.length ? derived : [{}]);
            onToggleOverride(e.target.checked);
          }}
          className="accent-blue-600 cursor-pointer"
        />
        Edit segments manually
      </label>

      {!override && derived.length === 0 && (
        <p className="text-[11px] text-gray-400 leading-relaxed">
          No segments yet. Fill in Sector, Flight No, Travel Dt and Class in the Itinerary
          group and they will be built automatically.
        </p>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-max border-collapse">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="px-2 py-1.5 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide">#</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
                    {c.label}
                  </th>
                ))}
                {override && <th className="px-2 py-1.5" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((seg, i) => (
                <tr key={i} className="border-b border-gray-100">
                  <td className="px-2 py-1.5 text-[11px] text-gray-400">{i + 1}</td>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className="px-1 py-1">
                      {override ? (
                        <input
                          value={seg[c.key] ?? ""}
                          placeholder={c.placeholder}
                          onChange={(e) => set(i, c.key, e.target.value)}
                          className={`${c.width} border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-blue-400`}
                        />
                      ) : (
                        <span className={`${c.width} inline-block text-[11px] text-gray-700 px-2 py-1`}>
                          {seg[c.key] ?? <span className="text-gray-300">—</span>}
                        </span>
                      )}
                    </td>
                  ))}
                  {override && (
                    <td className="px-2 py-1">
                      <button
                        type="button"
                        onClick={() => onChange(rows.filter((_, j) => j !== i))}
                        className="p-1 rounded text-red-400 hover:bg-red-50"
                        title="Remove segment"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {override && (
        <button
          type="button"
          onClick={() => onChange([...rows, {}])}
          className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline"
        >
          <Plus className="w-3.5 h-3.5" /> Add segment
        </button>
      )}

      {!override && (
        <div className="text-[10px] text-gray-400 leading-relaxed space-y-0.5 border-t border-gray-100 pt-2">
          <p>Expected formats — <span className="font-mono text-gray-500">Sector</span> space-separated pairs (<span className="font-mono">DEL/BOM BOM/DEL</span>),{" "}
            <span className="font-mono text-gray-500">Flight No</span> space-separated (<span className="font-mono">AI-101 AI-102</span>, hyphens dropped),{" "}
            <span className="font-mono text-gray-500">Travel Dt</span> space-separated (<span className="font-mono">16MAY 24MAY</span>),{" "}
            <span className="font-mono text-gray-500">Class</span> slash-separated (<span className="font-mono">Y/Y</span>).</p>
        </div>
      )}
    </div>
  );
}
