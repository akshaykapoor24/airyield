"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, X, ArrowLeft } from "lucide-react";
import api from "@/lib/api";

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

const CONTINENTS         = ["Asia","Europe","North America","South America","Africa","Middle East","Oceania"];
const COUNTRY_GROUPS     = ["GCC","SAARC","EU","ASEAN","APAC"];
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
function InclExclTabContent({ suffix, isExclusion, data, onChange, viceVersa, onViceVersa }: {
  suffix: string; isExclusion: boolean;
  data: Record<string, string>; onChange: (k: string, v: string) => void;
  viceVersa: boolean; onViceVersa: () => void;
}) {
  const rows: { key: string; label: string; isSelect?: boolean; options?: string[] }[][] = [
    [{ key:"continents", label:`Continents ${suffix}` }, { key:"countryGroup", label:`Country Group ${suffix}` }],
    [{ key:"originContinents", label:`Origin Continents ${suffix}` }, { key:"destContinents", label:`Destination Continents ${suffix}` }],
    [{ key:"originCountryGroup", label:`Origin Country Group ${suffix}` }, { key:"destCountryGroup", label:`Destination Country Group ${suffix}` }],
    [{ key:"originCountry", label:`Origin Country ${suffix}` }, { key:"destCountry", label:`Destination Country ${suffix}` }],
    [{ key:"originAirport", label:`Origin Airport ${suffix}` }, { key:"destAirport", label:`Destination Airport ${suffix}` }],
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

  return (
    <div className="px-4 py-3 space-y-3">
      {rows.map((pair, ri) => (
        <div key={ri} className={`grid gap-3 ${pair.length === 2 ? "grid-cols-2" : "grid-cols-1 max-w-[50%]"}`}>
          {pair.map(f => (
            <div key={f.key}>
              {f.isSelect
                ? <SelectField label={f.label} options={f.options??[]} value={data[f.key]??""} onChange={v => onChange(f.key, v)}/>
                : <SearchSelectField label={f.label} options={INCL_EXCL_SEARCH_OPTIONS[f.key]??[]} value={data[f.key]??""} onChange={v => onChange(f.key, v)}/>
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
function DealTypeSelector({ onSelect }: { onSelect: (t: "airline" | "b2b") => void }) {
  const [selected, setSelected] = useState<"airline" | "b2b" | null>(null);

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-10 w-full max-w-md">
        <h1 className="text-base font-semibold text-gray-800 mb-1">Select Deal Type</h1>
        <p className="text-xs text-gray-400 mb-6">Choose the type of deal you want to create.</p>

        <div className="flex flex-col gap-3 mb-8">
          {(["airline", "b2b"] as const).map(type => (
            <label key={type}
              className={`flex items-center gap-3 border rounded-lg px-4 py-3.5 cursor-pointer transition-colors ${
                selected === type
                  ? "border-blue-500 bg-blue-50/60"
                  : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
              }`}>
              <input
                type="radio"
                name="dealType"
                value={type}
                checked={selected === type}
                onChange={() => setSelected(type)}
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

        <button
          type="button"
          disabled={!selected}
          onClick={() => selected && onSelect(selected)}
          className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function NewDealPage() {
  const router = useRouter();

  // step: null = deal-type selection, set = form
  const [dealType, setDealType] = useState<"airline" | "b2b" | null>(null);

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
    if (!airlineType || !airlineName || !validFrom || !validTo) {
      setSubmitError("Please fill in Airline Type, Airline Name, Valid From and Valid To.");
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

  // ── Step 0: deal-type selection ──────────────────────────────────────────
  if (dealType === null) {
    return <DealTypeSelector onSelect={setDealType} />;
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
