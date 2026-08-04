"use client";

import { useEffect, useRef, useState } from "react";
import { Building2, Calendar, CheckCircle, ChevronDown, FileText, Lock, Search, Tag } from "lucide-react";
import { AIRLINE_AGENCIES, type StatementType } from "@/lib/ticketFields";

export type { StatementType };
export { AIRLINE_AGENCIES };

/** Searchable single-select that always opens downward. */
export function AgencyDropdown({
  agency, setAgency, agencyOptions, touched, fieldCls, disabled,
}: {
  agency: string;
  setAgency: (v: string) => void;
  agencyOptions: string[];
  touched: boolean;
  fieldCls: (v: string) => string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = agencyOptions.filter((a) => a.toLowerCase().includes(query.toLowerCase()));
  const handleSelect = (a: string) => { setAgency(a); setOpen(false); setQuery(""); };

  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
        <Building2 className="w-3.5 h-3.5 inline mr-1" />
        Statement Agency <span className="text-red-500">*</span>
      </label>
      <div className="relative" ref={ref}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          className={`${fieldCls(agency)} w-full text-left flex items-center justify-between pr-8 disabled:opacity-60 disabled:cursor-not-allowed`}
        >
          <span className={agency ? "text-gray-800" : "text-gray-400"}>
            {agency || "— Select agency —"}
          </span>
          <ChevronDown className="w-4 h-4 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </button>

        {open && !disabled && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
            <div className="p-2 border-b border-gray-100">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search Agency..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
                />
              </div>
            </div>
            <ul className="max-h-48 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-2 text-xs text-gray-400 italic">No agencies found</li>
              ) : filtered.map((a) => (
                <li key={a}>
                  <button
                    type="button"
                    onClick={() => handleSelect(a)}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-blue-50 transition-colors ${
                      a === agency ? "bg-blue-50 text-blue-700 font-semibold" : "text-gray-700"
                    }`}
                  >
                    {a}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {touched && !agency && (
        <p className="text-[11px] text-red-500 mt-1">Agency is required</p>
      )}
    </div>
  );
}

/**
 * Statement metadata panel — statement type, agency and validity window.
 *
 * Shared by Upload Statement and Create Statement so the two flows can never
 * disagree about what a statement is. `lockedReason`, used only by Create
 * Statement, freezes the panel once tickets have been punched: statement type
 * selects the whole field set, so changing it mid-buffer would invalidate rows
 * already entered.
 */
export default function StatementFormPanel({
  statementType, setStatementType,
  agency, setAgency,
  agencyOptions,
  statementName, setStatementName,
  validFrom, setValidFrom,
  validTo, setValidTo,
  touched, isComplete,
  lockedReason,
}: {
  statementType: StatementType; setStatementType: (v: StatementType) => void;
  agency: string; setAgency: (v: string) => void;
  agencyOptions: string[];
  statementName: string; setStatementName: (v: string) => void;
  validFrom: string; setValidFrom: (v: string) => void;
  validTo: string; setValidTo: (v: string) => void;
  touched: boolean;
  isComplete: boolean;
  lockedReason?: string | null;
}) {
  const locked = !!lockedReason;
  // Mirrors the server's fallback so the placeholder shows the name that will
  // actually be saved when the field is left blank.
  const derivedName = agency && validFrom
    ? `${statementType} - ${agency} - ${validFrom}`
    : "";
  const fieldCls = (val: string) =>
    `w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
      touched && !val.trim()
        ? "border-red-300 bg-red-50"
        : "border-gray-200 bg-white"
    }`;
  const dateError = touched && validFrom && validTo && validTo < validFrom;

  return (
    // No overflow-hidden: AgencyDropdown opens as an absolute panel and would be
    // clipped by it. The header rounds its own top corners instead.
    <div className="bg-white border border-gray-200 rounded-xl h-fit sticky top-4">
      {/* panel header */}
      <div className="px-5 py-4 border-b border-gray-100 rounded-t-xl" style={{ background: "#1e3a5f" }}>
        <div className="flex items-center gap-2.5">
          <FileText className="w-4 h-4 text-white/80" />
          <h2 className="text-sm font-semibold text-white">Statement Details</h2>
        </div>
        <p className="text-xs text-white/60 mt-1">Fill in the statement information before saving</p>
      </div>

      <div className="px-5 py-5 space-y-4">
        {locked && (
          <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
            <Lock className="w-3.5 h-3.5 shrink-0 mt-px" />
            <span>{lockedReason}</span>
          </div>
        )}

        {/* Statement Type */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            Statement Type <span className="text-red-500">*</span>
          </label>
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm font-medium">
            {(["B2B", "AIRLINE"] as StatementType[]).map((t) => (
              <button
                key={t}
                type="button"
                disabled={locked}
                onClick={() => { setStatementType(t); setAgency(""); }}
                className={`flex-1 py-2 transition-colors disabled:cursor-not-allowed ${
                  statementType === t
                    ? "bg-[#1e3a5f] text-white"
                    : "bg-white text-gray-600 hover:bg-gray-50 disabled:hover:bg-white disabled:text-gray-400"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Statement Name — optional; blank falls back to the derived name */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Tag className="w-3.5 h-3.5 inline mr-1" />
            Statement Name
          </label>
          <input
            type="text"
            value={statementName}
            disabled={locked}
            maxLength={500}
            placeholder={derivedName || "e.g. Q1 BSP settlement"}
            onChange={(e) => setStatementName(e.target.value)}
            className="w-full border border-gray-200 bg-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-60 disabled:cursor-not-allowed"
          />
          <p className="text-[11px] text-gray-400 mt-1">
            {statementName.trim()
              ? "Used as the statement's name in the repository."
              : derivedName
                ? `Leave blank to name it “${derivedName}”.`
                : "Leave blank to name it from the type, agency and start date."}
          </p>
        </div>

        {/* Agency — conditional on statement type */}
        {statementType === "AIRLINE" ? (
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              <Building2 className="w-3.5 h-3.5 inline mr-1" />
              Statement Agency <span className="text-red-500">*</span>
            </label>
            <select
              value={agency}
              disabled={locked}
              onChange={(e) => setAgency(e.target.value)}
              className={`${fieldCls(agency)} disabled:opacity-60 disabled:cursor-not-allowed`}
            >
              <option value="">— Select agency —</option>
              {AIRLINE_AGENCIES.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
            {touched && !agency && (
              <p className="text-[11px] text-red-500 mt-1">Agency is required</p>
            )}
          </div>
        ) : (
          <AgencyDropdown
            agency={agency}
            setAgency={setAgency}
            agencyOptions={agencyOptions}
            touched={touched}
            fieldCls={fieldCls}
            disabled={locked}
          />
        )}

        {/* Valid From */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Calendar className="w-3.5 h-3.5 inline mr-1" />
            Statement Valid From <span className="text-red-500">*</span>
          </label>
          <input
            type="date"
            value={validFrom}
            disabled={locked}
            onChange={(e) => setValidFrom(e.target.value)}
            onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
            className={`${fieldCls(validFrom)} disabled:opacity-60 disabled:cursor-not-allowed`}
          />
          {touched && !validFrom && (
            <p className="text-[11px] text-red-500 mt-1">Valid from date is required</p>
          )}
        </div>

        {/* Valid To */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Calendar className="w-3.5 h-3.5 inline mr-1" />
            Statement Valid To <span className="text-red-500">*</span>
          </label>
          <input
            type="date"
            value={validTo}
            min={validFrom || undefined}
            disabled={locked}
            onChange={(e) => setValidTo(e.target.value)}
            onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
            className={`${dateError ? "w-full border border-red-300 bg-red-50 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" : fieldCls(validTo)} disabled:opacity-60 disabled:cursor-not-allowed`}
          />
          {touched && !validTo && (
            <p className="text-[11px] text-red-500 mt-1">Valid to date is required</p>
          )}
          {dateError && (
            <p className="text-[11px] text-red-500 mt-1">Valid to must be on or after valid from</p>
          )}
        </div>

        {/* completion indicator */}
        <div className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium ${
          isComplete ? "bg-green-50 text-green-700 border border-green-200" : "bg-gray-50 text-gray-400 border border-gray-200"
        }`}>
          <CheckCircle className={`w-4 h-4 ${isComplete ? "text-green-600" : "text-gray-300"}`} />
          {isComplete ? "Statement details complete" : "Complete all fields above"}
        </div>
      </div>
    </div>
  );
}

/** The gate both flows use before allowing a save. */
export const isStatementComplete = (agency: string, validFrom: string, validTo: string): boolean =>
  agency !== "" && validFrom !== "" && validTo !== "" && validTo >= validFrom;
