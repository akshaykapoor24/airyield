"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import api from "@/lib/api";

export type Airline = { id: number; name: string; iata_code: string; icao_code: string | null };

/**
 * Airline code + name as one control, backed by the airline master.
 *
 * Code and name are one decision, so they share one widget: picking from the
 * dropdown fills both. Shared by the Create Ticket form and the Series/SIT/MICE
 * contract form — an airline resolvable in the master is what lets a ticket
 * match a deal, so the "not in the master" warning belongs everywhere it is used.
 */
export default function AirlinePicker({
  code, name, onPick, onCodeChange, invalid, required,
}: {
  code: string;
  name: string;
  onPick: (a: Airline) => void;
  onCodeChange: (v: string) => void;
  invalid?: boolean;
  /** A ticket cannot match a deal without an airline; a contract can still be filed. */
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Airline[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<Airline[]>("/airlines/", { params: { limit: 5000 } })
      .then((r) => setOptions(r.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? options.filter((a) =>
        a.name.toLowerCase().includes(q) ||
        a.iata_code?.toLowerCase().includes(q) ||
        a.icao_code?.toLowerCase().includes(q))
    : options;

  // Mirrors the resolution the server does: IATA or ICAO, case-insensitive, plus
  // zero-padding for numeric accounting codes.
  const trimmed = code.trim();
  const variants = new Set([trimmed.toUpperCase()]);
  if (/^\d+$/.test(trimmed)) variants.add(trimmed.padStart(3, "0"));
  const known = !trimmed || options.length === 0 || options.some((a) =>
    variants.has((a.iata_code ?? "").toUpperCase()) ||
    variants.has((a.icao_code ?? "").toUpperCase()));

  return (
    <div className="min-w-0" ref={ref}>
      <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
        Airline{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <div className="relative">
        <div className="flex gap-1.5">
          <input
            value={code}
            placeholder="AI"
            onChange={(e) => onCodeChange(e.target.value.toUpperCase())}
            className={`w-16 shrink-0 border rounded-lg px-2 py-1.5 text-xs font-mono uppercase focus:outline-none focus:ring-1 ${
              invalid ? "border-red-300 bg-red-50 focus:ring-red-400" : "border-gray-200 focus:ring-blue-400"
            }`}
          />
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex-1 min-w-0 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-left flex items-center justify-between gap-1 hover:bg-gray-50"
          >
            <span className={`truncate ${name ? "text-gray-800" : "text-gray-400"}`}>
              {name || "search…"}
            </span>
            <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          </button>
        </div>

        {open && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 min-w-[260px] bg-white border border-gray-200 rounded-lg shadow-lg">
            <div className="p-2 border-b border-gray-100">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by name or code…"
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
                />
              </div>
            </div>
            <ul className="max-h-56 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-2 text-xs text-gray-400 italic">No airlines found</li>
              ) : filtered.slice(0, 200).map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => { onPick(a); setOpen(false); setQuery(""); }}
                    className="w-full text-left px-3 py-2 text-xs hover:bg-blue-50 flex items-center gap-2"
                  >
                    <span className="font-mono text-[10px] text-gray-500 w-8 shrink-0">{a.iata_code}</span>
                    <span className="truncate text-gray-700">{a.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {!known && (
        <p className="text-[10px] text-amber-600 mt-1 leading-snug">
          Not in the airline master — this ticket will save but can never match a deal.
        </p>
      )}
    </div>
  );
}
