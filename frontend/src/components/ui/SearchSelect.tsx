"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";

/**
 * Single-select dropdown with a search box, over a plain list of strings.
 *
 * Exists because a native `<datalist>` renders as an unstyled browser popup that
 * ignores the app's design entirely, and a bare `<select>` over a few thousand
 * master records is unusable. Styled to match the AirlinePicker panel.
 */
export default function SearchSelect({
  value, options, onChange, placeholder, disabled, invalid, allowCustom,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  /** Keep what the user typed even when it matches nothing in the list. */
  allowCustom?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // A master can hold several rows sharing a name (the supplier master has one
  // row per branch). This control stores the string, so duplicates are
  // indistinguishable once picked — and a value-keyed list would collide.
  const unique = useMemo(() => [...new Set(options)], [options]);

  const q = query.trim().toLowerCase();
  const filtered = q ? unique.filter((o) => o.toLowerCase().includes(q)) : unique;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={`w-full border rounded-lg px-3 py-2 text-sm text-left flex items-center justify-between gap-1 bg-gray-50 disabled:opacity-50 ${
          invalid ? "border-red-300 bg-red-50" : "border-gray-200 hover:bg-gray-100"
        }`}
      >
        <span className={`truncate ${value ? "text-gray-800" : "text-gray-400"}`}>
          {value || placeholder || "Select…"}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
      </button>

      {open && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="p-2 border-b border-gray-100">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter" || !allowCustom || !query.trim()) return;
                  onChange(query.trim());
                  setOpen(false);
                  setQuery("");
                }}
                placeholder="Search…"
                className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
              />
            </div>
          </div>
          <ul className="max-h-56 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-xs text-gray-400 italic">
                {allowCustom && query.trim()
                  ? `Press Enter to use "${query.trim()}"`
                  : "No matches"}
              </li>
            ) : filtered.slice(0, 300).map((o) => (
              <li key={o}>
                <button
                  type="button"
                  onClick={() => { onChange(o); setOpen(false); setQuery(""); }}
                  className={`w-full text-left px-3 py-2 text-xs hover:bg-blue-50 truncate ${
                    o === value ? "text-blue-700 font-semibold" : "text-gray-700"
                  }`}
                >
                  {o}
                </button>
              </li>
            ))}
          </ul>
          {value && (
            <div className="border-t border-gray-100 p-1">
              <button
                type="button"
                onClick={() => { onChange(""); setOpen(false); setQuery(""); }}
                className="w-full text-left px-2 py-1.5 text-[11px] text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded"
              >
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
