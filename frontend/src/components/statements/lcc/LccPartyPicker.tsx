"use client";

// Pick ONE customer or corporate, by id.
//
// Neither existing control fits. `ui/SearchSelect.tsx` stores a STRING, and its own
// comment warns that two master rows sharing a name become indistinguishable once
// picked — which is exactly the case here (a real tenant has three customers all
// called "ZZ Disc Test"); it also caps the list at 300. `ui/MultiSelectDropdown.tsx`
// is id-keyed but multi-select, with checkboxes and chips. This is the single-select
// twin: its `Option` shape and its label+sublabel filter, rendering one value.
//
// `sublabel` carries the corporate a customer belongs to, so two people with the same
// name are still distinguishable in the list.

import { useEffect, useMemo, useRef, useState } from "react";
import { Building, ChevronDown, Search, User } from "lucide-react";

export type PartyOption = {
  value: number;
  label: string;
  sublabel?: string;
  kind: "customer" | "corporate";
};

export default function LccPartyPicker({
  options, value, onChange, placeholder = "Select a customer or corporate…",
  disabled, allowClear = true, size = "md",
}: {
  options: PartyOption[];
  value: number | null;
  onChange: (opt: PartyOption | null) => void;
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  /** "sm" for the per-row control inside the worklist table. */
  size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setQuery(""); }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const selected = useMemo(() => options.find((o) => o.value === value) ?? null, [options, value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      o.label.toLowerCase().includes(q) || (o.sublabel ?? "").toLowerCase().includes(q));
  }, [options, query]);

  const pad = size === "sm" ? "px-2 py-1 text-[11px]" : "px-3 py-2 text-sm";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={`w-full border rounded-lg ${pad} text-left flex items-center justify-between gap-1 bg-white disabled:opacity-50 ${
          selected ? "border-slate-200" : "border-slate-200 hover:bg-slate-50"
        }`}
      >
        <span className={`truncate flex items-center gap-1.5 ${selected ? "text-slate-800" : "text-slate-400"}`}>
          {selected?.kind === "corporate" && <Building className="w-3 h-3 shrink-0 text-slate-400" />}
          {selected?.kind === "customer" && <User className="w-3 h-3 shrink-0 text-slate-400" />}
          {selected ? selected.label : placeholder}
          {selected?.sublabel && <span className="text-slate-400">· {selected.sublabel}</span>}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
      </button>

      {open && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 min-w-[260px] bg-white border border-slate-200 rounded-lg shadow-lg">
          <div className="p-2 border-b border-slate-100">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search customers and corporates…"
                className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
          </div>
          <ul className="max-h-56 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-xs text-slate-400 italic">
                {options.length === 0
                  ? "No customers or corporates yet — add them under User master."
                  : "No matches"}
              </li>
            ) : filtered.map((o) => (
              <li key={`${o.kind}-${o.value}`}>
                <button
                  type="button"
                  onClick={() => { onChange(o); setOpen(false); setQuery(""); }}
                  className={`w-full text-left px-3 py-2 text-xs hover:bg-blue-50 flex items-center gap-2 ${
                    o.value === value && o.kind === selected?.kind ? "text-blue-700 font-semibold" : "text-slate-700"
                  }`}
                >
                  {o.kind === "corporate"
                    ? <Building className="w-3 h-3 shrink-0 text-slate-400" />
                    : <User className="w-3 h-3 shrink-0 text-slate-400" />}
                  <span className="truncate">{o.label}</span>
                  {o.sublabel && <span className="text-slate-400 truncate">· {o.sublabel}</span>}
                </button>
              </li>
            ))}
          </ul>
          {allowClear && selected && (
            <div className="border-t border-slate-100 p-1">
              <button
                type="button"
                onClick={() => { onChange(null); setOpen(false); setQuery(""); }}
                className="w-full text-left px-2 py-1.5 text-[11px] text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded"
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
