"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

type Option<T extends string | number> = { value: T; label: string; sublabel?: string };

interface MultiSelectDropdownProps<T extends string | number> {
  options: Option<T>[];
  selected: T[];
  onChange: (values: T[]) => void;
  placeholder?: string;
  disabled?: boolean;
  /** Shown when the search filter matches nothing. */
  emptyText?: string;
  /** Hide the search box for short, fixed option lists. */
  searchable?: boolean;
}

export default function MultiSelectDropdown<T extends string | number>({
  options,
  selected,
  onChange,
  placeholder = "Select...",
  disabled = false,
  emptyText = "No results found",
  searchable = true,
}: MultiSelectDropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const toggle = (id: T) => {
    onChange(selected.includes(id) ? selected.filter((v) => v !== id) : [...selected, id]);
  };

  const remove = (id: T, e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(selected.filter((v) => v !== id));
  };

  const filtered = options.filter((o) => {
    const q = search.toLowerCase();
    return o.label.toLowerCase().includes(q) || (o.sublabel ?? "").toLowerCase().includes(q);
  });

  // Ordered by selection, not by the option list, so the value round-trips in
  // the order the user built it.
  const selectedOptions = selected
    .map((v) => options.find((o) => o.value === v))
    .filter((o): o is Option<T> => Boolean(o));

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => { if (!disabled) { setOpen((v) => !v); } }}
        className="w-full min-h-[38px] border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-left bg-white flex items-start gap-1.5 flex-wrap disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="flex-1 flex flex-wrap gap-1 min-w-0">
          {selectedOptions.length === 0 ? (
            <span className="text-gray-400 py-0.5">{placeholder}</span>
          ) : (
            selectedOptions.map((o) => (
              <span
                key={String(o.value)}
                className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 text-xs font-medium"
              >
                {o.label}
                <X
                  className="w-3 h-3 cursor-pointer hover:text-blue-900"
                  onClick={(e) => remove(o.value, e)}
                />
              </span>
            ))
          )}
        </span>
        <ChevronDown className={`w-4 h-4 text-gray-400 shrink-0 mt-0.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg">
          {searchable && (
            <div className="p-2 border-b border-gray-100">
              <input
                autoFocus
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search..."
                className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
          )}
          <ul className="max-h-52 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-sm text-gray-400">{emptyText}</li>
            ) : (
              filtered.map((o) => {
                const isSelected = selected.includes(o.value);
                return (
                  <li
                    key={String(o.value)}
                    onClick={() => toggle(o.value)}
                    className={`flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 ${isSelected ? "bg-blue-50/50" : ""}`}
                  >
                    <input
                      type="checkbox"
                      readOnly
                      checked={isSelected}
                      className="accent-blue-600 shrink-0"
                    />
                    <span className="flex flex-col min-w-0">
                      <span className="font-medium text-gray-800 truncate">{o.label}</span>
                      {o.sublabel && <span className="text-xs text-gray-400 truncate">{o.sublabel}</span>}
                    </span>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
