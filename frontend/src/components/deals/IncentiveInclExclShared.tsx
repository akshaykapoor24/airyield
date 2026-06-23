"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { ChevronDown, X, Check, Pencil, Plus, Trash2 } from "lucide-react";
import api from "@/lib/api";

// ── shared types ─────────────────────────────────────────────────────────
export type IEFieldValue = string | string[];

export type FieldConfig = {
  key: string; label: string;
  type: "date"|"select"|"search"|"number";
  condition?: { field: string; value: string };
  visible?: (data: Record<string, string>) => boolean;
};

export type SlabColDef = {
  key: string;
  header: string;
  type: "select" | "number" | "date";
  options?: string[];
};

export type AncillaryItem = {
  key: string;
  label: string;
  withValue: string;
  withoutValue: string;
  numPctKey: string;
  amtKey: string;
};

// ── static options ──────────────────────────────────────────────────────
export const INCENTIVE_TYPES = [
  "PLB","Super PLB","Transaction Fee",
  "Deposit Incentive (DI)","Marketing Fund","Ancillary",
  "Frontend","Backend","Cashback",
  "Segment Incentive","Push Action",
];

export const FREQUENCY_OPTIONS    = ["Quarterly","Half Yearly","Yearly"];
export const FLIGHT_TYPE_OPTIONS  = ["International","Domestic","Both"];
export const CLASS_OPTIONS        = ["All","Economy","Premium","Business"];
export const TARGET_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
export const PAYOUT_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
export const TARGET_BASED_OPTIONS = ["Amount Based","Segment Based"];

export const INCLUSIONS_EXCLUSIONS = [
  "Inclusion For Trigger",
  "Exclusion For Trigger",
  "Inclusion For Payout",
  "Exclusion For Payout",
];

export const CONTINENTS         = ["Africa","Asia","Europe","North America","Oceania","South America","Antarctica"];
export const COUNTRY_GROUPS     = ["APAC","EUROPEAN NATIONS","GCC/MIDDLE EAST","LATIN AMERICA","MEAI","MEAI/APAC","MEAI/SAARC","MEAI/SAARC/APAC","NAM","OTHER","SAARC","SAARC/APAC"];
export const COUNTRIES          = ["India","UAE","Saudi Arabia","Qatar","UK","Germany","USA","Singapore","Australia"];
export const AIRPORTS           = ["DEL","BOM","DXB","DOH","LHR","FRA","JFK","SIN","SYD"];
export const CITIES             = ["Delhi","Mumbai","Dubai","Doha","London","Frankfurt","New York","Singapore","Sydney"];
export const FARE_TYPE_CATS     = ["Normal","Group","Corporate","Excursion","Tour"];
export const TOUR_CODES         = ["TC001","TC002","TC003","TC004"];
export const DOMESTIC_CTRS      = ["India","UAE","UK","USA","Australia"];
export const SOTO_OPTIONS       = ["SOTO All","SOTO within India","SOTO outside India"];
export const INCL_CLASS_OPTIONS = ["All","Economy","Premium Economy","Business","First"];

export const FIELD_OPTIONS: Record<string, string[]> = {
  frequency:               FREQUENCY_OPTIONS,
  flightType:              FLIGHT_TYPE_OPTIONS,
  targetCalcCols:          TARGET_CALC_OPTIONS,
  payoutCalcCols:          PAYOUT_CALC_OPTIONS,
  targetBased:             TARGET_BASED_OPTIONS,
  amountBasedType:         ["Fixed", "Slab Based"],
  segmentBasedType:        ["Fixed", "Slab Based"],
  incentiveNumPct:    ["Number", "Percentage"],
  cashbackTargetType: ["Amount", "Percentage"],
  marketFundType:     ["Fixed", "Variable"],
  diType:             ["Bulk Deposit", "Normal Deposit"],
  bulkDepositType:    ["Single Deposit", "Tranches"],
  normalDepositType:  ["Bank Transfer", "Credit Card"],
  diCurrencySingle:   ["USD", "EUR", "INR", "AED", "GBP", "SGD", "AUD", "THB"],
  diCurrencyTranche:  ["USD", "EUR", "INR", "AED", "GBP", "SGD", "AUD", "THB"],
  diCurrencyBank:     ["USD", "EUR", "INR", "AED", "GBP", "SGD", "AUD", "THB"],
  diCurrencyCard:     ["USD", "EUR", "INR", "AED", "GBP", "SGD", "AUD", "THB"],
  bulkSingleNumPct:   ["Number", "Percentage"],
  trancheNumPct:      ["Number", "Percentage"],
  bankTransferNumPct: ["Number", "Percentage"],
  creditCardNumPct:   ["Number", "Percentage"],
  creditCardType:     ["Visa", "MasterCard", "American Express", "Rupay", "Others"],
  bankName:           ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Bank", "Yes Bank", "Citibank", "Standard Chartered", "HSBC", "Other"],
};

export const INCL_EXCL_SEARCH_OPTIONS: Record<string, string[]> = {
  continents: CONTINENTS, countryGroup: COUNTRY_GROUPS,
  originContinents: CONTINENTS, destContinents: CONTINENTS,
  originCountryGroup: COUNTRY_GROUPS, destCountryGroup: COUNTRY_GROUPS,
  originCountry: COUNTRIES, destCountry: COUNTRIES,
  originAirport: AIRPORTS, destAirport: AIRPORTS,
  city: CITIES, fareTypeCategory: FARE_TYPE_CATS,
  class: INCL_CLASS_OPTIONS, tourCode: TOUR_CODES,
  domesticCountry: DOMESTIC_CTRS, soto: SOTO_OPTIONS,
};

// ── compact select ─────────────────────────────────────────────────────────
export function SelectField({ label, placeholder="Select...", options, value, onChange }: {
  label?: string; placeholder?: string; options: string[];
  value: string; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  return (
    <div className="relative" ref={ref}>
      {label && <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={value ? "text-gray-800" : "text-gray-400"}>{value || placeholder}</span>
        <div className="flex items-center gap-0.5">
          {value && <span onClick={e => { e.stopPropagation(); onChange(""); }} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg max-h-44 overflow-y-auto">
          {options.map(opt => (
            <button key={opt} type="button" onClick={() => { onChange(opt); setOpen(false); }}
              className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-50 text-gray-700">{opt}</button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── compact search select ──────────────────────────────────────────────────
export function SearchSelectField({ label, placeholder="Search and select", options, value, onChange }: {
  label?: string; placeholder?: string; options: string[];
  value: string; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  const filtered = options.filter(o => o.toLowerCase().includes(search.toLowerCase()));
  return (
    <div className="relative" ref={ref}>
      {label && <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={() => { setOpen(o => !o); setSearch(""); }}
        className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={value ? "text-gray-800" : "text-gray-400"}>{value || placeholder}</span>
        <div className="flex items-center gap-0.5">
          {value && <span onClick={e => { e.stopPropagation(); onChange(""); }} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg">
          <div className="p-1.5 border-b border-gray-100">
            <input autoFocus value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..."
              className="w-full text-xs px-2 py-1 border border-gray-200 rounded focus:outline-none"/>
          </div>
          <div className="max-h-36 overflow-y-auto">
            {filtered.length ? filtered.map(opt => (
              <button key={opt} type="button" onClick={() => { onChange(opt); setOpen(false); }}
                className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-50 text-gray-700">{opt}</button>
            )) : <p className="px-2.5 py-1.5 text-xs text-gray-400">No results</p>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── multi-checkbox dropdown ────────────────────────────────────────────────
export function MultiCheckboxDropdown({ label, placeholder="Select...", options, values, onChange }: {
  label?: string; placeholder?: string; options: string[];
  values: string[]; onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  const toggle = (opt: string) => {
    onChange(values.includes(opt) ? values.filter(v => v !== opt) : [...values, opt]);
  };
  const display = values.length ? values.join(", ") : null;
  return (
    <div className="relative" ref={ref}>
      {label && <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={display ? "text-gray-800" : "text-gray-400"}>{display || placeholder}</span>
        <div className="flex items-center gap-0.5">
          {values.length > 0 && <span onClick={e => { e.stopPropagation(); onChange([]); }} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg">
          {options.map(opt => (
            <label key={opt} className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-blue-50 cursor-pointer">
              <input type="checkbox" checked={values.includes(opt)} onChange={() => toggle(opt)}
                className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
              {opt}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ── multi-value search select ───────────────────────────────────────────────
export function MultiSearchSelectField({ label, placeholder="Search and select", options, values, onChange }: {
  label?: string; placeholder?: string; options: string[];
  values: string[]; onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  const filtered = options.filter(o => o.toLowerCase().includes(search.toLowerCase()));
  const toggle = (opt: string) => onChange(values.includes(opt) ? values.filter(v => v !== opt) : [...values, opt]);
  const display = values.length ? values.join(", ") : null;
  return (
    <div className="relative" ref={ref}>
      {label && <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={() => { setOpen(o => !o); setSearch(""); }}
        className="w-full flex items-start justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400 min-h-[28px]">
        <span className={display ? "text-gray-800 whitespace-normal break-words leading-relaxed" : "text-gray-400"}>{display || placeholder}</span>
        <div className="flex items-center gap-0.5 flex-shrink-0 ml-1 mt-0.5">
          {values.length > 0 && <span onClick={e => { e.stopPropagation(); onChange([]); }} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg">
          <div className="p-1.5 border-b border-gray-100">
            <input autoFocus value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..."
              className="w-full text-xs px-2 py-1 border border-gray-200 rounded focus:outline-none"/>
          </div>
          <div className="max-h-44 overflow-y-auto">
            {filtered.length ? filtered.map(opt => (
              <label key={opt} className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-blue-50 cursor-pointer">
                <input type="checkbox" checked={values.includes(opt)} onChange={() => toggle(opt)}
                  className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
                {opt}
              </label>
            )) : <p className="px-2.5 py-1.5 text-xs text-gray-400">No results</p>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── free-text tag input (e.g. tour codes) ───────────────────────────────────
export function TagInput({ label, placeholder="Type and press Enter", values, onChange }: {
  label?: string; placeholder?: string; values: string[]; onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState("");
  const commit = () => { const v = text.trim(); if (v && !values.includes(v)) { onChange([...values, v]); } setText(""); };
  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    if (e.key === "Backspace" && !text && values.length) { onChange(values.slice(0, -1)); }
  };
  return (
    <div>
      {label && <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <div className="min-h-[28px] border border-gray-200 rounded-md px-2 py-1 flex flex-wrap gap-1 bg-white focus-within:ring-1 focus-within:ring-blue-400">
        {values.map(v => (
          <span key={v} className="flex items-center gap-1 px-1.5 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded text-[10px] font-medium">
            {v}<button type="button" onClick={() => onChange(values.filter(x => x !== v))} className="text-blue-400 hover:text-red-500 leading-none"><X className="w-2.5 h-2.5"/></button>
          </span>
        ))}
        <input value={text} onChange={e => setText(e.target.value)} onKeyDown={handleKey} onBlur={commit}
          placeholder={values.length ? "" : placeholder}
          className="flex-1 min-w-[80px] text-xs border-none outline-none bg-transparent py-0.5 text-gray-800 placeholder-gray-400"/>
      </div>
      <p className="text-[9px] text-gray-400 mt-0.5">Press Enter or comma to add a code</p>
    </div>
  );
}

// ── date input ─────────────────────────────────────────────────────────────
export function DateField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  // Always a real date input so the FIRST click opens the native calendar (no
  // text→date swap that used to cost a click). Stays empty until a date is picked —
  // no current date is pre-filled.
  return (
    <div>
      <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
      <input type="date" value={value}
        onClick={e => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported — ignore */ } }}
        onChange={e => onChange(e.currentTarget.value)}
        className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-400 cursor-pointer"/>
    </div>
  );
}

// ── tab bar ────────────────────────────────────────────────────────────────
export function TabBar({ tabs, active, onSelect, onRemove }: {
  tabs: string[]; active: string;
  onSelect: (t: string) => void;
  onRemove?: (t: string) => void;
}) {
  return (
    <div className="flex items-center gap-1 flex-wrap border-b border-gray-100 px-4 pt-3">
      {tabs.map(t => (
        <div key={t} onClick={() => onSelect(t)}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-t-md text-xs font-medium cursor-pointer border-b-2 transition-colors ${
            active === t
              ? "border-blue-500 text-blue-600 bg-blue-50/60"
              : "border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50"
          }`}>
          {t}
          {onRemove && (
            <span onClick={e => { e.stopPropagation(); onRemove(t); }}
              className="ml-0.5 text-gray-300 hover:text-red-400 leading-none">
              <X className="w-3 h-3"/>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── section card wrapper ───────────────────────────────────────────────────
export function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200">
      <div className="px-4 py-2.5 border-b border-gray-100">
        <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">{title}</h2>
      </div>
      {children}
    </div>
  );
}

// ── payout fields (Fixed / Slab Based tree) ─────────────────────────────────
export function payoutFields(n: string): FieldConfig[] {
  return [
    // Step 1: appears when Target Based (Amount or Segment) is selected
    {
      key: "amountBasedType",
      label: `Amount Based for ${n}`,
      type: "select",
      visible: (d) => d["targetBased"] === "Amount Based" || d["targetBased"] === "Segment Based",
    },
    // Step 2a (Fixed path): Base Target Amount
    {
      key: "baseTargetAmount",
      label: `Base Target Amount for ${n}`,
      type: "number",
      visible: (d) => d["amountBasedType"] === "Fixed",
    },
    // Step 2b: Number or Percentage selector — Fixed AND Slab Based paths
    {
      key: "incentiveNumPct",
      label: `Incentive in Number or Percentage for ${n}`,
      type: "select",
      visible: (d) => d["amountBasedType"] === "Fixed" || d["amountBasedType"] === "Slab Based",
    },
    // Step 3: Incentive value — Fixed path only (Slab Based uses the grid instead)
    {
      key: "incentiveAmtPct",
      label: `Incentive Percentage or Amount for ${n}`,
      type: "number",
      visible: (d) =>
        d["amountBasedType"] === "Fixed" &&
        (d["incentiveNumPct"] === "Number" || d["incentiveNumPct"] === "Percentage"),
    },
    // Step 4: Capped Incentive — Fixed + Percentage only (cap expressed both ways)
    {
      key: "cappedIncentive",
      label: `Capped Incentive for ${n} in percentage`,
      type: "number",
      visible: (d) => d["amountBasedType"] === "Fixed" && d["incentiveNumPct"] === "Percentage",
    },
    {
      key: "cappedIncentiveAmount",
      label: `Capped Incentive for ${n} in amount`,
      type: "number",
      visible: (d) => d["amountBasedType"] === "Fixed" && d["incentiveNumPct"] === "Percentage",
    },
  ];
}

export const INCENTIVE_FIELDS: Record<string, FieldConfig[]> = {
  "PLB": [
    { key:"validFrom",      label:"Contract Valid from for PLB",       type:"date"   },
    { key:"validTo",        label:"Contract Valid to for PLB",         type:"date"   },
    { key:"frequency",      label:"Frequency for PLB",                 type:"select" },
    { key:"flightType",     label:"Flight Type for PLB",               type:"select" },
    { key:"class",          label:"Class for PLB",                     type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for PLB",       type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for PLB",       type:"select" },
    { key:"targetBased",    label:"Target Based for PLB",              type:"select" },
    ...payoutFields("PLB"),
  ],
  "Super PLB": [
    { key:"validFrom",      label:"Contract Valid from for Super PLB",       type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Super PLB",         type:"date"   },
    { key:"frequency",      label:"Frequency for Super PLB",                 type:"select" },
    { key:"flightType",     label:"Flight Type for Super PLB",               type:"select" },
    { key:"class",          label:"Class for Super PLB",                     type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Super PLB",       type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Super PLB",       type:"select" },
    { key:"targetBased",    label:"Target Based for Super PLB",              type:"select" },
    ...payoutFields("Super PLB"),
  ],
  "Transaction Fee": [
    { key:"validFrom",      label:"Contract Valid from for Transaction Fee",       type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Transaction Fee",         type:"date"   },
    { key:"frequency",      label:"Frequency for Transaction Fee",                 type:"select" },
    { key:"flightType",     label:"Flight Type for Transaction Fee",               type:"select" },
    { key:"class",          label:"Class for Transaction Fee",                     type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Transaction Fee",       type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Transaction Fee",       type:"select" },
    { key:"targetBased",    label:"Target Based for Transaction Fee",              type:"select" },
    ...payoutFields("Transaction Fee"),
  ],
  "Deposit Incentive (DI)": [
    // ── Level 1 ──────────────────────────────────────────────────────────
    { key:"diType", label:"Deposit Incentive Types", type:"select" },

    // ── Bulk Deposit ─────────────────────────────────────────────────────
    { key:"bulkDepositType", label:"Bulk Deposit Types", type:"select",
      visible:(d) => d["diType"] === "Bulk Deposit" },

    // Single Deposit fields
    { key:"depositAmount", label:"Deposit Amount", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Single Deposit" },
    { key:"diCurrencySingle", label:"Currency", type:"select",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Single Deposit" },
    { key:"bulkSingleNumPct", label:"Incentive in Number or Percentage", type:"select",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Single Deposit" },
    { key:"bulkSingleAmt", label:"Incentive Percentage or Amount", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Single Deposit" &&
                     (d["bulkSingleNumPct"] === "Number" || d["bulkSingleNumPct"] === "Percentage") },
    { key:"bulkSingleCapped", label:"Capped Incentive", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Single Deposit" &&
                     d["bulkSingleNumPct"] === "Percentage" },

    // Tranches fields
    { key:"numberOfTranches", label:"Number of Tranches", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Tranches" },
    { key:"perTrancheAmount", label:"Per Tranche Amount", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Tranches" },
    { key:"diCurrencyTranche", label:"Currency", type:"select",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Tranches" },
    { key:"trancheNumPct", label:"Incentive in Number or Percentage", type:"select",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Tranches" },
    { key:"trancheAmt", label:"Incentive Percentage or Amount", type:"number",
      visible:(d) => d["diType"] === "Bulk Deposit" && d["bulkDepositType"] === "Tranches" &&
                     (d["trancheNumPct"] === "Number" || d["trancheNumPct"] === "Percentage") },

    // ── Normal Deposit ────────────────────────────────────────────────────
    { key:"normalDepositType", label:"Normal Deposit Types", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" },

    // Bank Transfer fields
    { key:"bankName", label:"Bank Name", type:"search",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Bank Transfer" },
    { key:"bankTransferRate", label:"Rate of Bank Transfer", type:"number",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Bank Transfer" },
    { key:"diCurrencyBank", label:"Currency", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Bank Transfer" },
    { key:"bankTransferNumPct", label:"Incentive in Number or Percentage", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Bank Transfer" },
    { key:"bankTransferAmt", label:"Incentive Percentage or Amount", type:"number",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Bank Transfer" &&
                     (d["bankTransferNumPct"] === "Number" || d["bankTransferNumPct"] === "Percentage") },

    // Credit Card fields
    { key:"creditCardType", label:"Credit Card Type", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Credit Card" },
    { key:"processingFee", label:"Processing Fee (%)", type:"number",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Credit Card" },
    { key:"diCurrencyCard", label:"Currency", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Credit Card" },
    { key:"creditCardNumPct", label:"Incentive in Number or Percentage", type:"select",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Credit Card" },
    { key:"creditCardAmt", label:"Incentive Percentage or Amount", type:"number",
      visible:(d) => d["diType"] === "Normal Deposit" && d["normalDepositType"] === "Credit Card" &&
                     (d["creditCardNumPct"] === "Number" || d["creditCardNumPct"] === "Percentage") },
  ],
  "Marketing Fund": [
    { key:"validFrom",      label:"Contract Valid from for Marketing Fund",    type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Marketing Fund",      type:"date"   },
    { key:"frequency",      label:"Frequency for Marketing Fund",              type:"select" },
    { key:"flightType",     label:"Flight Type for Marketing Fund",            type:"select" },
    { key:"class",          label:"Class for Marketing Fund",                  type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Marketing Fund",    type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Marketing Fund",    type:"select" },
    { key:"targetBased",    label:"Target Based for Marketing Fund",           type:"select" },
    { key:"marketFundType", label:"Market Fund Type",                          type:"select" },
    { key:"exchangeRate",   label:"Exchange Rate",                             type:"number" },
    ...payoutFields("Marketing Fund"),
  ],
  "Ancillary": [], // rendered by AncillaryTabContent
  "Frontend": [
    { key:"validFrom",      label:"Contract Valid from for Frontend",        type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Frontend",          type:"date"   },
    { key:"frequency",      label:"Frequency for Frontend",                  type:"select" },
    { key:"flightType",     label:"Flight Type for Frontend",                type:"select" },
    { key:"class",          label:"Class for Frontend",                      type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Frontend",        type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Frontend",        type:"select" },
    { key:"targetBased",    label:"Target Based for Frontend",               type:"select" },
    ...payoutFields("Frontend"),
  ],
  "Backend": [
    { key:"validFrom",      label:"Contract Valid from for Backend",         type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Backend",           type:"date"   },
    { key:"frequency",      label:"Frequency for Backend",                   type:"select" },
    { key:"flightType",     label:"Flight Type for Backend",                 type:"select" },
    { key:"class",          label:"Class for Backend",                       type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Backend",         type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Backend",         type:"select" },
    { key:"targetBased",    label:"Target Based for Backend",                type:"select" },
    ...payoutFields("Backend"),
  ],
  "Cashback": [
    { key:"cashbackPeriodFrom",  label:"Period From for Cashback",                 type:"date"   },
    { key:"cashbackPeriodTo",    label:"Period To for Cashback",                   type:"date"   },
    { key:"cashbackTargetType",  label:"Target in Percent or Amount for Cashback", type:"select" },
    {
      key:     "cashbackTargetValue",
      label:   "Target Percent or Amount for Cashback",
      type:    "number",
      visible: (d) => d["cashbackTargetType"] === "Amount" || d["cashbackTargetType"] === "Percentage",
    },
  ],
  "Segment Incentive": [], // rendered by SegmentIncentiveTabContent
  "Push Action": [
    { key:"validFrom",      label:"Contract Valid from for Push Action",      type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Push Action",        type:"date"   },
    { key:"frequency",      label:"Frequency for Push Action",                type:"select" },
    { key:"flightType",     label:"Flight Type for Push Action",              type:"select" },
    { key:"class",          label:"Class for Push Action",                    type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Push Action",      type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Push Action",      type:"select" },
    { key:"targetBased",    label:"Target Based for Push Action",             type:"select" },
    ...payoutFields("Push Action"),
  ],
};

// ── ancillary sub-form ────────────────────────────────────────────────────
export const ANCILLARY_ITEMS: AncillaryItem[] = [
  { key:"baggageType",  label:"Baggage Type",     withValue:"With Baggage",       withoutValue:"Without Baggage",       numPctKey:"baggageNumPct",  amtKey:"baggageAmt"   },
  { key:"meals",        label:"Meals",             withValue:"With Meal",          withoutValue:"Without Meal",          numPctKey:"mealsNumPct",    amtKey:"mealsAmt"     },
  { key:"seatFees",     label:"Seat Fees",         withValue:"With Seat Fees",     withoutValue:"Without Seat Fees",     numPctKey:"seatFeesNumPct", amtKey:"seatFeesAmt"  },
  { key:"transport",    label:"Transport",         withValue:"With Transport",     withoutValue:"Without Transport",     numPctKey:"transportNumPct",amtKey:"transportAmt" },
  { key:"groupBooking", label:"Group Booking Fee", withValue:"With Group Booking", withoutValue:"Without Group Booking", numPctKey:"groupNumPct",    amtKey:"groupAmt"     },
  { key:"loungeAccess", label:"Lounge Access",     withValue:"With Lounge Access", withoutValue:"Without Lounge Access", numPctKey:"loungeNumPct",   amtKey:"loungeAmt"    },
  { key:"cabFacility",  label:"Cab Facility",      withValue:"With Cab Facility",  withoutValue:"Without Cab Facility",  numPctKey:"cabNumPct",      amtKey:"cabAmt"       },
];

export function AncillaryTabContent({ data, onChange }: {
  data: Record<string, string>;
  onChange: (k: string, v: string) => void;
}) {
  const handleChange = (key: string, value: string) => {
    onChange(key, value);
    const item = ANCILLARY_ITEMS.find(i => i.key === key);
    if (item) { onChange(item.numPctKey, ""); onChange(item.amtKey, ""); }
    const byNumPct = ANCILLARY_ITEMS.find(i => i.numPctKey === key);
    if (byNumPct) { onChange(byNumPct.amtKey, ""); }
  };

  const pairs: AncillaryItem[][] = [];
  for (let i = 0; i < ANCILLARY_ITEMS.length; i += 2) pairs.push(ANCILLARY_ITEMS.slice(i, i + 2));

  const renderCard = (item: AncillaryItem) => {
    const parentVal  = data[item.key]       ?? "";
    const numPctVal  = data[item.numPctKey] ?? "";
    const isWith     = parentVal === item.withValue;
    const amtVisible = isWith && (numPctVal === "Number" || numPctVal === "Percentage");

    return (
      <div className="border border-gray-200 rounded-lg p-3 bg-white space-y-2.5">
        <SelectField
          label={item.label}
          options={[item.withValue, item.withoutValue]}
          value={parentVal}
          onChange={v => handleChange(item.key, v)}
        />
        {isWith && (
          <>
            <SelectField
              label={`Incentive in Number or Percentage for ${item.label}`}
              options={["Number", "Percentage"]}
              value={numPctVal}
              onChange={v => handleChange(item.numPctKey, v)}
            />
            {amtVisible && (
              <div>
                <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">
                  Incentive Percentage or Amount for {item.label}
                </label>
                <input
                  type="number"
                  placeholder="Enter number"
                  value={data[item.amtKey] ?? ""}
                  onChange={e => onChange(item.amtKey, e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <div className="px-4 py-3 space-y-3">
      {pairs.map((pair, i) => (
        <div key={i} className={`grid gap-3 ${pair.length === 2 ? "grid-cols-2" : "grid-cols-1 max-w-[50%]"}`}>
          {pair.map(item => <div key={item.key}>{renderCard(item)}</div>)}
        </div>
      ))}
    </div>
  );
}

// ── slab grid ─────────────────────────────────────────────────────────────
// Frequency drives which period column the slab table shows:
//   Quarterly  → Quarterly Freq (Q1–Q4)
//   Half Yearly→ Half Yearly Freq (H1/H2)
//   Yearly     → neither (whole-year band)
//   unset/other→ both (legacy fallback so existing deals keep their column)
function freqSlabCols(frequency: string): SlabColDef[] {
  const quarterly: SlabColDef  = { key: "quarterlyFreq",  header: "Quarterly Freq",   type: "select", options: ["Q1","Q2","Q3","Q4"] };
  const halfYearly: SlabColDef = { key: "halfYearlyFreq", header: "Half Yearly Freq", type: "select", options: ["H1","H2"] };
  if (frequency === "Quarterly")   return [quarterly];
  if (frequency === "Half Yearly") return [halfYearly];
  if (frequency === "Yearly")      return [];
  return [quarterly, halfYearly];
}

export function amountSlabCols(_n: string, flightType: string, frequency = ""): SlabColDef[] {
  const domesticCols: SlabColDef[] = [
    { key: "domEconomy",  header: "Domestic Economy",  type: "number" },
    { key: "domPremium",  header: "Domestic Premium",  type: "number" },
    { key: "domBusiness", header: "Domestic Business", type: "number" },
  ];
  const intlCols: SlabColDef[] = [
    { key: "intlEconomy",  header: "International Economy",  type: "number" },
    { key: "intlPremium",  header: "International Premium",  type: "number" },
    { key: "intlBusiness", header: "International Business", type: "number" },
  ];
  const segmentClassCols =
    flightType === "Domestic"        ? domesticCols
    : flightType === "International" ? intlCols
    : [...domesticCols, ...intlCols];

  return [
    ...freqSlabCols(frequency),
    { key: "baseTargetNumPct",      header: "Base Target (Num / Pct)", type: "select", options: ["Number","Percentage"] },
    { key: "baseTargetAmount",      header: "Base Target Amount",      type: "number" },
    { key: "targetFrom",            header: "Target From",             type: "number" },
    { key: "targetTo",              header: "Target To",               type: "number" },
    ...segmentClassCols,
    { key: "cappedIncentive",       header: "Capped Incentive %",      type: "number" },
    { key: "cappedIncentiveAmount", header: "Capped Incentive Amt",    type: "number" },
  ];
}

export function segmentSlabCols(flightType: string, frequency = ""): SlabColDef[] {
  const domesticCols: SlabColDef[] = [
    { key: "domEconomy",  header: "Domestic Economy",  type: "number" },
    { key: "domPremium",  header: "Domestic Premium",  type: "number" },
    { key: "domBusiness", header: "Domestic Business", type: "number" },
  ];
  const intlCols: SlabColDef[] = [
    { key: "intlEconomy",  header: "International Economy",  type: "number" },
    { key: "intlPremium",  header: "International Premium",  type: "number" },
    { key: "intlBusiness", header: "International Business", type: "number" },
  ];
  const segmentClassCols =
    flightType === "Domestic"        ? domesticCols
    : flightType === "International" ? intlCols
    : [...domesticCols, ...intlCols]; // "Both" or unset → all combinations

  return [
    ...freqSlabCols(frequency),
    { key: "targetFrom",           header: "Target From",      type: "number" },
    { key: "targetTo",             header: "Target To",        type: "number" },
    ...segmentClassCols,
    { key: "incentiveValue",       header: "Incentive Value in percentage", type: "number" },
    { key: "incentiveValueAmount", header: "Incentive Value in amount",     type: "number" },
  ];
}

export function SlabGrid({ title, cols, rows, onRowsChange }: {
  title: string;
  cols: SlabColDef[];
  rows: Record<string, string>[];
  onRowsChange: (rows: Record<string, string>[]) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState(false);

  const addRow = () => {
    const newRow: Record<string, string> = { id: Math.random().toString(36).slice(2) };
    cols.forEach(c => { newRow[c.key] = ""; });
    onRowsChange([...rows, newRow]);
  };

  const deleteSelected = () => {
    onRowsChange(rows.filter(r => !selected.has(r.id)));
    setSelected(new Set());
  };

  const updateCell = (rowId: string, key: string, value: string) => {
    onRowsChange(rows.map(r => r.id === rowId ? { ...r, [key]: value } : r));
    setEditing(true);
  };

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const allSelected = rows.length > 0 && rows.every(r => selected.has(r.id));

  const renderCell = (row: Record<string, string>, col: SlabColDef) => {
    if (col.type === "select") {
      return (
        <select
          value={row[col.key] ?? ""}
          onChange={e => updateCell(row.id, col.key, e.target.value)}
          onBlur={() => setEditing(false)}
          className="w-full bg-transparent text-xs text-gray-700 focus:outline-none cursor-pointer py-0.5 min-w-[80px]"
        >
          <option value="">—</option>
          {(col.options ?? []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    if (col.type === "number") {
      return (
        <input
          type="number"
          value={row[col.key] ?? "0"}
          onChange={e => updateCell(row.id, col.key, e.target.value)}
          onBlur={() => setEditing(false)}
          className="w-full bg-transparent text-xs text-gray-700 focus:outline-none text-right min-w-[60px]"
        />
      );
    }
    return (
      <input
        type="date"
        value={row[col.key] ?? ""}
        onClick={e => { try { e.currentTarget.showPicker?.(); } catch { /* ignore */ } }}
        onChange={e => updateCell(row.id, col.key, e.target.value)}
        onBlur={() => setEditing(false)}
        className="w-full bg-transparent text-xs text-gray-700 focus:outline-none min-w-[110px] cursor-pointer"
      />
    );
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-white border-b border-gray-100">
        <span className="text-xs font-semibold text-gray-700">{title}</span>
        <div className="flex items-center gap-4">
          {editing
            ? <span className="text-xs text-amber-500 flex items-center gap-1"><Pencil className="w-3 h-3"/>Editing...</span>
            : <span className="text-xs text-green-600 flex items-center gap-1"><Check className="w-3 h-3"/>Saved</span>
          }
          <button type="button" onClick={addRow}
            className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1">
            <Plus className="w-3 h-3"/>Add row
          </button>
          <button type="button" onClick={deleteSelected} disabled={selected.size === 0}
            className="text-xs text-red-500 hover:text-red-600 flex items-center gap-1 disabled:opacity-40">
            <Trash2 className="w-3 h-3"/>Delete Rows
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="w-8 px-2 py-2 border-r border-gray-200">
                <input type="checkbox" checked={allSelected}
                  onChange={() => allSelected ? setSelected(new Set()) : setSelected(new Set(rows.map(r => r.id)))}
                  className="w-3.5 h-3.5 accent-blue-600 rounded"/>
              </th>
              {cols.map(c => (
                <th key={c.key} className="px-3 py-2 text-left font-medium text-gray-500 border-r border-gray-200 last:border-r-0 min-w-[80px] max-w-[120px]">
                  <span className="text-[11px] leading-tight break-words">{c.header}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 && (
              <tr>
                <td colSpan={cols.length + 1} className="px-3 py-4 text-center text-xs text-gray-400">
                  No rows yet — click Add row
                </td>
              </tr>
            )}
            {rows.map(row => (
              <tr key={row.id}
                className={`transition-colors ${selected.has(row.id) ? "bg-blue-50" : "hover:bg-gray-50/60"}`}>
                <td className="px-2 py-1 text-center border-r border-gray-100">
                  <input type="checkbox" checked={selected.has(row.id)} onChange={() => toggleSelect(row.id)}
                    className="w-3.5 h-3.5 accent-blue-600 rounded"/>
                </td>
                {cols.map(c => (
                  <td key={c.key} className="px-3 py-1 border-r border-gray-100 last:border-r-0">
                    {renderCell(row, c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── segment incentive form ────────────────────────────────────────────────
export function SegmentIncentiveTabContent({ data, onChange }: {
  data: Record<string, string>;
  onChange: (k: string, v: string) => void;
}) {
  const flightType = data["siFlightType"] ?? "";

  const domesticCols: SlabColDef[] = [
    { key:"domEconomy",       header:"Domestic Economy",         type:"number" },
    { key:"domPremEconomy",   header:"Domestic Premium Economy", type:"number" },
    { key:"domBusinessFirst", header:"Domestic Business/First",  type:"number" },
  ];
  const intlCols: SlabColDef[] = [
    { key:"intlEconomy",       header:"International Economy",          type:"number" },
    { key:"intlPremEconomy",   header:"International Premium Economy",  type:"number" },
    { key:"intlBusinessFirst", header:"International Business/First",   type:"number" },
  ];
  const baseCols: SlabColDef[] = [
    { key:"numberOfSegments", header:"Number of Segments", type:"number" },
    { key:"targetFrom",       header:"Target From",         type:"number" },
    { key:"targetTo",         header:"Target To",           type:"number" },
  ];

  const slabCols: SlabColDef[] = [
    ...baseCols,
    ...(flightType === "International" ? intlCols
      : flightType === "Domestic"      ? domesticCols
      : [...domesticCols, ...intlCols]),   // All or unset → both
  ];

  const slabRows = useMemo<Record<string, string>[]>(() => {
    try { return JSON.parse(data["siSlabs"] ?? "[]"); } catch { return []; }
  }, [data]);

  const handleFlightTypeChange = (v: string) => {
    onChange("siFlightType", v);
    onChange("siSlabs", "[]");  // reset slab rows when flight type changes
  };

  return (
    <div className="px-4 py-3 space-y-3">
      {/* Row 1: Period From | Period To */}
      <div className="grid grid-cols-2 gap-3">
        <DateField
          label="Period From for Segment Incentive"
          value={data["siPeriodFrom"] ?? ""}
          onChange={v => onChange("siPeriodFrom", v)}
        />
        <DateField
          label="Period To for Segment Incentive"
          value={data["siPeriodTo"] ?? ""}
          onChange={v => onChange("siPeriodTo", v)}
        />
      </div>

      {/* Row 2: Target Type | Target Value */}
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Target in Percent or Amount for Segment Incentive"
          options={["Amount", "Percentage"]}
          value={data["siTargetType"] ?? ""}
          onChange={v => onChange("siTargetType", v)}
        />
        <div>
          <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">
            Target Percent or Amount for Segment Incentive
          </label>
          <input
            type="number"
            placeholder="Enter Number"
            value={data["siTargetValue"] ?? ""}
            onChange={e => onChange("siTargetValue", e.target.value)}
            className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      </div>

      {/* Row 3: Class | Flight Type */}
      <div className="grid grid-cols-2 gap-3">
        <SearchSelectField
          label="Class for Segment Incentive"
          options={["All", "Economy", "Premium", "Business"]}
          value={data["siClass"] ?? ""}
          onChange={v => onChange("siClass", v)}
        />
        <SelectField
          label="Flight Type for Segment Incentive"
          options={["All", "Domestic", "International"]}
          value={flightType}
          onChange={handleFlightTypeChange}
        />
      </div>

      {/* Slab table — columns driven by Flight Type */}
      <SlabGrid
        title="Segment Incentive Slab"
        cols={slabCols}
        rows={slabRows}
        onRowsChange={r => onChange("siSlabs", JSON.stringify(r))}
      />
    </div>
  );
}

// ── incentive tab content ──────────────────────────────────────────────────
export function IncentiveTabContent({ name, data, onChange }: {
  name: string; data: Record<string, string>; onChange: (k: string, v: string) => void;
}) {
  if (name === "Ancillary") {
    return <AncillaryTabContent data={data} onChange={onChange} />;
  }
  if (name === "Segment Incentive") {
    return <SegmentIncentiveTabContent data={data} onChange={onChange} />;
  }

  const allFields = INCENTIVE_FIELDS[name] ?? [];

  // Clear downstream fields when a parent field changes
  const handleFieldChange = (key: string, value: string) => {
    onChange(key, value);
    if (key === "targetBased") {
      onChange("amountBasedType", "");
      onChange("baseTargetAmount", "");
      onChange("incentiveNumPct", "");
      onChange("incentiveAmtPct", "");
      onChange("cappedIncentive", "");
      onChange("cappedIncentiveAmount", "");
      onChange("amountSlabs", "[]");
      onChange("segmentSlabs", "[]");
    } else if (key === "amountBasedType") {
      onChange("baseTargetAmount", "");
      onChange("incentiveNumPct", "");
      onChange("incentiveAmtPct", "");
      onChange("cappedIncentive", "");
      onChange("cappedIncentiveAmount", "");
      onChange("amountSlabs", "[]");
      onChange("segmentSlabs", "[]");
    } else if (key === "incentiveNumPct") {
      onChange("incentiveAmtPct", "");
      onChange("cappedIncentive", "");
      onChange("cappedIncentiveAmount", "");
    } else if (key === "flightType") {
      onChange("amountSlabs", "[]");
      onChange("segmentSlabs", "[]");
    } else if (key === "cashbackTargetType") {
      onChange("cashbackTargetValue", "");
    } else if (key === "diType") {
      // clear all DI sub-fields
      ["bulkDepositType","depositAmount","diCurrencySingle","bulkSingleNumPct","bulkSingleAmt","bulkSingleCapped",
       "numberOfTranches","perTrancheAmount","diCurrencyTranche","trancheNumPct","trancheAmt",
       "normalDepositType","bankName","bankTransferRate","diCurrencyBank","bankTransferNumPct","bankTransferAmt",
       "creditCardType","processingFee","diCurrencyCard","creditCardNumPct","creditCardAmt",
      ].forEach(k => onChange(k, ""));
    } else if (key === "bulkDepositType") {
      ["depositAmount","diCurrencySingle","bulkSingleNumPct","bulkSingleAmt","bulkSingleCapped",
       "numberOfTranches","perTrancheAmount","diCurrencyTranche","trancheNumPct","trancheAmt",
      ].forEach(k => onChange(k, ""));
    } else if (key === "bulkSingleNumPct") {
      onChange("bulkSingleAmt", ""); onChange("bulkSingleCapped", "");
    } else if (key === "trancheNumPct") {
      onChange("trancheAmt", "");
    } else if (key === "normalDepositType") {
      ["bankName","bankTransferRate","diCurrencyBank","bankTransferNumPct","bankTransferAmt",
       "creditCardType","processingFee","diCurrencyCard","creditCardNumPct","creditCardAmt",
      ].forEach(k => onChange(k, ""));
    } else if (key === "bankTransferNumPct") {
      onChange("bankTransferAmt", "");
    } else if (key === "creditCardNumPct") {
      onChange("creditCardAmt", "");
    }
  };

  const visible = allFields.filter(f => {
    if (f.visible) return f.visible(data);
    if (!f.condition) return true;
    const actual = data[f.condition.field] ?? "";
    if (f.condition.value === "__set__") return actual !== "";
    return actual === f.condition.value;
  });

  const fieldRows: FieldConfig[][] = [];
  for (let i = 0; i < visible.length; i += 2) fieldRows.push(visible.slice(i, i + 2));

  const renderField = (f: FieldConfig) => {
    if (f.type === "date")
      return <DateField label={f.label} value={data[f.key]??""} onChange={v => handleFieldChange(f.key, v)}/>;
    if (f.type === "number")
      return (
        <div>
          <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{f.label}</label>
          <input type="number" placeholder="Enter number" value={data[f.key]??""} onChange={e => handleFieldChange(f.key, e.target.value)}
            className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
        </div>
      );
    if (f.type === "search")
      return <SearchSelectField label={f.label} options={FIELD_OPTIONS[f.key] ?? CLASS_OPTIONS} value={data[f.key]??""} onChange={v => handleFieldChange(f.key, v)}/>;
    return <SelectField label={f.label} options={FIELD_OPTIONS[f.key]??[]} value={data[f.key]??""} onChange={v => handleFieldChange(f.key, v)}/>;
  };

  // Slab table visibility
  const showAmountSlab  = data["amountBasedType"] === "Slab Based" && data["targetBased"] === "Amount Based";
  const showSegmentSlab = data["amountBasedType"] === "Slab Based" && data["targetBased"] === "Segment Based";

  // Plain computation (not useMemo) — this function already returns early for
  // Ancillary/Segment Incentive above, so a hook here would be called conditionally.
  let amountSlabRows: Record<string, string>[] = [];
  try { amountSlabRows = JSON.parse(data["amountSlabs"] ?? "[]"); } catch { amountSlabRows = []; }

  let segmentSlabRows: Record<string, string>[] = [];
  try { segmentSlabRows = JSON.parse(data["segmentSlabs"] ?? "[]"); } catch { segmentSlabRows = []; }

  return (
    <div className="px-4 py-3 space-y-3">
      {fieldRows.map((pair, ri) => (
        <div key={ri} className={`grid gap-3 ${pair.length === 2 ? "grid-cols-2" : "grid-cols-1 max-w-[50%]"}`}>
          {pair.map(f => <div key={f.key}>{renderField(f)}</div>)}
        </div>
      ))}

      {showAmountSlab && (
        <SlabGrid
          title={`${name} Amount Slab`}
          cols={amountSlabCols(name, data["flightType"] ?? "", data["frequency"] ?? "")}
          rows={amountSlabRows}
          onRowsChange={r => onChange("amountSlabs", JSON.stringify(r))}
        />
      )}

      {showSegmentSlab && (
        <SlabGrid
          title={`${name} Segment Slab`}
          cols={segmentSlabCols(data["flightType"] ?? "", data["frequency"] ?? "")}
          rows={segmentSlabRows}
          onRowsChange={r => onChange("segmentSlabs", JSON.stringify(r))}
        />
      )}
    </div>
  );
}

// ── incl/excl tab content (multi-value across all condition fields) ────────
export function InclExclTabContent({ suffix, isExclusion, data, onChange, viceVersa, onViceVersa, continentOptions, countryGroupOptions }: {
  suffix: string; isExclusion: boolean;
  data: Record<string, IEFieldValue>; onChange: (k: string, v: IEFieldValue) => void;
  viceVersa: boolean; onViceVersa: () => void;
  continentOptions: string[]; countryGroupOptions: string[];
}) {
  const [originCountries, setOriginCountries] = useState<string[]>([]);
  const [destCountries,   setDestCountries]   = useState<string[]>([]);
  const [originAirports,  setOriginAirports]  = useState<string[]>([]);
  const [destAirports,    setDestAirports]    = useState<string[]>([]);
  const [allCountries,    setAllCountries]    = useState<string[]>([]);
  const [allAirports,     setAllAirports]     = useState<string[]>([]);

  const asArray = (v: IEFieldValue | undefined): string[] => Array.isArray(v) ? v : v ? [v] : [];

  // Country/airport option-narrowing keys off the first selected continent/country —
  // multi-value fields may hold several, but narrowing only needs one to start from.
  const origContinent = asArray(data["originContinents"])[0] ?? "";
  const destContinent = asArray(data["destContinents"])[0] ?? "";
  const origCountry   = asArray(data["originCountry"])[0] ?? "";
  const destCountry   = asArray(data["destCountry"])[0] ?? "";

  useEffect(() => {
    api.get<{ iata_code: string; country: string | null }[]>("/airports/?limit=5000")
      .then(r => {
        setAllAirports(r.data.map(a => a.iata_code).filter(Boolean));
        const countries = [...new Set(r.data.map(a => a.country).filter(Boolean))] as string[];
        setAllCountries(countries.sort());
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!origContinent) { setOriginCountries([]); return; }
    api.get<{ countries: string[] }>(`/airports/options?continent=${encodeURIComponent(origContinent)}`)
      .then(r => setOriginCountries(r.data.countries ?? []))
      .catch(() => setOriginCountries([]));
  }, [origContinent]);

  useEffect(() => {
    if (!destContinent) { setDestCountries([]); return; }
    api.get<{ countries: string[] }>(`/airports/options?continent=${encodeURIComponent(destContinent)}`)
      .then(r => setDestCountries(r.data.countries ?? []))
      .catch(() => setDestCountries([]));
  }, [destContinent]);

  useEffect(() => {
    if (!origCountry) { setOriginAirports([]); return; }
    api.get<{ airports: string[] }>(`/airports/options?country=${encodeURIComponent(origCountry)}`)
      .then(r => setOriginAirports(r.data.airports ?? []))
      .catch(() => setOriginAirports([]));
  }, [origCountry]);

  useEffect(() => {
    if (!destCountry) { setDestAirports([]); return; }
    api.get<{ airports: string[] }>(`/airports/options?country=${encodeURIComponent(destCountry)}`)
      .then(r => setDestAirports(r.data.airports ?? []))
      .catch(() => setDestAirports([]));
  }, [destCountry]);

  const localOptions: Record<string, string[]> = {
    ...INCL_EXCL_SEARCH_OPTIONS,
    continents:         continentOptions,
    countryGroup:       countryGroupOptions,
    originContinents:   continentOptions,
    destContinents:     continentOptions,
    originCountryGroup: countryGroupOptions,
    destCountryGroup:   countryGroupOptions,
    originCountry:      origContinent ? originCountries : allCountries,
    destCountry:        destContinent ? destCountries   : allCountries,
    originAirport:      origCountry   ? originAirports  : allAirports,
    destAirport:        destCountry   ? destAirports    : allAirports,
  };

  type RowField = {
    key: string; label: string;
    isDate?: boolean; isTag?: boolean; isMulti?: "select" | "search";
    placeholder?: string;
  };

  const rows: RowField[][] = [
    [{ key:"validFrom", label:"Valid From", isDate:true }, { key:"validTo", label:"Valid To", isDate:true }],
    [{ key:"continents", label:`Continents ${suffix}`, isMulti:"select" }, { key:"countryGroup", label:`Country Group ${suffix}`, isMulti:"select" }],
    [{ key:"originContinents", label:`Origin Continents ${suffix}`, isMulti:"select" }, { key:"destContinents", label:`Destination Continents ${suffix}`, isMulti:"select" }],
    [{ key:"originCountryGroup", label:`Origin Country Group ${suffix}`, isMulti:"select" }, { key:"destCountryGroup", label:`Destination Country Group ${suffix}`, isMulti:"select" }],
    [
      { key:"originCountry", label:`Origin Country ${suffix}`, isMulti:"search", placeholder: "Search and select" },
      { key:"destCountry",   label:`Destination Country ${suffix}`, isMulti:"search", placeholder: "Search and select" },
    ],
    [
      { key:"originAirport", label:`Origin Airport ${suffix}`, isMulti:"search", placeholder: "Search and select" },
      { key:"destAirport",   label:`Destination Airport ${suffix}`, isMulti:"search", placeholder: "Search and select" },
    ],
    [{ key:"city", label:`City ${suffix}`, isMulti:"search" }, { key:"fareTypeCategory", label:`Fare Type Category ${suffix}`, isMulti:"select" }],
    [
      { key:"class", label:`Class ${suffix}`, isMulti:"select" },
      isExclusion
        ? { key:"soto", label:"SOTO for Exclusion", isMulti:"select" }
        : { key:"tourCode", label:`Tour Code ${suffix}`, isTag:true },
    ],
    ...(isExclusion
      ? [[{ key:"tourCode", label:`Tour Code ${suffix}`, isTag:true } as RowField, { key:"domesticCountry", label:`Domestic Country ${suffix}`, isMulti:"search" as const } as RowField]]
      : [[{ key:"domesticCountry", label:`Domestic Country ${suffix}`, isMulti:"search" as const } as RowField]]),
  ];

  const dateExclusionValues = [
    ...(data["dateExclusionTicket"] === "true" ? ["Ticket Date"] : []),
    ...(data["dateExclusionTravel"] === "true" ? ["Travel Date"] : []),
  ];
  const handleDateExclusionChange = (selected: string[]) => {
    onChange("dateExclusionTicket", selected.includes("Ticket Date") ? "true" : "");
    onChange("dateExclusionTravel", selected.includes("Travel Date") ? "true" : "");
  };

  return (
    <div className="px-4 py-3 space-y-3">
      <div className="grid gap-3 grid-cols-1 max-w-[50%]">
        <MultiCheckboxDropdown
          label="Date Exclusion"
          placeholder="Select date exclusion"
          options={["Ticket Date", "Travel Date"]}
          values={dateExclusionValues}
          onChange={handleDateExclusionChange}
        />
      </div>
      {rows.map((pair, ri) => (
          <div key={ri} className={`grid gap-3 ${pair.length === 2 ? "grid-cols-2" : "grid-cols-1 max-w-[50%]"}`}>
            {pair.map(f => (
              <div key={f.key}>
                {f.isDate
                  ? <DateField label={f.label} value={(data[f.key] as string) ?? ""} onChange={v => onChange(f.key, v)}/>
                  : f.isTag
                    ? <TagInput label={f.label} values={asArray(data[f.key])} onChange={v => onChange(f.key, v)}/>
                    : f.isMulti === "select"
                      ? <MultiCheckboxDropdown label={f.label} options={localOptions[f.key]??[]} values={asArray(data[f.key])} onChange={v => onChange(f.key, v)}/>
                      : <MultiSearchSelectField label={f.label} placeholder={f.placeholder} options={localOptions[f.key]??[]} values={asArray(data[f.key])} onChange={v => onChange(f.key, v)}/>
                }
              </div>
            ))}
          </div>
        ))}
      <label className="flex items-center gap-2 cursor-pointer pt-1">
        <input type="checkbox" checked={viceVersa} onChange={onViceVersa} className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
        <span className="text-xs text-gray-600">Select this option if the route is vice versa.</span>
      </label>
    </div>
  );
}

// ── shared: repository-shaped incentive entry → flat form data ───────────────
// Mirrors the upload/create conversion: drops the `slabs[]` array into the
// amountSlabs / segmentSlabs / siSlabs JSON strings the SlabGrid expects, routed
// by slabType so Segment Incentive rows are not lost.
export function incentiveEntryToForm(entry: Record<string, unknown>): Record<string, string> {
  const form: Record<string, string> = {};
  for (const [k, v] of Object.entries(entry ?? {})) {
    if (k === "slabs") continue;
    if (v !== null && v !== undefined && !Array.isArray(v) && typeof v !== "object") form[k] = String(v);
  }
  const slabs = entry?.["slabs"] as Array<Record<string, unknown>> | undefined;
  if (slabs && slabs.length > 0) {
    const groups: Record<string, Record<string, string>[]> = { amount: [], segment: [], si: [] };
    slabs.forEach((s, i) => {
      const row: Record<string, string> = { id: `r${i}` };
      if (s.quarterlyFreq)       row.quarterlyFreq = String(s.quarterlyFreq);
      if (s.halfYearlyFreq)      row.halfYearlyFreq = String(s.halfYearlyFreq);
      if (s.baseTargetAmtNumPct) row.baseTargetNumPct = String(s.baseTargetAmtNumPct);
      if (s.baseTargetAmount)    row.baseTargetAmount = String(s.baseTargetAmount);
      if (s.targetFrom)          row.targetFrom = String(s.targetFrom);
      if (s.targetTo)            row.targetTo = String(s.targetTo);
      if (s.segment)             row.segment = String(s.segment);
      if (s.class)               row.class = String(s.class);
      for (const [k, v] of Object.entries((s.values as Record<string, unknown>) ?? {})) row[k] = v != null ? String(v) : "";
      const st = String(s.slabType ?? "amount").toLowerCase();
      (groups[st] ?? groups.amount).push(row);
    });
    if (groups.amount.length && !form.amountSlabs)   form.amountSlabs = JSON.stringify(groups.amount);
    if (groups.segment.length && !form.segmentSlabs) form.segmentSlabs = JSON.stringify(groups.segment);
    if (groups.si.length && !form.siSlabs)           form.siSlabs = JSON.stringify(groups.si);
  }
  return form;
}

// ── shared: combined Incentive + Incl/Excl editor (repository) ───────────────
// One tab per incentive type. Each tab shows that incentive's payout fields AND
// its 4 inclusion/exclusion rule sub-tabs, so everything for an incentive is edited
// in one place. onSave receives form-shaped incentive_data and per-incentive
// incl_excl_data ({inc: {ruleType: conditions}}) for a single PATCH.
export function IncentiveRulesModal({
  incentiveTypes, incentiveData, inclExclData, initialIncType, onSave, onClose,
}: {
  incentiveTypes: string[];
  incentiveData: Record<string, Record<string, unknown>>;
  inclExclData: Record<string, Record<string, Record<string, IEFieldValue>>>;
  initialIncType?: string;
  onSave: (
    incentiveData: Record<string, Record<string, string>>,
    inclExclData: Record<string, Record<string, Record<string, IEFieldValue>>>,
  ) => Promise<void>;
  onClose: () => void;
}) {
  const [incForms, setIncForms] = useState<Record<string, Record<string, string>>>(() => {
    const init: Record<string, Record<string, string>> = {};
    for (const t of incentiveTypes) init[t] = incentiveEntryToForm(incentiveData[t] ?? {});
    return init;
  });
  const [ieForms, setIeForms] = useState<Record<string, Record<string, Record<string, IEFieldValue>>>>(() => {
    const init: Record<string, Record<string, Record<string, IEFieldValue>>> = {};
    for (const t of incentiveTypes) {
      init[t] = {};
      const d = inclExclData[t] ?? {};
      for (const rt of INCLUSIONS_EXCLUSIONS) init[t][rt] = { ...(d[rt] ?? {}) };
    }
    return init;
  });
  const [activeInc, setActiveInc] = useState(initialIncType && incentiveTypes.includes(initialIncType) ? initialIncType : (incentiveTypes[0] ?? ""));
  const [activeRule, setActiveRule] = useState(INCLUSIONS_EXCLUSIONS[0]);
  const [saving, setSaving] = useState(false);

  const [continentOptions, setContinentOptions] = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);
  useEffect(() => {
    api.get<{ continents: string[]; country_groups: string[] }>("/airports/options")
      .then(r => { if (r.data.continents?.length) setContinentOptions(r.data.continents); if (r.data.country_groups?.length) setCountryGroupOptions(r.data.country_groups); })
      .catch(() => {});
  }, []);

  const inc = incentiveTypes.includes(activeInc) ? activeInc : (incentiveTypes[0] ?? "");
  const isExclusion = activeRule.startsWith("Exclusion");
  const ieSuffix = isExclusion ? "for Exclusion" : "for Inclusion";
  const ruleData = ieForms[inc]?.[activeRule] ?? {};

  const setIncField = (k: string, v: string) => setIncForms(p => ({ ...p, [inc]: { ...(p[inc] ?? {}), [k]: v } }));
  const setIeField = (k: string, v: IEFieldValue) =>
    setIeForms(p => ({ ...p, [inc]: { ...(p[inc] ?? {}), [activeRule]: { ...(p[inc]?.[activeRule] ?? {}), [k]: v } } }));
  const toggleViceVersa = () => setIeField("viceVersa", ruleData["viceVersa"] === "true" ? "" : "true");

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(incForms, ieForms); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Incentive &amp; Rules</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Per incentive type: payout details and its inclusion / exclusion rules, all in one place.</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        {incentiveTypes.length === 0 ? (
          <p className="px-5 py-8 text-xs text-gray-400 text-center">This deal has no incentive types.</p>
        ) : (
          <>
            <TabBar tabs={incentiveTypes} active={inc} onSelect={setActiveInc} />
            <div className="overflow-y-auto flex-1">
              <IncentiveTabContent name={inc} data={incForms[inc] ?? {}} onChange={setIncField} />
              <div className="border-t border-gray-100 mt-1 pt-3">
                <h3 className="px-4 text-[11px] font-bold text-gray-500 uppercase tracking-wide">Inclusion / Exclusion Rules</h3>
                <div className="px-4 mt-2">
                  <div className="flex gap-1 border-b border-gray-100 flex-wrap">
                    {INCLUSIONS_EXCLUSIONS.map(rt => {
                      const has = Object.keys(ieForms[inc]?.[rt] ?? {}).some(k => k !== "viceVersa" && (ieForms[inc]?.[rt]?.[k] as IEFieldValue)?.length);
                      return (
                        <button key={rt} type="button" onClick={() => setActiveRule(rt)}
                          className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap ${activeRule === rt ? "border-[#1e3a5f] text-[#1e3a5f]" : "border-transparent text-gray-400 hover:text-gray-600"}`}>
                          {rt}{has && <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 align-middle" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <InclExclTabContent
                  key={`${inc}:${activeRule}`}
                  suffix={ieSuffix}
                  isExclusion={isExclusion}
                  data={ruleData}
                  onChange={setIeField}
                  viceVersa={ruleData["viceVersa"] === "true"}
                  onViceVersa={toggleViceVersa}
                  continentOptions={continentOptions}
                  countryGroupOptions={countryGroupOptions}
                />
              </div>
            </div>
          </>
        )}
        <div className="px-5 pb-4 pt-3 border-t border-gray-100 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Check className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save Changes"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}
