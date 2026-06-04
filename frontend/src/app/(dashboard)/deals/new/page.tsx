"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, X, ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

// ── static options ─────────────────────────────────────────────────────────
const CONTRACT_YEARS   = ["Calendar year", "Financial year"];
const TRIGGER_TYPES    = ["Flown", "Sales"];
const PAYOUT_TYPES     = ["Flown", "Sales"];
const ENTITIES         = ["ATB", "TSI", "YOL"];
const IATA_NUMBERS     = ["12345678", "87654321", "11223344", "44332211"];
const BUSINESS_TYPES   = ["B2B", "B2C", "B2E", "MICE"];
const LOGIN_IDS        = ["AGENT001", "AGENT002", "AGENT003", "AGENT004"];

const INCENTIVE_TYPES = [
  "PLB","Super PLB","Transaction Fee",
  "Deposit Incentive (DI)","Marketing Fund","Ancillary",
  "Frontend","Backend","Cashback",
  "Segment Incentive","Push Action",
];

const FREQUENCY_OPTIONS    = ["Quarterly","Half Yearly","Yearly"];
const FLIGHT_TYPE_OPTIONS  = ["International","Domestic","Both"];
const CLASS_OPTIONS        = ["All","Economy","Premium","Business"];
const TARGET_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
const PAYOUT_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
const TARGET_BASED_OPTIONS = ["Amount Based","Segment Based"];

type FieldConfig = {
  key: string; label: string;
  type: "date"|"select"|"search"|"number";
  condition?: { field: string; value: string };
};

function payoutFields(n: string): FieldConfig[] {
  return [
    { key:"amountBasedType",    label:`Amount Based for ${n}`,                   type:"select", condition:{field:"targetBased", value:"Amount Based"} },
    { key:"baseTargetAmount",   label:`Base Target Amount for ${n}`,             type:"number", condition:{field:"targetBased", value:"Amount Based"} },
    { key:"segmentBasedType",   label:`Segment Based for ${n}`,                  type:"select", condition:{field:"targetBased", value:"Segment Based"} },
    { key:"baseTargetSegments", label:`Base Target Segments for ${n}`,           type:"number", condition:{field:"targetBased", value:"Segment Based"} },
    { key:"incentiveNumPct",    label:`Incentive in Number or Percentage for ${n}`, type:"select", condition:{field:"targetBased", value:"__set__"} },
    { key:"incentiveAmtPct",    label:`Incentive Percentage or Amount for ${n}`, type:"number", condition:{field:"targetBased", value:"__set__"} },
    { key:"cappedIncentive",    label:`Capped Incentive for ${n}`,               type:"number", condition:{field:"targetBased", value:"__set__"} },
  ];
}
function payoutCalcFields(n: string): FieldConfig[] {
  return [
    { key:"incentiveNumPct", label:`Incentive in Number or Percentage for ${n}`, type:"select", condition:{field:"payoutCalcCols", value:"__set__"} },
    { key:"incentiveAmtPct", label:`Incentive Percentage or Amount for ${n}`,    type:"number", condition:{field:"payoutCalcCols", value:"__set__"} },
    { key:"cappedIncentive", label:`Capped Incentive for ${n}`,                  type:"number", condition:{field:"payoutCalcCols", value:"__set__"} },
  ];
}

const INCENTIVE_FIELDS: Record<string, FieldConfig[]> = {
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
    { key:"validFrom",      label:"Contract Valid from for Super PLB", type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Super PLB",   type:"date"   },
    { key:"frequency",      label:"Frequency for Super PLB",           type:"select" },
    { key:"flightType",     label:"Flight Type for Super PLB",         type:"select" },
    { key:"class",          label:"Class for Super PLB",               type:"search" },
    { key:"targetBased",    label:"Target Based for Super PLB",        type:"select" },
    { key:"targetCalcCols", label:"Target Calc Columns for Super PLB", type:"select" },
    ...payoutFields("Super PLB"),
  ],
  "Transaction Fee": [
    { key:"validFrom",      label:"Contract Valid from for Transaction Fee", type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Transaction Fee",   type:"date"   },
    { key:"frequency",      label:"Frequency for Transaction Fee",           type:"select" },
    { key:"flightType",     label:"Flight Type for Transaction Fee",         type:"select" },
    { key:"class",          label:"Class for Transaction Fee",               type:"search" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Transaction Fee", type:"select" },
    ...payoutCalcFields("Transaction Fee"),
  ],
  "Deposit Incentive (DI)": [
    { key:"validFrom",   label:"Contract Valid from for DI", type:"date"   },
    { key:"validTo",     label:"Contract Valid to for DI",   type:"date"   },
    { key:"frequency",   label:"Frequency for DI",           type:"select" },
    { key:"flightType",  label:"Flight Type for DI",         type:"select" },
    { key:"targetBased", label:"Target Based for DI",        type:"select" },
    ...payoutFields("Deposit Incentive (DI)"),
  ],
  "Marketing Fund": [
    { key:"validFrom",      label:"Contract Valid from for Marketing Fund", type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Marketing Fund",   type:"date"   },
    { key:"frequency",      label:"Frequency for Marketing Fund",           type:"select" },
    { key:"flightType",     label:"Flight Type for Marketing Fund",         type:"select" },
    { key:"class",          label:"Class for Marketing Fund",               type:"search" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Marketing Fund", type:"select" },
    ...payoutCalcFields("Marketing Fund"),
  ],
  "Ancillary": [
    { key:"validFrom",      label:"Contract Valid from for Ancillary", type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Ancillary",   type:"date"   },
    { key:"flightType",     label:"Flight Type for Ancillary",         type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Ancillary", type:"select" },
    ...payoutCalcFields("Ancillary"),
  ],
  "Frontend": [
    { key:"validFrom",      label:"Contract Valid from for Frontend",  type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Frontend",    type:"date"   },
    { key:"frequency",      label:"Frequency for Frontend",            type:"select" },
    { key:"class",          label:"Class for Frontend",                type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Frontend",  type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Frontend",  type:"select" },
    ...payoutCalcFields("Frontend"),
  ],
  "Backend": [
    { key:"validFrom",      label:"Contract Valid from for Backend",   type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Backend",     type:"date"   },
    { key:"frequency",      label:"Frequency for Backend",             type:"select" },
    { key:"class",          label:"Class for Backend",                 type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Backend",   type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Backend",   type:"select" },
    ...payoutCalcFields("Backend"),
  ],
  "Cashback": [
    { key:"validFrom",   label:"Contract Valid from for Cashback", type:"date"   },
    { key:"validTo",     label:"Contract Valid to for Cashback",   type:"date"   },
    { key:"frequency",   label:"Frequency for Cashback",           type:"select" },
    { key:"flightType",  label:"Flight Type for Cashback",         type:"select" },
    { key:"targetBased", label:"Target Based for Cashback",        type:"select" },
    ...payoutFields("Cashback"),
  ],
  "Segment Incentive": [
    { key:"validFrom",      label:"Contract Valid from for Segment Incentive", type:"date"   },
    { key:"validTo",        label:"Contract Valid to for Segment Incentive",   type:"date"   },
    { key:"frequency",      label:"Frequency for Segment Incentive",           type:"select" },
    { key:"class",          label:"Class for Segment Incentive",               type:"search" },
    { key:"targetCalcCols", label:"Target Calc Columns for Segment Incentive", type:"select" },
    { key:"payoutCalcCols", label:"Payout Calc Columns for Segment Incentive", type:"select" },
    ...payoutCalcFields("Segment Incentive"),
  ],
  "Push Action": [
    { key:"validFrom",   label:"Contract Valid from for Push Action", type:"date"   },
    { key:"validTo",     label:"Contract Valid to for Push Action",   type:"date"   },
    { key:"frequency",   label:"Frequency for Push Action",           type:"select" },
    { key:"flightType",  label:"Flight Type for Push Action",         type:"select" },
    { key:"targetBased", label:"Target Based for Push Action",        type:"select" },
    ...payoutFields("Push Action"),
  ],
};

const INCLUSIONS_EXCLUSIONS = [
  "Inclusion For Trigger",
  "Exclusion For Trigger",
  "Inclusion For Payout",
  "Exclusion For Payout",
];

const CONTINENTS         = ["Africa","Asia","Europe","North America","Oceania","South America","Antarctica"];
const COUNTRY_GROUPS     = ["APAC","EUROPEAN NATIONS","GCC/MIDDLE EAST","LATIN AMERICA","MEAI","MEAI/APAC","MEAI/SAARC","MEAI/SAARC/APAC","NAM","OTHER","SAARC","SAARC/APAC"];
const COUNTRIES          = ["India","UAE","Saudi Arabia","Qatar","UK","Germany","USA","Singapore","Australia"];
const AIRPORTS           = ["DEL","BOM","DXB","DOH","LHR","FRA","JFK","SIN","SYD"];
const CITIES             = ["Delhi","Mumbai","Dubai","Doha","London","Frankfurt","New York","Singapore","Sydney"];
const FARE_TYPE_CATS     = ["Normal","Group","Corporate","Excursion","Tour"];
const TOUR_CODES         = ["TC001","TC002","TC003","TC004"];
const DOMESTIC_CTRS      = ["India","UAE","UK","USA","Australia"];
const SOTO_OPTIONS       = ["SOTO All","SOTO within India","SOTO outside India  "];
const INCL_CLASS_OPTIONS = ["All","Economy","Premium Economy","Business","First"];

const FIELD_OPTIONS: Record<string, string[]> = {
  frequency:        FREQUENCY_OPTIONS,
  flightType:       FLIGHT_TYPE_OPTIONS,
  targetCalcCols:   TARGET_CALC_OPTIONS,
  payoutCalcCols:   PAYOUT_CALC_OPTIONS,
  targetBased:      TARGET_BASED_OPTIONS,
  amountBasedType:  ["Fixed", "Slab Based"],
  segmentBasedType: ["Fixed", "Slab Based"],
  incentiveNumPct:  ["Number", "Percentage"],
};

const INCL_EXCL_SEARCH_OPTIONS: Record<string, string[]> = {
  continents: CONTINENTS, countryGroup: COUNTRY_GROUPS,
  originContinents: CONTINENTS, destContinents: CONTINENTS,
  originCountryGroup: COUNTRY_GROUPS, destCountryGroup: COUNTRY_GROUPS,
  originCountry: COUNTRIES, destCountry: COUNTRIES,
  originAirport: AIRPORTS, destAirport: AIRPORTS,
  city: CITIES, fareTypeCategory: FARE_TYPE_CATS,
  class: INCL_CLASS_OPTIONS, tourCode: TOUR_CODES,
  domesticCountry: DOMESTIC_CTRS,
};

// ── compact select ─────────────────────────────────────────────────────────
function SelectField({ label, placeholder="Select...", options, value, onChange }: {
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
function SearchSelectField({ label, placeholder="Search and select", options, value, onChange }: {
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
function MultiCheckboxDropdown({ label, placeholder="Select...", options, values, onChange }: {
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

// ── date input ─────────────────────────────────────────────────────────────
function DateField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
      <input type="text" placeholder="Enter date" value={value}
        onFocus={e => (e.target.type = "date")}
        onBlur={e => { if (!e.target.value) e.target.type = "text"; }}
        onChange={e => onChange(e.target.value)}
        className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
    </div>
  );
}

// ── tab bar ────────────────────────────────────────────────────────────────
function TabBar({ tabs, active, onSelect, onRemove }: {
  tabs: string[]; active: string;
  onSelect: (t: string) => void;
  onRemove: (t: string) => void;
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
          <span onClick={e => { e.stopPropagation(); onRemove(t); }}
            className="ml-0.5 text-gray-300 hover:text-red-400 leading-none">
            <X className="w-3 h-3"/>
          </span>
        </div>
      ))}
    </div>
  );
}

// ── incentive tab content ──────────────────────────────────────────────────
function IncentiveTabContent({ name, data, onChange }: {
  name: string; data: Record<string, string>; onChange: (k: string, v: string) => void;
}) {
  const allFields = INCENTIVE_FIELDS[name] ?? [];

  const visible = allFields.filter(f => {
    if (!f.condition) return true;
    const actual = data[f.condition.field] ?? "";
    if (f.condition.value === "__set__") return actual !== "";
    return actual === f.condition.value;
  });

  const rows: FieldConfig[][] = [];
  for (let i = 0; i < visible.length; i += 2) rows.push(visible.slice(i, i + 2));

  const renderField = (f: FieldConfig) => {
    if (f.type === "date")
      return <DateField label={f.label} value={data[f.key]??""} onChange={v => onChange(f.key, v)}/>;
    if (f.type === "number")
      return (
        <div>
          <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{f.label}</label>
          <input type="number" placeholder="Enter number" value={data[f.key]??""} onChange={e => onChange(f.key, e.target.value)}
            className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
        </div>
      );
    if (f.type === "search")
      return <SearchSelectField label={f.label} options={CLASS_OPTIONS} value={data[f.key]??""} onChange={v => onChange(f.key, v)}/>;
    return <SelectField label={f.label} options={FIELD_OPTIONS[f.key]??[]} value={data[f.key]??""} onChange={v => onChange(f.key, v)}/>;
  };

  return (
    <div className="px-4 py-3 space-y-3">
      {rows.map((pair, ri) => (
        <div key={ri} className={`grid gap-3 ${pair.length === 2 ? "grid-cols-2" : "grid-cols-1 max-w-[50%]"}`}>
          {pair.map(f => <div key={f.key}>{renderField(f)}</div>)}
        </div>
      ))}
    </div>
  );
}

// ── incl/excl tab content ──────────────────────────────────────────────────
function InclExclTabContent({ suffix, isExclusion, data, onChange, viceVersa, onViceVersa, continentOptions, countryGroupOptions }: {
  suffix: string; isExclusion: boolean;
  data: Record<string, string>; onChange: (k: string, v: string) => void;
  viceVersa: boolean; onViceVersa: () => void;
  continentOptions: string[]; countryGroupOptions: string[];
}) {
  const [originCountries, setOriginCountries] = useState<string[]>([]);
  const [destCountries,   setDestCountries]   = useState<string[]>([]);
  const [originAirports,  setOriginAirports]  = useState<string[]>([]);
  const [destAirports,    setDestAirports]    = useState<string[]>([]);
  const [allCountries,    setAllCountries]    = useState<string[]>([]);
  const [allAirports,     setAllAirports]     = useState<string[]>([]);

  const origContinent = data["originContinents"] ?? "";
  const destContinent = data["destContinents"]   ?? "";
  const origCountry   = data["originCountry"]    ?? "";
  const destCountry   = data["destCountry"]      ?? "";

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

  const handleChange = (k: string, v: string) => {
    onChange(k, v);
  };

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

  const rows: { key: string; label: string; isSelect?: boolean; isDate?: boolean; options?: string[]; placeholder?: string }[][] = [
    [{ key:"validFrom", label:"Valid From", isDate:true }, { key:"validTo", label:"Valid To", isDate:true }],
    [{ key:"continents", label:`Continents ${suffix}` }, { key:"countryGroup", label:`Country Group ${suffix}` }],
    [{ key:"originContinents", label:`Origin Continents ${suffix}` }, { key:"destContinents", label:`Destination Continents ${suffix}` }],
    [{ key:"originCountryGroup", label:`Origin Country Group ${suffix}` }, { key:"destCountryGroup", label:`Destination Country Group ${suffix}` }],
    [
      { key:"originCountry", label:`Origin Country ${suffix}`, placeholder: "Search and select" },
      { key:"destCountry",   label:`Destination Country ${suffix}`, placeholder: "Search and select" },
    ],
    [
      { key:"originAirport", label:`Origin Airport ${suffix}`, placeholder: "Search and select" },
      { key:"destAirport",   label:`Destination Airport ${suffix}`, placeholder: "Search and select" },
    ],
    [{ key:"city", label:`City ${suffix}` }, { key:"fareTypeCategory", label:`Fare Type Category ${suffix}` }],
    [
      { key:"class", label:`Class ${suffix}` },
      isExclusion
        ? { key:"soto", label:"SOTO for Exclusion", isSelect:true, options:SOTO_OPTIONS }
        : { key:"tourCode", label:`Tour Code ${suffix}` },
    ],
    ...(isExclusion
      ? [[{ key:"tourCode", label:`Tour Code ${suffix}` }, { key:"domesticCountry", label:`Domestic Country ${suffix}` }]]
      : [[{ key:"domesticCountry", label:`Domestic Country ${suffix}` }]]),
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
                  ? <DateField label={f.label} value={data[f.key]??""} onChange={v => handleChange(f.key, v)}/>
                  : f.isSelect
                    ? <SelectField label={f.label} options={f.options??[]} value={data[f.key]??""} onChange={v => handleChange(f.key, v)}/>
                    : <SearchSelectField label={f.label} placeholder={f.placeholder} options={localOptions[f.key]??[]} value={data[f.key]??""} onChange={v => handleChange(f.key, v)}/>
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

// ── section card wrapper ───────────────────────────────────────────────────
function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200">
      <div className="px-4 py-2.5 border-b border-gray-100">
        <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">{title}</h2>
      </div>
      {children}
    </div>
  );
}

// ── deal type selection screen ─────────────────────────────────────────────
type WorkflowPreviewStep = { step_order: number; role: string; approvers: { id: number; full_name: string; email: string }[] };

function DealTypeSelector({
  onSelect,
}: {
  onSelect: (t: "airline" | "b2b", c: "proprietary" | "enterprise") => void;
}) {
  const [selectedType, setSelectedType] = useState<"airline" | "b2b" | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<"proprietary" | "enterprise">("enterprise");
  const [workflowPreview, setWorkflowPreview] = useState<WorkflowPreviewStep[] | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    if (selectedCategory !== "enterprise") { setWorkflowPreview(null); return; }
    setLoadingPreview(true);
    api.get<WorkflowPreviewStep[]>("/approval-workflows/deals-preview")
      .then(r => setWorkflowPreview(r.data))
      .catch(() => setWorkflowPreview([]))
      .finally(() => setLoadingPreview(false));
  }, [selectedCategory]);

  return (
    <>
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-10 w-full max-w-md">
          <h1 className="text-base font-semibold text-gray-800 mb-1"> Deal Deatils</h1>
          <p className="text-xs text-gray-400 mb-6">Choose the type of deal you want to create.</p>

          {/* ── Deal Category ── */}
          <p className="text-xs font-semibold text-gray-700 mb-2">Deal Category</p>
          <div className="flex gap-2 mb-2">
            {([
              { value: "enterprise"  as const, label: "Enterprise"  },
              { value: "proprietary" as const, label: "Proprietary" },
            ] as const).map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setSelectedCategory(opt.value)}
                className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-semibold transition-all ${
                  selectedCategory === opt.value
                    ? "border-[#1e3a5f] bg-[#1e3a5f] text-white"
                    : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                }`}
              >
                <span className={`w-3 h-3 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                  selectedCategory === opt.value ? "border-white" : "border-gray-400"
                }`}>
                  {selectedCategory === opt.value && <span className="w-1.5 h-1.5 rounded-full bg-white block" />}
                </span>
                {opt.label}
              </button>
            ))}
          </div>
          {selectedCategory === "proprietary" && (
            <p className="text-[10px] text-gray-400 mb-5">Deal will be auto-approved, bypassing the approval workflow.</p>
          )}
          {selectedCategory === "enterprise" && (
            <div className="flex items-center justify-between mb-5">
              <p className="text-[10px] text-gray-400">Deal will follow the approval workflow.</p>
              <button type="button" onClick={() => setModalOpen(true)}
                className="text-[10px] font-semibold text-[#1e3a5f] hover:underline flex-shrink-0 ml-2">
                See workflow →
              </button>
            </div>
          )}

          {/* ── Deal Type ── */}
          <p className="text-xs font-semibold text-gray-700 mb-2">Deal Type</p>
          <div className="flex flex-col gap-3 mb-6">
            {(["airline", "b2b"] as const).map(type => (
              <label key={type}
                className={`flex items-center gap-3 border rounded-lg px-4 py-3.5 cursor-pointer transition-colors ${
                  selectedType === type
                    ? "border-blue-500 bg-blue-50/60"
                    : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
                }`}>
                <input
                  type="radio"
                  name="dealType"
                  value={type}
                  checked={selectedType === type}
                  onChange={() => setSelectedType(type)}
                  className="w-4 h-4 accent-blue-600"
                />
                <div>
                  <span className="text-sm font-medium text-gray-800">
                    {type === "airline" ? "Airline" : "B2B"}
                  </span>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    {type === "airline"
                      ? "Airline contract with full incentive and payout details"
                      : "B2B deal without contract year, trigger type or payout type"}
                  </p>
                </div>
              </label>
            ))}
          </div>

          {/* Continue */}
          <button
            type="button"
            disabled={!selectedType}
            onClick={() => selectedType && onSelect(selectedType, selectedCategory)}
            className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
            Continue →
          </button>
        </div>
      </div>

      {/* Workflow preview modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setModalOpen(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-bold text-gray-900">Approval Workflow</h2>
                <p className="text-xs text-gray-400 mt-0.5">Steps your deal will go through before approval</p>
              </div>
              <button onClick={() => setModalOpen(false)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="px-5 py-4">
              {loadingPreview && (
                <div className="flex items-center gap-2 text-sm text-gray-400 py-6 justify-center">
                  <span className="w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
                  <span>Loading workflow…</span>
                </div>
              )}
              {!loadingPreview && (!workflowPreview || workflowPreview.length === 0) && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
                  <p className="text-xs text-amber-700">No approval workflow configured. Ask your Super Admin to set one up.</p>
                </div>
              )}
              {!loadingPreview && workflowPreview && workflowPreview.length > 0 && (
                <div>
                  {workflowPreview.map((s, i) => (
                    <div key={s.step_order} className="flex gap-4 pb-5 last:pb-0">
                      <div className="flex flex-col items-center">
                        <span className="w-7 h-7 rounded-full bg-[#1e3a5f] text-white flex items-center justify-center text-xs font-bold flex-shrink-0">{s.step_order}</span>
                        {i < workflowPreview.length - 1 && <span className="flex-1 w-px bg-gray-200 mt-1" />}
                      </div>
                      <div className="flex-1 pt-0.5">
                        <p className="text-xs font-semibold text-gray-800 capitalize">{s.role.replace(/_/g, " ")}</p>
                        {s.approvers.length > 0 ? (
                          <div className="mt-1.5 space-y-1">
                            {s.approvers.map(a => (
                              <div key={a.id} className="flex items-center gap-2">
                                <span className="w-5 h-5 rounded-full bg-blue-100 text-[#1e3a5f] flex items-center justify-center text-[10px] font-bold flex-shrink-0">
                                  {a.full_name.charAt(0).toUpperCase()}
                                </span>
                                <div>
                                  <p className="text-[11px] font-medium text-gray-700">{a.full_name}</p>
                                  <p className="text-[10px] text-gray-400">{a.email}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[11px] text-gray-400 mt-1">No approvers assigned</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
              <button onClick={() => setModalOpen(false)} className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-[#1e3a5f] text-white hover:bg-[#16304f]">Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function NewDealPage() {
  const router = useRouter();

  const [dealType, setDealType]         = useState<"airline" | "b2b" | null>(null);
  const [dealCategory, setDealCategory] = useState<"proprietary" | "enterprise">("enterprise");

  // airline contract
  const [airlineType, setAirlineType]     = useState("");
  const [airlineName, setAirlineName]     = useState("");
  const [contractYear, setContractYear]   = useState("");
  const [validFrom, setValidFrom]         = useState("");
  const [validTo, setValidTo]             = useState("");
  const [triggerType, setTriggerType]     = useState("");
  const [payoutType, setPayoutType]       = useState("");
  const [entity, setEntity]               = useState("");
  const [iataNumber, setIataNumber]       = useState("");
  const [businessType, setBusinessType]   = useState("");
  const [entityLCC, setEntityLCC]         = useState("");
  const [loginId, setLoginId]             = useState("");

  // incentives
  const [incentives, setIncentives]   = useState<Record<string, boolean>>({});
  const [activeIncentiveTab, setActiveIncentiveTab] = useState("");
  const [incentiveData, setIncentiveData] = useState<Record<string, Record<string, string>>>({});

  const toggleIncentive = (key: string) => {
    setIncentives(p => {
      const next = { ...p, [key]: !p[key] };
      if (!p[key]) setActiveIncentiveTab(key);
      else {
        const remaining = INCENTIVE_TYPES.filter(t => t !== key && next[t]);
        setActiveIncentiveTab(remaining[remaining.length - 1] ?? "");
      }
      return next;
    });
  };
  const setIncentiveField = (inc: string, k: string, v: string) =>
    setIncentiveData(p => ({ ...p, [inc]: { ...(p[inc]??{}), [k]: v } }));

  // inclusions / exclusions
  const [inclExcl, setInclExcl]     = useState<Record<string, boolean>>({});
  const [activeInclExclTab, setActiveInclExclTab] = useState("");
  const [inclExclData, setInclExclData] = useState<Record<string, Record<string, string>>>({});
  const [viceVersa, setViceVersa]   = useState<Record<string, boolean>>({});

  const toggleInclExcl = (key: string) => {
    setInclExcl(p => {
      const next = { ...p, [key]: !p[key] };
      if (!p[key]) setActiveInclExclTab(key);
      else {
        const remaining = INCLUSIONS_EXCLUSIONS.filter(t => t !== key && next[t]);
        setActiveInclExclTab(remaining[remaining.length - 1] ?? "");
      }
      return next;
    });
  };
  const setInclExclField = (sec: string, k: string, v: string) =>
    setInclExclData(p => ({ ...p, [sec]: { ...(p[sec]??{}), [k]: v } }));
  const toggleViceVersa = (sec: string) =>
    setViceVersa(p => ({ ...p, [sec]: !p[sec] }));

  // file / other
  const [file, setFile]             = useState<File | null>(null);
  const fileRef                     = useRef<HTMLInputElement>(null);
  const [remark, setRemark]         = useState("");
  const [dealMakerName, setDealMakerName] = useState("");

  const [airlineOptions, setAirlineOptions] = useState<string[]>([]);
  const [loadingAirlines, setLoadingAirlines] = useState(false);

  const [supplierName, setSupplierName]       = useState("");
  const [supplierOptions, setSupplierOptions] = useState<string[]>([]);

  const [continentOptions, setContinentOptions] = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);

  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then(r => setSupplierOptions(r.data.map(s => s.name)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    api.get<{ continents: string[]; country_groups: string[] }>("/airports/options")
      .then(({ data }) => {
        if (data.continents?.length)     setContinentOptions(data.continents);
        if (data.country_groups?.length) setCountryGroupOptions(data.country_groups);
      })
      .catch(() => {});
  }, []);

  const fetchAirlinesByType = async (type: string) => {
    if (!type) { setAirlineOptions([]); return; }
    setLoadingAirlines(true);
    try {
      const { data } = await api.get<string[]>(`/classes/airlines-by-type/${type}`);
      setAirlineOptions(data);
    } catch {
      setAirlineOptions([]);
    } finally {
      setLoadingAirlines(false);
    }
  };

  const selectedIncentives = INCENTIVE_TYPES.filter(t => incentives[t]);
  const selectedInclExcl   = INCLUSIONS_EXCLUSIONS.filter(t => inclExcl[t]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f && f.type === "application/pdf") setFile(f);
  };

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const handleSubmit = async () => {
    if(!airlineType) {
      toast.error("Please select Airline Type.");
      return;
    }
    if(!airlineName) {
      toast.error("Please select Airline Name.");
      return;
    }
    if(!validFrom) {
      toast.error("Please enter Valid From date.");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      const endpoint = dealType === "b2b" ? "/deals/manual/b2b" : "/deals/manual/airline";
      const payload: Record<string, unknown> = {
        source_type:    "manual",
        source_agent:   dealMakerName || "manual",
        issue_date:     null,
        notes:          null,
        airline_type:   airlineType,
        airline_name:   airlineName,
        valid_from:     validFrom,
        valid_to:       validTo,
        entity:         airlineType === "GDS" ? (entity      || null) : null,
        iata_number:    airlineType === "GDS" ? (iataNumber  || null) : null,
        business_type:  airlineType === "LCC" ? (businessType|| null) : null,
        entity_lcc:     airlineType === "LCC" ? (entityLCC   || null) : null,
        login_id:       airlineType === "LCC" ? (loginId     || null) : null,
        remark:         remark       || null,
        deal_maker_name: dealMakerName || null,
        deal_category:   dealCategory || "enterprise",
        incentive_types: selectedIncentives,
        incentive_data:  incentiveData,
        incl_excl_types: selectedInclExcl,
        incl_excl_data:  inclExclData,
        vice_versa:      viceVersa,
        column_map:      {},
        rows:            [],
      };
      // airline-only fields
      if (dealType === "airline") {
        payload.contract_year = contractYear || null;
        payload.trigger_type  = triggerType  || null;
        payload.payout_type   = payoutType   || null;
      }
      // b2b-only fields
      if (dealType === "b2b") {
        payload.supplier_name = supplierName || null;
      }
      await api.post(endpoint, payload);
      router.push("/deals");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(msg ?? "Failed to save deal. Make sure the backend is running.");
    } finally {
      setSubmitting(false);
    }
  };

  const INCL_EXCL_META: Record<string, { title: string; suffix: string; isExclusion: boolean }> = {
    "Inclusion For Trigger": { title:"Inclusion For Trigger", suffix:"for Inclusion", isExclusion:false },
    "Exclusion For Trigger": { title:"Exclusion For Trigger", suffix:"for Exclusion", isExclusion:true  },
    "Inclusion For Payout":  { title:"Inclusion For Payout",  suffix:"for Inclusion", isExclusion:false },
    "Exclusion For Payout":  { title:"Exclusion For Payout",  suffix:"for Exclusion", isExclusion:true  },
  };

  // ── Step 0: deal-type + category selection ──────────────────────────────
  if (dealType === null) {
    return (
      <DealTypeSelector
        onSelect={(t, c) => { setDealType(t); setDealCategory(c); }}
      />
    );
  }

  // ── Step 1: form ─────────────────────────────────────────────────────────
  return (
    <div className="w-full pb-20 space-y-3">

      {/* page header with back link */}
      <div className="flex items-center gap-2 mb-1">
        <button type="button" onClick={() => setDealType(null)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5"/>
          Back
        </button>
        <span className="text-gray-300 text-xs">|</span>
        <h1 className="text-sm font-semibold text-gray-700">
          Create Deal — <span className="text-blue-600">{dealType === "airline" ? "Airline" : "B2B"}</span>
          <span className={`ml-2 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${dealCategory === "proprietary" ? "bg-violet-50 text-violet-700 border-violet-200" : "bg-blue-50 text-blue-700 border-blue-200"}`}>
            {dealCategory === "proprietary" ? "Proprietary" : "Enterprise"}
          </span>
        </h1>
      </div>

      {/* ── Airline Contract Details ──────────────────────────────────── */}
      <SectionCard title="Airline Contract Details">
        <div className="px-4 py-3 grid grid-cols-2 gap-3">
          <SelectField label="Airline Type" options={["GDS","LCC"]} value={airlineType}
            onChange={v => { setAirlineType(v); setAirlineName(""); fetchAirlinesByType(v); }}/>
          <SearchSelectField
            label="Airline Name"
            options={airlineOptions}
            value={airlineName}
            onChange={setAirlineName}
            placeholder={loadingAirlines ? "Loading..." : airlineType ? "Search and select" : "Select airline type first"}
          />

          {/* Supplier Name — B2B only */}
          {dealType === "b2b" && (
            <SearchSelectField
              label="Supplier Name"
              options={supplierOptions}
              value={supplierName}
              onChange={setSupplierName}
              placeholder={supplierOptions.length ? "Search and select supplier" : "Loading suppliers..."}
            />
          )}

          {/* Contract Year — Airline only */}
          {dealType === "airline" && (
            <SelectField label="Contract Year" options={CONTRACT_YEARS} value={contractYear} onChange={setContractYear}/>
          )}
          {airlineType === "LCC"
            ? <SearchSelectField label="Business Type" options={BUSINESS_TYPES} value={businessType} onChange={setBusinessType}/>
            : <div/>}

          <DateField label="Contract Valid From" value={validFrom} onChange={setValidFrom}/>
          <DateField label="Contract Valid To"   value={validTo}   onChange={setValidTo}/>

          {/* Trigger Type + Payout Type — Airline only */}
          {dealType === "airline" && (
            <>
              <SelectField label="Trigger Type" options={TRIGGER_TYPES} value={triggerType} onChange={setTriggerType}/>
              <SelectField label="Payout Type"  options={PAYOUT_TYPES}  value={payoutType}  onChange={setPayoutType}/>
            </>
          )}

          {airlineType === "GDS" && <>
            <SearchSelectField label="Entity"       options={ENTITIES}      value={entity}      onChange={setEntity}/>
            <SearchSelectField label="IATA Number"  options={IATA_NUMBERS}  value={iataNumber}  onChange={setIataNumber}/>
          </>}
          {airlineType === "LCC" && <>
            <SearchSelectField label="Entity for LCC" options={ENTITIES}   value={entityLCC}   onChange={setEntityLCC}/>
            <SearchSelectField label="Login ID"        options={LOGIN_IDS} value={loginId}     onChange={setLoginId}/>
          </>}
        </div>
      </SectionCard>

      {/* ── Incentive Types ───────────────────────────────────────────── */}
      <SectionCard title="Incentive Types">
        <div className="px-4 py-3 grid grid-cols-4 gap-x-4 gap-y-2 border-b border-gray-100">
          {INCENTIVE_TYPES.map(type => (
            <label key={type} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={!!incentives[type]} onChange={() => toggleIncentive(type)}
                className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
              <span className="text-xs text-gray-700">{type}</span>
            </label>
          ))}
        </div>

        {selectedIncentives.length > 0 && (
          <>
            <TabBar
              tabs={selectedIncentives}
              active={activeIncentiveTab}
              onSelect={setActiveIncentiveTab}
              onRemove={t => toggleIncentive(t)}
            />
            {activeIncentiveTab && incentives[activeIncentiveTab] && (
              <IncentiveTabContent
                name={activeIncentiveTab}
                data={incentiveData[activeIncentiveTab] ?? {}}
                onChange={(k, v) => setIncentiveField(activeIncentiveTab, k, v)}
              />
            )}
          </>
        )}
      </SectionCard>

      {/* ── Inclusions / Exclusions ───────────────────────────────────── */}
      <SectionCard title="Inclusions / Exclusions">
        <div className="px-4 py-3 grid grid-cols-4 gap-x-4 gap-y-2 border-b border-gray-100">
          {INCLUSIONS_EXCLUSIONS.map(item => (
            <label key={item} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={!!inclExcl[item]} onChange={() => toggleInclExcl(item)}
                className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
              <span className="text-xs text-gray-700">{item}</span>
            </label>
          ))}
        </div>

        {selectedInclExcl.length > 0 && (
          <>
            <TabBar
              tabs={selectedInclExcl}
              active={activeInclExclTab}
              onSelect={setActiveInclExclTab}
              onRemove={t => toggleInclExcl(t)}
            />
            {activeInclExclTab && inclExcl[activeInclExclTab] && (() => {
              const meta = INCL_EXCL_META[activeInclExclTab];
              return (
                <InclExclTabContent
                  suffix={meta.suffix}
                  isExclusion={meta.isExclusion}
                  data={inclExclData[activeInclExclTab] ?? {}}
                  onChange={(k, v) => setInclExclField(activeInclExclTab, k, v)}
                  viceVersa={!!viceVersa[activeInclExclTab]}
                  onViceVersa={() => toggleViceVersa(activeInclExclTab)}
                  continentOptions={continentOptions}
                  countryGroupOptions={countryGroupOptions}
                />
              );
            })()}
          </>
        )}
      </SectionCard>

      {/* ── File Drop ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-lg border border-gray-200 px-4 py-3 space-y-1.5">
        <div className="flex items-center gap-1">
          <span className="text-xs font-semibold text-blue-600 uppercase tracking-wide">File Drop</span>
          <span className="w-3.5 h-3.5 rounded-full border border-gray-400 text-gray-400 text-[9px] flex items-center justify-center cursor-help" title="Upload contract PDF">i</span>
        </div>
        <p className="text-[10px] text-gray-400">Supported File Type(s): .pdf</p>
        <div onDragOver={e => e.preventDefault()} onDrop={handleDrop} onClick={() => fileRef.current?.click()}
          className="border-2 border-dashed border-gray-200 rounded-lg flex flex-col items-center justify-center py-6 cursor-pointer hover:border-blue-300 hover:bg-blue-50/20 transition-colors">
          <input ref={fileRef} type="file" accept=".pdf" className="hidden"
            onChange={e => setFile(e.target.files?.[0] ?? null)}/>
          <svg className="w-8 h-8 text-blue-400 mb-1" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="8" y="6" width="24" height="32" rx="3"/>
            <rect x="16" y="10" width="24" height="32" rx="3" strokeDasharray="4 2"/>
          </svg>
          <p className="text-xs text-blue-500">{file ? file.name : "Drag and drop or click to upload file."}</p>
        </div>
      </div>

      {/* ── Remark ────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
        <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Remark</label>
        <textarea rows={2} placeholder="Enter text" value={remark} onChange={e => setRemark(e.target.value)}
          className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"/>
      </div>

      {/* ── Deal Maker Details ────────────────────────────────────────── */}
      <SectionCard title="Deal Maker Details">
        <div className="px-4 py-3">
          <div className="max-w-[50%]">
            <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Name</label>
            <input type="text" placeholder="Enter Name" value={dealMakerName} onChange={e => setDealMakerName(e.target.value)}
              className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
          </div>
        </div>
      </SectionCard>

      {/* ── Sticky bottom bar ────────────────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 z-40">
        {submitError && (
          <p className="text-center text-[11px] text-red-500 py-1 border-b border-red-100 bg-red-50">{submitError}</p>
        )}
        <div className="flex items-center justify-center gap-3 py-2.5">
          <button type="button" onClick={() => router.push("/deals")}
            className="px-7 py-1.5 border border-red-400 text-red-500 rounded-full text-xs font-medium hover:bg-red-50 transition-colors">
            Cancel
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting}
            className="px-7 py-1.5 bg-blue-600 text-white rounded-full text-xs font-medium hover:bg-blue-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed">
            {submitting ? "Saving..." : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
