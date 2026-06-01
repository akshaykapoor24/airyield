"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft, RefreshCw, Upload, Plus, X, CheckCircle, XCircle,
  AlertCircle, MinusCircle, User, Clock, Pencil, Save, Trash2,
  FileText, FileSpreadsheet, Building2, Calendar, Hash, ChevronDown,
} from "lucide-react";
import api from "@/lib/api";

// ── incl/excl option constants ─────────────────────────────────────────────
const IE_CONTINENTS     = ["Africa","Asia","Europe","North America","Oceania","South America","Antarctica"];
const IE_COUNTRY_GROUPS = ["APAC","EUROPEAN NATIONS","GCC/MIDDLE EAST","LATIN AMERICA","MEAI","MEAI/APAC","MEAI/SAARC","MEAI/SAARC/APAC","NAM","OTHER","SAARC","SAARC/APAC"];
const IE_CITIES         = ["Delhi","Mumbai","Dubai","Doha","London","Frankfurt","New York","Singapore","Sydney"];
const IE_FARE_TYPE_CATS = ["Normal","Group","Corporate","Excursion","Tour"];
const IE_TOUR_CODES     = ["TC001","TC002","TC003","TC004"];
const IE_DOMESTIC_CTRS  = ["India","UAE","UK","USA","Australia"];
const IE_CLASS_OPTIONS  = ["All","Economy","Premium Economy","Business","First"];
const IE_SOTO_OPTIONS   = ["SOTO All","SOTO within India","SOTO outside India"];

// ── shared UI primitives ───────────────────────────────────────────────────
function IESelectField({label,options,value,onChange}:{label?:string;options:string[];value:string;onChange:(v:string)=>void}){
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))setOpen(false);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[]);
  return(
    <div className="relative" ref={ref}>
      {label&&<label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={()=>setOpen(o=>!o)} className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={value?"text-gray-800":"text-gray-400"}>{value||"Select…"}</span>
        <div className="flex items-center gap-0.5">
          {value&&<span onClick={e=>{e.stopPropagation();onChange("");}} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open&&<div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg max-h-44 overflow-y-auto">
        {options.map(opt=><button key={opt} type="button" onClick={()=>{onChange(opt);setOpen(false);}} className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-50 text-gray-700">{opt}</button>)}
      </div>}
    </div>
  );
}

function IEMultiCheckboxDropdown({label,placeholder="Select...",options,values,onChange}:{label?:string;placeholder?:string;options:string[];values:string[];onChange:(v:string[])=>void}){
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))setOpen(false);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[]);
  const toggle=(opt:string)=>onChange(values.includes(opt)?values.filter(v=>v!==opt):[...values,opt]);
  const display=values.length?values.join(", "):null;
  return(
    <div className="relative" ref={ref}>
      {label&&<label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={()=>setOpen(o=>!o)} className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={display?"text-gray-800":"text-gray-400"}>{display||placeholder}</span>
        <div className="flex items-center gap-0.5">
          {values.length>0&&<span onClick={e=>{e.stopPropagation();onChange([]);}} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open&&<div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg">
        {options.map(opt=>(
          <label key={opt} className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-blue-50 cursor-pointer">
            <input type="checkbox" checked={values.includes(opt)} onChange={()=>toggle(opt)} className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"/>
            {opt}
          </label>
        ))}
      </div>}
    </div>
  );
}

function IESearchSelectField({label,placeholder="Search and select",options,value,onChange}:{label?:string;placeholder?:string;options:string[];value:string;onChange:(v:string)=>void}){
  const [open,setOpen]=useState(false);const [search,setSearch]=useState("");
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))setOpen(false);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[]);
  const filtered=options.filter(o=>o.toLowerCase().includes(search.toLowerCase()));
  return(
    <div className="relative" ref={ref}>
      {label&&<label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={()=>{setOpen(o=>!o);setSearch("");}} className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={value?"text-gray-800":"text-gray-400"}>{value||placeholder}</span>
        <div className="flex items-center gap-0.5">
          {value&&<span onClick={e=>{e.stopPropagation();onChange("");}} className="text-gray-300 hover:text-red-400"><X className="w-3 h-3"/></span>}
          <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
        </div>
      </button>
      {open&&<div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg">
        <div className="p-1.5 border-b border-gray-100"><input autoFocus value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search..." className="w-full text-xs px-2 py-1 border border-gray-200 rounded focus:outline-none"/></div>
        <div className="max-h-36 overflow-y-auto">
          {filtered.length?filtered.map(opt=><button key={opt} type="button" onClick={()=>{onChange(opt);setOpen(false);}} className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-blue-50 text-gray-700">{opt}</button>):<p className="px-2.5 py-1.5 text-xs text-gray-400">No results</p>}
        </div>
      </div>}
    </div>
  );
}

// ── types ──────────────────────────────────────────────────────────────────
type DealType = "upload" | "airline" | "b2b";

type DealBatch = {
  batch_id:        string;
  deal_type:       string;
  supplier_name:   string | null;
  file_name:       string | null;
  file_type:       string | null;
  incentive_types: string[];
  valid_from:      string | null;
  valid_to:        string | null;
  deal_count:      number;
  created_by_name: string | null;
  created_at:      string;
};

type DealRepositoryItem = {
  id:              number;
  deal_no:         string;
  deal_type:       DealType;
  source_agent:    string;
  airline_type:    string | null;
  airline_name:    string | null;
  contract_year:   string | null;
  valid_from:      string | null;
  valid_to:        string | null;
  trigger_type:    string | null;
  payout_type:     string | null;
  business_type:   string | null;
  entity_lcc:      string | null;
  remark:          string | null;
  deal_maker_name: string | null;
  incentive_types: string[] | null;
  incentive_data:  Record<string, Record<string, string>> | null;
  incl_excl_types: string[] | null;
  incl_excl_data:  Record<string, Record<string, string>> | null;
  status:                string;
  deal_lifecycle_status: string | null;
  created_at:            string;
  file_type:             string | null;
};

type DealHistoryStep = {
  step_order:          number;
  role:                string;
  assigned_user_name:  string;
  status:              string;
  acted_by_name:       string | null;
  acted_at:            string | null;
  reason:              string | null;
};

type DealHistoryData = {
  deal_id:          number;
  created_by_name:  string;
  created_at:       string;
  source_type:      string;
  status:           string;
  steps:            DealHistoryStep[];
};

// ── helpers ────────────────────────────────────────────────────────────────
const STATUS_STYLE: Record<string, string> = {
  approved:         "bg-green-50 text-green-600 border-green-200",
  confirmed:        "bg-blue-50 text-blue-600 border-blue-200",
  pending_approval: "bg-blue-50 text-blue-600 border-blue-200",
  extracted:        "bg-yellow-50 text-yellow-600 border-yellow-200",
  rejected:         "bg-red-50 text-red-600 border-red-200",
};
const STATUS_DOT: Record<string, string> = {
  approved:         "bg-green-500",
  confirmed:        "bg-blue-500",
  pending_approval: "bg-blue-500",
  extracted:        "bg-yellow-500",
  rejected:         "bg-red-500",
};
const STATUS_LABEL: Record<string, string> = {
  confirmed:        "Pending Approval",
  pending_approval: "Pending Approval",
  approved:         "Approved",
  rejected:         "Rejected",
  extracted:        "Extracted",
};

const LIFECYCLE_STYLE: Record<string, string> = {
  draft:  "bg-gray-50 text-gray-500 border-gray-200",
  active: "bg-emerald-50 text-emerald-600 border-emerald-200",
  closed: "bg-slate-100 text-slate-500 border-slate-300",
};
const LIFECYCLE_DOT: Record<string, string> = {
  draft:  "bg-gray-400",
  active: "bg-emerald-500",
  closed: "bg-slate-400",
};
const LIFECYCLE_LABEL: Record<string, string> = {
  draft:  "Draft",
  active: "Active",
  closed: "Closed",
};

const DEAL_TYPE_STYLE: Record<string, { label: string; cls: string }> = {
  airline: { label: "Airline", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  b2b:     { label: "B2B",     cls: "bg-violet-50 text-violet-700 border-violet-200" },
  upload:  { label: "Upload",  cls: "bg-teal-50 text-teal-700 border-teal-200" },
};

const STEP_STATUS_CONFIG: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  approved: { icon: <CheckCircle className="w-3.5 h-3.5" />, color: "text-green-600", label: "Approved" },
  rejected: { icon: <XCircle    className="w-3.5 h-3.5" />, color: "text-red-600",   label: "Rejected" },
  pending:  { icon: <AlertCircle className="w-3.5 h-3.5" />, color: "text-blue-500", label: "Pending"  },
  skipped:  { icon: <MinusCircle className="w-3.5 h-3.5" />, color: "text-gray-400", label: "Skipped"  },
};

const CONTRACT_YEAR_OPTIONS = ["Calendar year", "Financial year"];
const TRIGGER_TYPE_OPTIONS  = ["Flown", "Sales"];
const PAYOUT_TYPE_OPTIONS   = ["Flown", "Sales"];
const BUSINESS_TYPE_OPTIONS = ["B2B", "B2C", "B2E", "MICE"];
const AIRLINE_TYPE_OPTIONS  = ["GDS", "LCC"];

function formatDate(d: string | null) {
  if (!d) return "—";
  try { return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return d; }
}

function formatDateTime(d: string | null) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return d; }
}

function getDealTypeBadge(d: DealRepositoryItem) {
  if (d.deal_type !== "upload") return DEAL_TYPE_STYLE[d.deal_type];
  if (d.business_type) return DEAL_TYPE_STYLE.b2b;
  return DEAL_TYPE_STYLE.airline;
}

const TABLE_HEADERS = [
  "Deal No", "Deal Type", "Airline Name", "Airline Type", "Contract Year",
  "Valid From", "Valid To",
  "Trigger Type", "Payout Type",
  "Business Type", "Entity (LCC)",
  "Incentive Types", "Incl / Excl",
  "Deal Maker", "Approval Status", "Deal Status", "Actions",
];

// ── IncentiveEditModal ─────────────────────────────────────────────────────
function IncentiveEditModal({ name, data, onSave, onClose }: {
  name: string;
  data: Record<string, string>;
  onSave: (updated: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>({ ...data });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(fields); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Incentive Type — Edit Details</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
          {Object.keys(fields).length === 0 ? (
            <p className="text-xs text-gray-400 py-2">No fields recorded for this incentive.</p>
          ) : (
            <div className="space-y-3">
              {Object.entries(fields).map(([k, v]) => (
                <div key={k}>
                  <label className="block text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                    {k.replace(/([A-Z])/g, " $1").trim()}
                  </label>
                  <input
                    type="text"
                    value={v}
                    onChange={e => setFields(prev => ({ ...prev, [k]: e.target.value }))}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="px-5 pb-4 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ── InclExclEditModal ──────────────────────────────────────────────────────
function InclExclEditModal({ name, data, onSave, onClose }: {
  name: string;
  data: Record<string, string>;
  onSave: (updated: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Record<string,string>>({ ...data });
  const [saving, setSaving] = useState(false);
  const isExcl = name.startsWith("Exclusion");
  const suffix  = isExcl ? "for Exclusion" : "for Inclusion";

  const [continentOptions,    setContinentOptions]    = useState<string[]>(IE_CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(IE_COUNTRY_GROUPS);
  const [originCountries, setOriginCountries] = useState<string[]>([]);
  const [destCountries,   setDestCountries]   = useState<string[]>([]);
  const [originAirports,  setOriginAirports]  = useState<string[]>([]);
  const [destAirports,    setDestAirports]    = useState<string[]>([]);
  const [allCountries,    setAllCountries]    = useState<string[]>([]);
  const [allAirports,     setAllAirports]     = useState<string[]>([]);

  useEffect(()=>{
    api.get<{continents:string[];country_groups:string[]}>("/airports/options")
      .then(r=>{
        if(r.data.continents?.length)     setContinentOptions(r.data.continents);
        if(r.data.country_groups?.length) setCountryGroupOptions(r.data.country_groups);
      }).catch(()=>{});
    api.get<{iata_code:string;country:string|null}[]>("/airports/?limit=5000")
      .then(r=>{
        setAllAirports(r.data.map(a=>a.iata_code).filter(Boolean));
        const countries=[...new Set(r.data.map(a=>a.country).filter(Boolean))] as string[];
        setAllCountries(countries.sort());
      }).catch(()=>{});
  },[]);

  const origContinent = form["originContinents"] ?? "";
  const destContinent = form["destContinents"]   ?? "";
  const origCountry   = form["originCountry"]    ?? "";
  const destCountry   = form["destCountry"]      ?? "";

  useEffect(()=>{
    if(!origContinent){setOriginCountries([]);return;}
    api.get<{countries:string[]}>(`/airports/options?continent=${encodeURIComponent(origContinent)}`)
      .then(r=>setOriginCountries(r.data.countries??[])).catch(()=>setOriginCountries([]));
  },[origContinent]);

  useEffect(()=>{
    if(!destContinent){setDestCountries([]);return;}
    api.get<{countries:string[]}>(`/airports/options?continent=${encodeURIComponent(destContinent)}`)
      .then(r=>setDestCountries(r.data.countries??[])).catch(()=>setDestCountries([]));
  },[destContinent]);

  useEffect(()=>{
    if(!origCountry){setOriginAirports([]);return;}
    api.get<{airports:string[]}>(`/airports/options?country=${encodeURIComponent(origCountry)}`)
      .then(r=>setOriginAirports(r.data.airports??[])).catch(()=>setOriginAirports([]));
  },[origCountry]);

  useEffect(()=>{
    if(!destCountry){setDestAirports([]);return;}
    api.get<{airports:string[]}>(`/airports/options?country=${encodeURIComponent(destCountry)}`)
      .then(r=>setDestAirports(r.data.airports??[])).catch(()=>setDestAirports([]));
  },[destCountry]);

  const handleChange=(k:string,v:string)=>{
    setForm(p=>({...p,[k]:v}));
  };

  const opts:Record<string,string[]>={
    continents:continentOptions,           countryGroup:countryGroupOptions,
    originContinents:continentOptions,     destContinents:continentOptions,
    originCountryGroup:countryGroupOptions,destCountryGroup:countryGroupOptions,
    originCountry:origContinent?originCountries:allCountries,
    destCountry:destContinent?destCountries:allCountries,
    originAirport:origCountry?originAirports:allAirports,
    destAirport:destCountry?destAirports:allAirports,
    city:IE_CITIES, fareTypeCategory:IE_FARE_TYPE_CATS,
    class:IE_CLASS_OPTIONS, tourCode:IE_TOUR_CODES, domesticCountry:IE_DOMESTIC_CTRS,
  };

  const dateExclusionValues=[
    ...(form["dateExclusionTicket"]==="true"?["Ticket Date"]:[]),
    ...(form["dateExclusionTravel"]==="true"?["Travel Date"]:[]),
  ];
  const handleDateExclusionChange=(selected:string[])=>{
    setForm(p=>({...p,
      dateExclusionTicket:selected.includes("Ticket Date")?"true":"",
      dateExclusionTravel:selected.includes("Travel Date")?"true":"",
    }));
  };

  type IERow={key:string;label:string;isDate?:boolean;isSelect?:boolean;options?:string[];placeholder?:string};
  const rows:IERow[][]=[
    [{key:"validFrom",label:"Valid From",isDate:true},{key:"validTo",label:"Valid To",isDate:true}],
    [{key:"continents",label:`Continents ${suffix}`},{key:"countryGroup",label:`Country Group ${suffix}`}],
    [{key:"originContinents",label:`Origin Continents ${suffix}`},{key:"destContinents",label:`Destination Continents ${suffix}`}],
    [{key:"originCountryGroup",label:`Origin Country Group ${suffix}`},{key:"destCountryGroup",label:`Destination Country Group ${suffix}`}],
    [
      {key:"originCountry",label:`Origin Country ${suffix}`,placeholder:origContinent?"Search and select":"Select origin continent first"},
      {key:"destCountry",  label:`Destination Country ${suffix}`,placeholder:destContinent?"Search and select":"Select destination continent first"},
    ],
    [
      {key:"originAirport",label:`Origin Airport ${suffix}`,placeholder:origCountry?"Search and select":"Select origin country first"},
      {key:"destAirport",  label:`Destination Airport ${suffix}`,placeholder:destCountry?"Search and select":"Select destination country first"},
    ],
    [{key:"city",label:`City ${suffix}`},{key:"fareTypeCategory",label:`Fare Type Category ${suffix}`}],
    [
      {key:"class",label:`Class ${suffix}`},
      isExcl
        ?{key:"soto",label:"SOTO for Exclusion",isSelect:true,options:IE_SOTO_OPTIONS}
        :{key:"tourCode",label:`Tour Code ${suffix}`},
    ],
    ...(isExcl
      ?[[{key:"tourCode",label:`Tour Code ${suffix}`},{key:"domesticCountry",label:`Domestic Country ${suffix}`}]]
      :[[{key:"domesticCountry",label:`Domestic Country ${suffix}`}]]
    ),
  ];

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(form); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={e=>e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className={`text-sm font-bold ${isExcl?"text-red-700":"text-green-700"}`}>{name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">{isExcl?"Exclusion":"Inclusion"} Rule — Details</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500"/></button>
        </div>
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-3">
          <div className="grid gap-3 grid-cols-1 max-w-[50%]">
            <IEMultiCheckboxDropdown
              label="Date Exclusion"
              placeholder="Select date exclusion"
              options={["Ticket Date","Travel Date"]}
              values={dateExclusionValues}
              onChange={handleDateExclusionChange}
            />
          </div>
          {rows.map((pair,ri)=>(
            <div key={ri} className={`grid gap-3 ${pair.length===2?"grid-cols-2":"grid-cols-1 max-w-[50%]"}`}>
              {pair.map(f=>(
                <div key={f.key}>
                  {f.isDate?(
                    <div>
                      <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{f.label}</label>
                      <input type="date" value={form[f.key]??""} onChange={e=>handleChange(f.key,e.target.value)}
                        className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-800"/>
                    </div>
                  ):f.isSelect?(
                    <IESelectField label={f.label} options={f.options??[]} value={form[f.key]??""} onChange={v=>handleChange(f.key,v)}/>
                  ):(
                    <IESearchSelectField label={f.label} placeholder={f.placeholder} options={opts[f.key]??[]} value={form[f.key]??""} onChange={v=>handleChange(f.key,v)}/>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="px-5 pb-4 pt-3 border-t border-gray-100 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5"/>{saving?"Saving...":"Save Changes"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ── DealHistoryPanel ───────────────────────────────────────────────────────
function DealHistoryPanel({ dealId, dealType, displayLabel, data, loading, onClose }: {
  dealId: number; dealType: DealType; displayLabel: string;
  data: DealHistoryData | null; loading: boolean; onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-100 bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Deal #{dealId} — History</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">{displayLabel} deal · Creation &amp; approval trail</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-5 h-5 animate-spin text-gray-300" />
            </div>
          ) : !data ? (
            <p className="text-xs text-gray-400 text-center py-12">Failed to load history.</p>
          ) : (
            <>
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Created</p>
                <div className="flex items-start gap-3 bg-gray-50 rounded-xl p-3">
                  <div className="w-8 h-8 rounded-full bg-[#1e3a5f] flex items-center justify-center shrink-0">
                    <User className="w-4 h-4 text-white" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold text-gray-800">{data.created_by_name}</p>
                    <p className="text-[11px] text-gray-500 mt-0.5">{formatDateTime(data.created_at)}</p>
                    <span className={`inline-block mt-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                      data.source_type === "manual"
                        ? "bg-indigo-50 text-indigo-600 border border-indigo-200"
                        : "bg-teal-50 text-teal-600 border border-teal-200"
                    }`}>{data.source_type}</span>
                  </div>
                </div>
              </div>
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Approval Timeline</p>
                {data.steps.length === 0 ? (
                  <p className="text-[12px] text-gray-400 italic py-4 text-center">No approval steps yet.</p>
                ) : (
                  <div className="relative">
                    <div className="absolute left-4 top-2 bottom-2 w-px bg-gray-200" />
                    <div className="space-y-4">
                      {data.steps.map((step, idx) => {
                        const cfg = STEP_STATUS_CONFIG[step.status] ?? STEP_STATUS_CONFIG.pending;
                        return (
                          <div key={idx} className="flex gap-3 relative">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 ${
                              step.status === "approved" ? "bg-green-50 border-2 border-green-400"
                              : step.status === "rejected" ? "bg-red-50 border-2 border-red-400"
                              : step.status === "skipped" ? "bg-gray-50 border-2 border-gray-300"
                              : "bg-blue-50 border-2 border-blue-400"
                            }`}>
                              <span className={`text-[10px] font-bold ${cfg.color}`}>{step.step_order}</span>
                            </div>
                            <div className="flex-1 min-w-0 pb-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-[11px] font-semibold text-gray-700">{step.role}</span>
                                <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${cfg.color}`}>
                                  {cfg.icon} {cfg.label}
                                </span>
                              </div>
                              <p className="text-[11px] text-gray-500 mt-0.5">
                                Assigned to: <span className="font-medium text-gray-700">{step.assigned_user_name}</span>
                              </p>
                              {step.acted_by_name && step.acted_at && (
                                <p className="text-[11px] text-gray-500 mt-0.5">
                                  By: <span className="font-medium text-gray-700">{step.acted_by_name}</span>
                                  {" · "}{formatDateTime(step.acted_at)}
                                </p>
                              )}
                              {step.reason && (
                                <p className="text-[11px] text-gray-500 italic mt-1 bg-gray-50 rounded px-2 py-1">
                                  &ldquo;{step.reason}&rdquo;
                                </p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ── DealEditPanel ──────────────────────────────────────────────────────────
type EditFields = {
  airline_type:    string;
  airline_name:    string;
  contract_year:   string;
  valid_from:      string;
  valid_to:        string;
  trigger_type:    string;
  payout_type:     string;
  business_type:   string;
  entity_lcc:      string;
  remark:          string;
  deal_maker_name: string;
};

function DealEditPanel({ deal, onSave, onClose }: {
  deal: DealRepositoryItem;
  onSave: (updated: Partial<EditFields>) => Promise<void>;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<EditFields>({
    airline_type:    deal.airline_type    ?? "",
    airline_name:    deal.airline_name    ?? "",
    contract_year:   deal.contract_year   ?? "",
    valid_from:      deal.valid_from      ?? "",
    valid_to:        deal.valid_to        ?? "",
    trigger_type:    deal.trigger_type    ?? "",
    payout_type:     deal.payout_type     ?? "",
    business_type:   deal.business_type   ?? "",
    entity_lcc:      deal.entity_lcc      ?? "",
    remark:          deal.remark          ?? "",
    deal_maker_name: deal.deal_maker_name ?? "",
  });
  const [saving, setSaving] = useState(false);

  const set = (k: keyof EditFields) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setFields(prev => ({ ...prev, [k]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Partial<EditFields> = {};
      for (const [k, v] of Object.entries(fields) as [keyof EditFields, string][]) {
        const orig = (deal[k as keyof DealRepositoryItem] ?? "") as string;
        if (v !== orig) payload[k] = v || undefined;
      }
      await onSave(payload);
    } finally { setSaving(false); }
  };

  const inp = "w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400";
  const lbl = "block text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1";
  const sel = `${inp} bg-white`;

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-[480px] bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Edit Deal #{deal.id}</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">{getDealTypeBadge(deal).label} deal · {deal.airline_name || deal.source_agent}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Contract Details</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Airline Type</label>
              <select value={fields.airline_type} onChange={set("airline_type")} className={sel}>
                <option value="">— Select —</option>
                {AIRLINE_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Airline Name</label>
              <input type="text" value={fields.airline_name} onChange={set("airline_name")} className={inp} placeholder="e.g. Air India" />
            </div>
            <div>
              <label className={lbl}>Contract Year</label>
              <select value={fields.contract_year} onChange={set("contract_year")} className={sel}>
                <option value="">— Select —</option>
                {CONTRACT_YEAR_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Business Type</label>
              <select value={fields.business_type} onChange={set("business_type")} className={sel}>
                <option value="">— Select —</option>
                {BUSINESS_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Valid From</label>
              <input type="date" value={fields.valid_from} onChange={set("valid_from")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Valid To</label>
              <input type="date" value={fields.valid_to} onChange={set("valid_to")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Trigger Type</label>
              <select value={fields.trigger_type} onChange={set("trigger_type")} className={sel}>
                <option value="">— Select —</option>
                {TRIGGER_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Payout Type</label>
              <select value={fields.payout_type} onChange={set("payout_type")} className={sel}>
                <option value="">— Select —</option>
                {PAYOUT_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Entity (LCC)</label>
              <input type="text" value={fields.entity_lcc} onChange={set("entity_lcc")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Deal Maker</label>
              <input type="text" value={fields.deal_maker_name} onChange={set("deal_maker_name")} className={inp} />
            </div>
          </div>
          <div>
            <label className={lbl}>Remark</label>
            <textarea value={fields.remark} onChange={set("remark")} rows={3}
              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none" />
          </div>
        </div>
        <div className="px-5 py-4 border-t border-gray-100 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save Changes"}
          </button>
          <button onClick={onClose} className="px-4 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </>
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function DealBatchPage() {
  const params = useParams();
  const batchId = params.batch_id as string;

  const [batch,   setBatch]   = useState<DealBatch | null>(null);
  const [deals,   setDeals]   = useState<DealRepositoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  // history panel
  const [historyDealId,   setHistoryDealId]   = useState<number | null>(null);
  const [historyDealType, setHistoryDealType] = useState<DealType>("upload");
  const [historyLabel,    setHistoryLabel]    = useState("Upload");
  const [historyData,     setHistoryData]     = useState<DealHistoryData | null>(null);
  const [historyLoading,  setHistoryLoading]  = useState(false);

  // edit panel
  const [editDeal, setEditDeal] = useState<DealRepositoryItem | null>(null);

  // delete
  const [deleteTarget,  setDeleteTarget]  = useState<DealRepositoryItem | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // incentive / incl-excl edit popups
  const [incentivePopup, setIncentivePopup] = useState<{
    name: string; data: Record<string, string>; dealId: number; dealType: DealType;
  } | null>(null);
  const [inclExclPopup, setInclExclPopup] = useState<{
    name: string; data: Record<string, string>; dealId: number; dealType: DealType;
  } | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [batchRes, dealsRes] = await Promise.all([
        api.get<DealBatch>(`/deals/batches/${batchId}`),
        api.get<DealRepositoryItem[]>(`/deals/repository?batch_id=${batchId}`),
      ]);
      setBatch(batchRes.data);
      setDeals(dealsRes.data);
    } catch {
      setError("Failed to load batch. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const openHistory = useCallback(async (d: DealRepositoryItem) => {
    setHistoryDealId(d.id);
    setHistoryDealType(d.deal_type);
    setHistoryLabel(getDealTypeBadge(d).label);
    setHistoryData(null);
    setHistoryLoading(true);
    try {
      const { data } = await api.get<DealHistoryData>(`/deals/repository/${d.id}/history?deal_type=${d.deal_type}`);
      setHistoryData(data);
    } catch {
      setHistoryData(null);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const closeHistory = useCallback(() => {
    setHistoryDealId(null);
    setHistoryData(null);
  }, []);

  const patchDeal = useCallback(async (dealId: number, dealType: DealType, payload: object) => {
    const { data } = await api.patch<DealRepositoryItem>(
      `/deals/repository/${dealId}?deal_type=${dealType}`,
      payload
    );
    setDeals(prev => prev.map(d => d.id === data.id && d.deal_type === data.deal_type ? data : d));
    return data;
  }, []);

  const handleEditSave = useCallback(async (payload: Partial<EditFields>) => {
    if (!editDeal) return;
    const wasRejected = editDeal.status === "rejected";
    await patchDeal(editDeal.id, editDeal.deal_type, payload);
    if (wasRejected) {
      await api.post(`/deals/repository/${editDeal.id}/resubmit?deal_type=${editDeal.deal_type}`);
      await fetchAll();
    }
    setEditDeal(null);
  }, [editDeal, patchDeal, fetchAll]);

  const handleIncentiveSave = useCallback(async (updatedData: Record<string, string>) => {
    if (!incentivePopup) return;
    const deal = deals.find(d => d.id === incentivePopup.dealId && d.deal_type === incentivePopup.dealType);
    if (!deal) return;
    const newIncentiveData = { ...(deal.incentive_data ?? {}), [incentivePopup.name]: updatedData };
    await patchDeal(incentivePopup.dealId, incentivePopup.dealType, { incentive_data: newIncentiveData });
  }, [incentivePopup, deals, patchDeal]);

  const handleInclExclSave = useCallback(async (updatedData: Record<string, string>) => {
    if (!inclExclPopup) return;
    const deal = deals.find(d => d.id === inclExclPopup.dealId && d.deal_type === inclExclPopup.dealType);
    if (!deal) return;
    const newInclExclData = { ...(deal.incl_excl_data ?? {}), [inclExclPopup.name]: updatedData };
    await patchDeal(inclExclPopup.dealId, inclExclPopup.dealType, { incl_excl_data: newInclExclData });
  }, [inclExclPopup, deals, patchDeal]);

  const handleDeleteDeal = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      await api.delete(`/deals/repository/${deleteTarget.id}?deal_type=${deleteTarget.deal_type}`);
      setDeals(prev => prev.filter(d => !(d.id === deleteTarget.id && d.deal_type === deleteTarget.deal_type)));
      setDeleteTarget(null);
    } catch {
      // keep state; user can retry
    } finally {
      setDeleteLoading(false);
    }
  }, [deleteTarget]);

  if (loading) return (
    <div className="flex items-center justify-center py-32">
      <div className="text-center space-y-3">
        <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
        <p className="text-sm text-gray-500">Loading batch…</p>
      </div>
    </div>
  );

  if (error) return (
    <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700 max-w-xl">
      {error}
    </div>
  );

  const dtStyle = DEAL_TYPE_STYLE[batch?.deal_type ?? "airline"] ?? DEAL_TYPE_STYLE.airline;
  const FileIcon = batch?.file_type === "pdf" ? FileText : FileSpreadsheet;

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/deals"
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-500 transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Deals / Batch</p>
            <h1 className="text-xl font-bold text-gray-900">{batch?.supplier_name || "Batch Detail"}</h1>
          </div>
        </div>
        <button onClick={fetchAll} disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* ── Batch metadata card ── */}
      {batch && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center shrink-0">
              <Building2 className="w-6 h-6 text-blue-500" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <h2 className="text-base font-bold text-gray-900">{batch.supplier_name || "—"}</h2>
                <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase border ${dtStyle.cls}`}>
                  {dtStyle.label}
                </span>
                {(batch.incentive_types ?? []).map(t => (
                  <span key={t} className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">{t}</span>
                ))}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-2 text-xs text-gray-600">
                <div className="flex items-center gap-1.5">
                  <Calendar className="w-3.5 h-3.5 text-gray-400" />
                  <span className="font-medium">{formatDate(batch.valid_from)}</span>
                  <span className="text-gray-400">→</span>
                  <span className="font-medium">{formatDate(batch.valid_to)}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <FileIcon className="w-3.5 h-3.5 text-gray-400" />
                  <span className="truncate max-w-40" title={batch.file_name ?? undefined}>{batch.file_name || "—"}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Hash className="w-3.5 h-3.5 text-gray-400" />
                  <span className="font-semibold text-[#1e3a5f]">{batch.deal_count} deals</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <User className="w-3.5 h-3.5 text-gray-400" />
                  <span>{batch.created_by_name || "—"} · {formatDate(batch.created_at)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Deals table ── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
            {deals.length} Deal{deals.length !== 1 ? "s" : ""}
          </p>
          <div className="flex gap-2">
            <Link href="/deals/upload"
              className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3 py-1 rounded-lg text-xs font-medium hover:bg-gray-50">
              <Upload className="w-3 h-3" /> Upload
            </Link>
            <Link href="/deals/new"
              className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1 rounded-lg text-xs font-medium hover:bg-[#16304f]">
              <Plus className="w-3 h-3" /> Create Deal
            </Link>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {TABLE_HEADERS.map(h => (
                  <th key={h} className="px-2 py-2 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {deals.length === 0 ? (
                <tr>
                  <td colSpan={TABLE_HEADERS.length} className="px-4 py-12 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <Upload className="w-8 h-8 text-gray-300" />
                      <p className="text-xs text-gray-400 font-medium">No deals in this batch</p>
                    </div>
                  </td>
                </tr>
              ) : deals.map((d, idx) => {
                const dtBadge = getDealTypeBadge(d);
                return (
                  <tr key={`${d.deal_type}-${d.id}`}
                    className={`border-b border-gray-100 hover:bg-gray-50/60 transition-colors ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>

                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <span className="font-mono text-[10px] font-semibold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                        {d.deal_no}
                      </span>
                    </td>

                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold uppercase border ${dtBadge.cls}`}>
                        {dtBadge.label}
                      </span>
                    </td>

                    <td className="px-2 py-1.5 min-w-32">
                      <p className="text-[11px] font-semibold text-gray-800 whitespace-nowrap">
                        {d.airline_name || <span className="text-gray-300">—</span>}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 min-w-20">
                      {d.airline_type ? (
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${
                          d.airline_type === "LCC"
                            ? "bg-purple-50 text-purple-700 border-purple-200"
                            : "bg-sky-50 text-sky-700 border-sky-200"
                        }`}>{d.airline_type}</span>
                      ) : <span className="text-[11px] text-gray-300">—</span>}
                    </td>

                    <td className="px-2 py-1.5 min-w-24">
                      <p className="text-[11px] text-gray-700 font-medium whitespace-nowrap">
                        {d.contract_year || <span className="text-gray-300">—</span>}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 min-w-24">
                      <p className="text-[11px] text-green-600 font-medium whitespace-nowrap">{formatDate(d.valid_from)}</p>
                    </td>

                    <td className="px-2 py-1.5 min-w-24">
                      <p className="text-[11px] text-red-500 font-medium whitespace-nowrap">{formatDate(d.valid_to)}</p>
                    </td>

                    <td className="px-2 py-1.5 min-w-20">
                      <p className="text-[11px] text-gray-700 whitespace-nowrap">
                        {d.trigger_type || <span className="text-gray-300">—</span>}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 min-w-20">
                      <p className="text-[11px] text-gray-700 whitespace-nowrap">
                        {d.payout_type || <span className="text-gray-300">—</span>}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 min-w-20">
                      {d.business_type ? (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-gray-100 text-gray-600 border border-gray-200">{d.business_type}</span>
                      ) : <span className="text-[11px] text-gray-300">—</span>}
                    </td>

                    <td className="px-2 py-1.5 min-w-20">
                      <p className="text-[11px] text-gray-700 whitespace-nowrap">
                        {d.entity_lcc || <span className="text-gray-300">—</span>}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 min-w-28">
                      {(d.incentive_types ?? []).length > 0 ? (
                        <div className="flex flex-wrap gap-0.5">
                          {(d.incentive_types ?? []).map(t => (
                            <button key={t}
                              onClick={() => setIncentivePopup({ name: t, data: d.incentive_data?.[t] ?? {}, dealId: d.id, dealType: d.deal_type })}
                              className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-50 text-blue-700 border border-blue-200 whitespace-nowrap hover:bg-blue-100 cursor-pointer transition-colors">
                              {t}
                            </button>
                          ))}
                        </div>
                      ) : <span className="text-[11px] text-gray-300">—</span>}
                    </td>

                    <td className="px-2 py-1.5 min-w-28">
                      {(d.incl_excl_types ?? []).length > 0 ? (
                        <div className="flex flex-wrap gap-0.5">
                          {(d.incl_excl_types ?? []).map(t => {
                            const isExcl = t.toLowerCase().includes("exclusion");
                            return (
                              <button key={t}
                                onClick={() => setInclExclPopup({ name: t, data: d.incl_excl_data?.[t] ?? {}, dealId: d.id, dealType: d.deal_type })}
                                className={`px-1.5 py-0.5 rounded text-[9px] font-semibold border whitespace-nowrap cursor-pointer transition-colors ${
                                  isExcl
                                    ? "bg-red-50 text-red-600 border-red-200 hover:bg-red-100"
                                    : "bg-green-50 text-green-700 border-green-200 hover:bg-green-100"
                                }`}>
                                {t}
                              </button>
                            );
                          })}
                        </div>
                      ) : <span className="text-[11px] text-gray-300">—</span>}
                    </td>

                    <td className="px-2 py-1.5 min-w-28">
                      <p className="text-[11px] font-medium text-gray-700 whitespace-nowrap">
                        {d.deal_maker_name || d.source_agent}
                      </p>
                    </td>

                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${STATUS_STYLE[d.status] ?? "bg-gray-50 text-gray-500 border-gray-200"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[d.status] ?? "bg-gray-400"}`} />
                        {STATUS_LABEL[d.status] ?? d.status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                      </span>
                    </td>

                    <td className="px-2 py-1.5 whitespace-nowrap">
                      {(() => {
                        const ls = d.deal_lifecycle_status ?? "draft";
                        return (
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${LIFECYCLE_STYLE[ls] ?? LIFECYCLE_STYLE.draft}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${LIFECYCLE_DOT[ls] ?? LIFECYCLE_DOT.draft}`} />
                            {LIFECYCLE_LABEL[ls] ?? ls}
                          </span>
                        );
                      })()}
                    </td>

                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openHistory(d)}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors">
                          <Clock className="w-3 h-3" /> History
                        </button>
                        <button
                          onClick={() => (d.status === "approved" || d.status === "rejected") && setEditDeal(d)}
                          disabled={d.status !== "approved" && d.status !== "rejected"}
                          title={
                            d.status === "rejected" ? "Edit and resubmit for approval" :
                            d.status !== "approved" ? "Only approved or rejected deals can be edited" :
                            undefined
                          }
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                          {d.status === "rejected"
                            ? <><RefreshCw className="w-3 h-3" /> Edit &amp; Resubmit</>
                            : <><Pencil className="w-3 h-3" /> Edit</>
                          }
                        </button>
                        <button
                          onClick={() => d.status === "approved" && setDeleteTarget(d)}
                          disabled={d.status !== "approved"}
                          title={d.status !== "approved" ? "Only approved deals can be deleted" : undefined}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-red-200 text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                          <Trash2 className="w-3 h-3" /> Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Deal History Slide-over ── */}
      {historyDealId !== null && (
        <DealHistoryPanel
          dealId={historyDealId}
          dealType={historyDealType}
          displayLabel={historyLabel}
          data={historyData}
          loading={historyLoading}
          onClose={closeHistory}
        />
      )}

      {/* ── Deal Edit Slide-over ── */}
      {editDeal && (
        <DealEditPanel
          deal={editDeal}
          onSave={handleEditSave}
          onClose={() => setEditDeal(null)}
        />
      )}

      {/* ── Incentive edit popup ── */}
      {incentivePopup && (
        <IncentiveEditModal
          name={incentivePopup.name}
          data={incentivePopup.data}
          onSave={handleIncentiveSave}
          onClose={() => setIncentivePopup(null)}
        />
      )}

      {/* ── Incl/Excl edit popup ── */}
      {inclExclPopup && (
        <InclExclEditModal
          name={inclExclPopup.name}
          data={inclExclPopup.data}
          onSave={handleInclExclSave}
          onClose={() => setInclExclPopup(null)}
        />
      )}

      {/* ── Delete Confirm Modal ── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-red-500" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-800">Delete Deal</h3>
                <p className="text-xs text-gray-500 mt-0.5">This action cannot be undone.</p>
              </div>
            </div>
            <p className="text-xs text-gray-600 mb-6">
              Are you sure you want to delete deal{" "}
              <span className="font-semibold text-gray-800">
                {deleteTarget.airline_name || deleteTarget.deal_no || `#${deleteTarget.id}`}
              </span>?
            </p>
            <div className="flex items-center justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} disabled={deleteLoading}
                className="px-4 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50">
                Cancel
              </button>
              <button onClick={handleDeleteDeal} disabled={deleteLoading}
                className="px-4 py-1.5 rounded-lg bg-red-500 text-white text-xs font-medium hover:bg-red-600 transition-colors disabled:opacity-50 flex items-center gap-1.5">
                {deleteLoading ? (
                  <><RefreshCw className="w-3 h-3 animate-spin" /> Deleting…</>
                ) : (
                  <><Trash2 className="w-3 h-3" /> Delete</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
