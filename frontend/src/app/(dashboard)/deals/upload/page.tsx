"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import {
  Upload, FileText, FileSpreadsheet, File, Check,
  ChevronRight, AlertTriangle, X, RefreshCw, Save,
  Plus, Trash2, ChevronDown, ArrowRight, Info, Settings2, Search,
} from "lucide-react";
import * as XLSX from "xlsx";
import api from "@/lib/api";
import { useRouter } from "next/navigation";

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════════
// Supplier names are fetched live from the supplier master API
const ENTITIES       = ["ATB", "TSI", "YOL"];
const CONTRACT_YEARS = ["Calendar year", "Financial year"];
const TRIGGER_TYPES  = ["Flown", "Sales"];
const PAYOUT_TYPES   = ["Flown", "Sales"];
const BUSINESS_TYPES = ["B2B", "B2C", "B2E", "MICE"];

const INCENTIVE_TYPES = [
  "PLB","Super PLB","Transaction Fee","Deposit Incentive (DI)","Marketing Fund",
  "Ancillary","Frontend","Backend","Cashback","Segment Incentive","Push Action",
];

const INCLUSIONS_EXCLUSIONS = [
  "Inclusion For Trigger","Exclusion For Trigger",
  "Inclusion For Payout","Exclusion For Payout",
];

const CONTINENTS         = ["Africa","Asia","Europe","North America","Oceania","South America","Antarctica"];
const COUNTRY_GROUPS     = ["APAC","EUROPEAN NATIONS","GCC/MIDDLE EAST","LATIN AMERICA","MEAI","MEAI/APAC","MEAI/SAARC","MEAI/SAARC/APAC","NAM","OTHER","SAARC","SAARC/APAC"];
const CITIES             = ["Delhi","Mumbai","Dubai","Doha","London","Frankfurt","New York","Singapore","Sydney"];
const FARE_TYPE_CATS     = ["Normal","Group","Corporate","Excursion","Tour"];
const TOUR_CODES         = ["TC001","TC002","TC003","TC004"];
const DOMESTIC_CTRS      = ["India","UAE","UK","USA","Australia"];
const INCL_CLASS_OPTIONS = ["All","Economy","Premium Economy","Business","First"];
const SOTO_OPTIONS       = ["SOTO All","SOTO within India","SOTO outside India  "];

const FREQUENCY_OPTIONS    = ["Quarterly","Half Yearly","Yearly"];
const FLIGHT_TYPE_OPTIONS  = ["International","Domestic","Both"];
const CLASS_OPTIONS        = ["All","Economy","Premium","Business"];
const TARGET_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
const PAYOUT_CALC_OPTIONS  = ["Basic","Basic + YQ","Basic + YQ +YR","Basic + YR"];
const TARGET_BASED_OPTIONS = ["Amount Based","Segment Based"];

const FIELD_OPTIONS: Record<string,string[]> = {
  frequency:FREQUENCY_OPTIONS, flightType:FLIGHT_TYPE_OPTIONS,
  class:CLASS_OPTIONS,
  targetCalcCols:TARGET_CALC_OPTIONS, payoutCalcCols:PAYOUT_CALC_OPTIONS,
  targetBased:TARGET_BASED_OPTIONS,
  amountBasedType:["Fixed","Slab Based"], segmentBasedType:["Fixed","Slab Based"],
  incentiveNumPct:["Number","Percentage"],
};

const NORMALIZE_ALIASES: Record<string,string> = {
  "yearly":"Yearly","yealy":"Yearly","annual":"Yearly","annually":"Yearly",
  "half yearly":"Half Yearly","halfyearly":"Half Yearly","semi-annual":"Half Yearly","biannual":"Half Yearly","half-yearly":"Half Yearly",
  "quarterly":"Quarterly","quarter":"Quarterly",
  "international":"International","intl":"International","inter":"International",
  "domestic":"Domestic","dom":"Domestic",
  "both":"Both",
  "economy":"Economy","eco":"Economy","econ":"Economy",
  "premium":"Premium","prem":"Premium",
  "business":"Business","biz":"Business","bus":"Business",
  "all":"All",
  "basic":"Basic",
  "b+yq":"Basic + YQ","basic+yq":"Basic + YQ","basic + yq":"Basic + YQ",
  "b+yq+yr":"Basic + YQ +YR","basic+yq+yr":"Basic + YQ +YR","basic + yq +yr":"Basic + YQ +YR",
  "b+yr":"Basic + YR","basic+yr":"Basic + YR","basic + yr":"Basic + YR",
  "amount based":"Amount Based","amount":"Amount Based",
  "segment based":"Segment Based","segment":"Segment Based","segments":"Segment Based",
  "percentage":"Percentage","pct":"Percentage","percent":"Percentage",
  "number":"Number","num":"Number",
  "fixed":"Fixed",
  "slab based":"Slab Based","slab":"Slab Based",
};

function levenshtein(a:string,b:string):number{
  const m=a.length,n=b.length;
  const dp:number[][]=Array.from({length:m+1},(_,i)=>Array.from({length:n+1},(_,j)=>i===0?j:j===0?i:0));
  for(let i=1;i<=m;i++)for(let j=1;j<=n;j++)dp[i][j]=a[i-1]===b[j-1]?dp[i-1][j-1]:1+Math.min(dp[i-1][j],dp[i][j-1],dp[i-1][j-1]);
  return dp[m][n];
}

function normalizeSelectValue(raw:string,options:string[]):string{
  if(!raw)return raw;
  const trimmed=raw.trim();
  if(options.includes(trimmed))return trimmed;
  const lower=trimmed.toLowerCase();
  const ci=options.find(o=>o.toLowerCase()===lower);
  if(ci)return ci;
  const alias=NORMALIZE_ALIASES[lower];
  if(alias&&options.includes(alias))return alias;
  let best=trimmed,bestDist=Infinity;
  for(const opt of options){const d=levenshtein(lower,opt.toLowerCase());if(d<bestDist){bestDist=d;best=opt;}}
  return bestDist<=Math.max(2,Math.floor(best.length*0.4))?best:trimmed;
}

type FieldConfig = {key:string;label:string;type:"date"|"select"|"search"|"number";condition?:{field:string;value:string}};

function payoutFields(n:string):FieldConfig[]{return[
  {key:"amountBasedType",    label:`Amount Based for ${n}`,                    type:"select",condition:{field:"targetBased",value:"Amount Based"}},
  {key:"baseTargetAmount",   label:`Base Target Amount for ${n}`,              type:"number",condition:{field:"targetBased",value:"Amount Based"}},
  {key:"segmentBasedType",   label:`Segment Based for ${n}`,                   type:"select",condition:{field:"targetBased",value:"Segment Based"}},
  {key:"baseTargetSegments", label:`Base Target Segments for ${n}`,            type:"number",condition:{field:"targetBased",value:"Segment Based"}},
  {key:"incentiveNumPct",    label:`Incentive in Number or Percentage for ${n}`,type:"select",condition:{field:"targetBased",value:"__set__"}},
  {key:"incentiveAmtPct",    label:`Incentive Percentage or Amount for ${n}`,  type:"number",condition:{field:"targetBased",value:"__set__"}},
  {key:"cappedIncentive",    label:`Capped Incentive for ${n}`,                type:"number",condition:{field:"targetBased",value:"__set__"}},
];}
function payoutCalcFields(n:string):FieldConfig[]{return[
  {key:"incentiveNumPct",label:`Incentive in Number or Percentage for ${n}`,type:"select",condition:{field:"payoutCalcCols",value:"__set__"}},
  {key:"incentiveAmtPct",label:`Incentive Percentage or Amount for ${n}`,   type:"number",condition:{field:"payoutCalcCols",value:"__set__"}},
  {key:"cappedIncentive",label:`Capped Incentive for ${n}`,                 type:"number",condition:{field:"payoutCalcCols",value:"__set__"}},
];}

// Matches every field in InclExclDetailModal (Exclusion + Inclusion).
// key "_dateExclusion" is a synthetic XLS-only field; extraction expands it to
// dateExclusionTicket / dateExclusionTravel based on the cell value.
const INCL_EXCL_FIELDS: FieldConfig[] = [
  {key:"_dateExclusion",     label:"Date Exclusion",          type:"search"},
  {key:"validFrom",          label:"Valid From",               type:"date"},
  {key:"validTo",            label:"Valid To",                 type:"date"},
  {key:"continents",         label:"Continents",               type:"select"},
  {key:"countryGroup",       label:"Country Group",            type:"select"},
  {key:"originContinents",   label:"Origin Continents",        type:"select"},
  {key:"destContinents",     label:"Destination Continents",   type:"select"},
  {key:"originCountryGroup", label:"Origin Country Group",     type:"select"},
  {key:"destCountryGroup",   label:"Destination Country Group",type:"select"},
  {key:"originCountry",      label:"Origin Country",           type:"search"},
  {key:"destCountry",        label:"Destination Country",      type:"search"},
  {key:"originAirport",      label:"Origin Airport",           type:"search"},
  {key:"destAirport",        label:"Destination Airport",      type:"search"},
  {key:"city",               label:"City",                     type:"search"},
  {key:"fareTypeCategory",   label:"Fare Type Category",       type:"select"},
  {key:"class",              label:"Class",                    type:"select"},
  {key:"soto",               label:"SOTO",                     type:"select"},
  {key:"tourCode",           label:"Tour Code",                type:"search"},
  {key:"domesticCountry",    label:"Domestic Country",         type:"search"},
];

const INCENTIVE_FIELDS:Record<string,FieldConfig[]> = {
  "PLB":[{key:"validFrom",label:"Contract Valid from for PLB",type:"date"},{key:"validTo",label:"Contract Valid to for PLB",type:"date"},{key:"frequency",label:"Frequency for PLB",type:"select"},{key:"flightType",label:"Flight Type for PLB",type:"select"},{key:"class",label:"Class for PLB",type:"search"},{key:"targetCalcCols",label:"Target Calc Columns for PLB",type:"select"},{key:"payoutCalcCols",label:"Payout Calc Columns for PLB",type:"select"},{key:"targetBased",label:"Target Based for PLB",type:"select"},...payoutFields("PLB")],
  "Super PLB":[{key:"validFrom",label:"Contract Valid from for Super PLB",type:"date"},{key:"validTo",label:"Contract Valid to for Super PLB",type:"date"},{key:"frequency",label:"Frequency for Super PLB",type:"select"},{key:"flightType",label:"Flight Type for Super PLB",type:"select"},{key:"class",label:"Class for Super PLB",type:"search"},{key:"targetBased",label:"Target Based for Super PLB",type:"select"},{key:"targetCalcCols",label:"Target Calc Columns for Super PLB",type:"select"},...payoutFields("Super PLB")],
  "Transaction Fee":[{key:"validFrom",label:"Contract Valid from for Transaction Fee",type:"date"},{key:"validTo",label:"Contract Valid to for Transaction Fee",type:"date"},{key:"frequency",label:"Frequency for Transaction Fee",type:"select"},{key:"flightType",label:"Flight Type for Transaction Fee",type:"select"},{key:"class",label:"Class for Transaction Fee",type:"search"},{key:"payoutCalcCols",label:"Payout Calc Columns for Transaction Fee",type:"select"},...payoutCalcFields("Transaction Fee")],
  "Deposit Incentive (DI)":[{key:"validFrom",label:"Contract Valid from for DI",type:"date"},{key:"validTo",label:"Contract Valid to for DI",type:"date"},{key:"frequency",label:"Frequency for DI",type:"select"},{key:"flightType",label:"Flight Type for DI",type:"select"},{key:"targetBased",label:"Target Based for DI",type:"select"},...payoutFields("Deposit Incentive (DI)")],
  "Marketing Fund":[{key:"validFrom",label:"Contract Valid from for Marketing Fund",type:"date"},{key:"validTo",label:"Contract Valid to for Marketing Fund",type:"date"},{key:"frequency",label:"Frequency for Marketing Fund",type:"select"},{key:"flightType",label:"Flight Type for Marketing Fund",type:"select"},{key:"class",label:"Class for Marketing Fund",type:"search"},{key:"payoutCalcCols",label:"Payout Calc Columns for Marketing Fund",type:"select"},...payoutCalcFields("Marketing Fund")],
  "Ancillary":[{key:"validFrom",label:"Contract Valid from for Ancillary",type:"date"},{key:"validTo",label:"Contract Valid to for Ancillary",type:"date"},{key:"flightType",label:"Flight Type for Ancillary",type:"select"},{key:"payoutCalcCols",label:"Payout Calc Columns for Ancillary",type:"select"},...payoutCalcFields("Ancillary")],
  "Frontend":[{key:"validFrom",label:"Contract Valid from for Frontend",type:"date"},{key:"validTo",label:"Contract Valid to for Frontend",type:"date"},{key:"frequency",label:"Frequency for Frontend",type:"select"},{key:"class",label:"Class for Frontend",type:"search"},{key:"targetCalcCols",label:"Target Calc Columns for Frontend",type:"select"},{key:"payoutCalcCols",label:"Payout Calc Columns for Frontend",type:"select"},...payoutCalcFields("Frontend")],
  "Backend":[{key:"validFrom",label:"Contract Valid from for Backend",type:"date"},{key:"validTo",label:"Contract Valid to for Backend",type:"date"},{key:"frequency",label:"Frequency for Backend",type:"select"},{key:"class",label:"Class for Backend",type:"search"},{key:"targetCalcCols",label:"Target Calc Columns for Backend",type:"select"},{key:"payoutCalcCols",label:"Payout Calc Columns for Backend",type:"select"},...payoutCalcFields("Backend")],
  "Cashback":[{key:"validFrom",label:"Contract Valid from for Cashback",type:"date"},{key:"validTo",label:"Contract Valid to for Cashback",type:"date"},{key:"frequency",label:"Frequency for Cashback",type:"select"},{key:"flightType",label:"Flight Type for Cashback",type:"select"},{key:"targetBased",label:"Target Based for Cashback",type:"select"},...payoutFields("Cashback")],
  "Segment Incentive":[{key:"validFrom",label:"Contract Valid from for Segment Incentive",type:"date"},{key:"validTo",label:"Contract Valid to for Segment Incentive",type:"date"},{key:"frequency",label:"Frequency for Segment Incentive",type:"select"},{key:"class",label:"Class for Segment Incentive",type:"search"},{key:"targetCalcCols",label:"Target Calc Columns for Segment Incentive",type:"select"},{key:"payoutCalcCols",label:"Payout Calc Columns for Segment Incentive",type:"select"},...payoutCalcFields("Segment Incentive")],
  "Push Action":[{key:"validFrom",label:"Contract Valid from for Push Action",type:"date"},{key:"validTo",label:"Contract Valid to for Push Action",type:"date"},{key:"frequency",label:"Frequency for Push Action",type:"select"},{key:"flightType",label:"Flight Type for Push Action",type:"select"},{key:"targetBased",label:"Target Based for Push Action",type:"select"},...payoutFields("Push Action")],
};


// ═══════════════════════════════════════════════════════════════════════════════
// COLUMN DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════
const CONTRACT_COLS_ALL = [
  {key:"c__airline_type",  label:"Airline Type"},
  {key:"c__airline_name",  label:"Airline Name"},
  {key:"c__contract_year", label:"Contract Year"},
  {key:"c__business_type", label:"Business Type"},
  {key:"c__valid_from",    label:"Contract Valid From"},
  {key:"c__valid_to",      label:"Contract Valid To"},
  {key:"c__trigger_type",  label:"Trigger Type"},
  {key:"c__payout_type",   label:"Payout Type"},
  {key:"c__entity_lcc",    label:"Entity"},
  {key:"c__login_id",      label:"Login ID"},
];
const B2B_HIDDEN_COLS = ["c__contract_year","c__trigger_type","c__payout_type"];
const REMARKS_COL = {key:"r__remarks", label:"Remarks"};

function getContractCols(dealType:string){
  return dealType === "b2b"
    ? CONTRACT_COLS_ALL.filter(c => !B2B_HIDDEN_COLS.includes(c.key))
    : CONTRACT_COLS_ALL;
}
function incentiveMapCols(inc:string){
  return (INCENTIVE_FIELDS[inc]??[]).map(f=>({
    key:`i__${inc}__${f.key}`,
    label:f.label.replace(` for ${inc}`,"").replace(/ for .*/,"").replace(/ \(.*\)/,""),
  }));
}
function inclExclMapCols(type:string){
  return INCL_EXCL_FIELDS.map(f=>({key:`ie__${type}__${f.key}`,label:f.label}));
}

// ═══════════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════════
type ReviewRow = {
  row_order:number;
  airline_name:string; iata_code:string;
  eco_commission:string; peco_commission:string; bus_commission:string;
  valid_on:string; validity_raw:string; remarks:string;
  extra: Record<string,string>;
};

type RowInclExcl = {
  types:     string[];
  data:      Record<string, Record<string,string>>;
  viceVersa: Record<string, boolean>;
};

type ExtractionPreview = {
  source_type:string; file_name:string; confidence:number;
  warning?:string; rows:Omit<ReviewRow,"extra">[];
  doc_columns:string[];
  raw_rows:Record<string,string>[];
};

type AIDeal = {
  airline_type: string;
  airline_name: string;
  contract_valid_from: string | null;
  contract_valid_to: string | null;
  incentive_types: string[];
  incentive_data: {
    PLB?: {
      validFrom: string | null; validTo: string | null;
      frequency: string; flightType: string; class: string;
      targetCalcCols: string; payoutCalcCols: string;
      targetBased: string | null;
      amountBasedType: string | null; baseTargetAmount: number | null;
      segmentBasedType: string | null; baseTargetSegments: number | null;
      incentiveNumPct: string; incentiveAmtPct: number; cappedIncentive: number | null;
    };
  };
  remark: string;
};

type AIExtractResponse = {
  deals: AIDeal[];
  file_name: string;
  confidence: number;
  warning?: string;
};

function convertAIDealsToRows(deals: AIDeal[]): ReviewRow[] {
  return deals.map((deal, idx) => {
    const plb = deal.incentive_data?.PLB;
    const extra: Record<string, string> = {};
    if (deal.airline_type)          extra["c__airline_type"] = deal.airline_type;
    if (deal.airline_name)          extra["c__airline_name"]  = deal.airline_name;
    if (deal.contract_valid_from)   extra["c__valid_from"]    = deal.contract_valid_from;
    if (deal.contract_valid_to)     extra["c__valid_to"]      = deal.contract_valid_to;
    if (plb) {
      if (plb.validFrom)           extra["inc::PLB::validFrom"]          = plb.validFrom;
      if (plb.validTo)             extra["inc::PLB::validTo"]            = plb.validTo;
      if (plb.frequency)           extra["inc::PLB::frequency"]          = plb.frequency;
      if (plb.flightType)          extra["inc::PLB::flightType"]         = plb.flightType;
      if (plb.class)               extra["inc::PLB::class"]              = plb.class;
      if (plb.targetCalcCols)      extra["inc::PLB::targetCalcCols"]     = plb.targetCalcCols;
      if (plb.payoutCalcCols)      extra["inc::PLB::payoutCalcCols"]     = plb.payoutCalcCols;
      if (plb.targetBased)         extra["inc::PLB::targetBased"]        = plb.targetBased;
      if (plb.amountBasedType)     extra["inc::PLB::amountBasedType"]    = plb.amountBasedType;
      if (plb.baseTargetAmount != null) extra["inc::PLB::baseTargetAmount"]  = String(plb.baseTargetAmount);
      if (plb.segmentBasedType)    extra["inc::PLB::segmentBasedType"]   = plb.segmentBasedType;
      if (plb.baseTargetSegments != null) extra["inc::PLB::baseTargetSegments"] = String(plb.baseTargetSegments);
      if (plb.incentiveNumPct)     extra["inc::PLB::incentiveNumPct"]    = plb.incentiveNumPct;
      if (plb.incentiveAmtPct)     extra["inc::PLB::incentiveAmtPct"]   = String(plb.incentiveAmtPct);
      if (plb.cappedIncentive != null) extra["inc::PLB::cappedIncentive"] = String(plb.cappedIncentive);
    }
    return {
      row_order: idx,
      airline_name: deal.airline_name || "",
      iata_code: "", eco_commission: "", peco_commission: "",
      bus_commission: "", valid_on: "", validity_raw: "",
      remarks: deal.remark || "",
      extra,
    };
  });
}

const EMPTY_ROW = ():ReviewRow => ({
  row_order:0,airline_name:"",iata_code:"",eco_commission:"",
  peco_commission:"",bus_commission:"",valid_on:"",validity_raw:"",remarks:"",
  extra:{},
});

// ═══════════════════════════════════════════════════════════════════════════════
// UI PRIMITIVES
// ═══════════════════════════════════════════════════════════════════════════════
function SelectField({label,placeholder="Select...",options,value,onChange,required}:{label?:string;placeholder?:string;options:string[];value:string;onChange:(v:string)=>void;required?:boolean}){
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))setOpen(false);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[]);
  return(
    <div className="relative" ref={ref}>
      {label&&<label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}{required&&<span className="text-red-400 ml-0.5">*</span>}</label>}
      <button type="button" onClick={()=>setOpen(o=>!o)} className="w-full flex items-center justify-between border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400">
        <span className={value?"text-gray-800":"text-gray-400"}>{value||placeholder}</span>
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

function SearchSelectField({label,placeholder="Search and select",options,value,onChange}:{label?:string;placeholder?:string;options:string[];value:string;onChange:(v:string)=>void}){
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

function MultiCheckboxDropdown({label,placeholder="Select...",options,values,onChange}:{label?:string;placeholder?:string;options:string[];values:string[];onChange:(v:string[])=>void}){
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

function SectionCard({title,children}:{title:string;children:React.ReactNode}){
  return(
    <div className="bg-white rounded-lg border border-gray-200">
      <div className="px-4 py-2.5 border-b border-gray-100">
        <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function FileIcon({name}:{name:string}){
  const ext=name.split(".").pop()?.toLowerCase();
  if(ext==="pdf")return <FileText className="w-5 h-5 text-red-500"/>;
  if(ext==="xlsx"||ext==="xls")return <FileSpreadsheet className="w-5 h-5 text-green-600"/>;
  return <File className="w-5 h-5 text-blue-500"/>;
}

function StepBar({step}:{step:1|2|3|4}){
  const steps=["Upload & Info","Column Mapping","Review & Edit","Done"];
  return(
    <div className="flex items-center gap-0">
      {steps.map((label,i)=>{
        const n=i+1;const done=n<step;const active=n===step;
        return(
          <div key={label} className="flex items-center">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${active?"bg-[#1e3a5f] text-white":done?"bg-green-100 text-green-700":"bg-gray-100 text-gray-400"}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${active?"bg-white text-[#1e3a5f]":done?"bg-green-500 text-white":"bg-gray-300 text-gray-500"}`}>
                {done?<Check className="w-3 h-3"/>:n}
              </div>
              {label}
            </div>
            {i<steps.length-1&&<ChevronRight className="w-4 h-4 text-gray-300 mx-0.5"/>}
          </div>
        );
      })}
    </div>
  );
}

function MultiSelectDropdown({label,options,selected,onChange}:{label?:string;options:string[];selected:string[];onChange:(next:string[])=>void}){
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))setOpen(false);};document.addEventListener("mousedown",h);return()=>document.removeEventListener("mousedown",h);},[]);
  const toggle=(opt:string)=>onChange(selected.includes(opt)?selected.filter(s=>s!==opt):[...selected,opt]);
  return(
    <div className="relative" ref={ref}>
      {label&&<label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>}
      <button type="button" onClick={()=>setOpen(o=>!o)} className="w-full min-h-[32px] flex items-start justify-between border border-gray-200 rounded-md px-2.5 py-1.5 bg-white text-left focus:outline-none focus:ring-1 focus:ring-blue-400 gap-2">
        <div className="flex flex-wrap gap-1 flex-1">
          {selected.length===0
            ?<span className="text-xs text-gray-400 self-center">Select…</span>
            :selected.map(s=>(
              <span key={s} className="inline-flex items-center gap-1 bg-[#1e3a5f] text-white text-[10px] font-semibold px-2 py-0.5 rounded-full">
                {s}<span onClick={e=>{e.stopPropagation();toggle(s);}} className="hover:text-red-300 cursor-pointer leading-none">×</span>
              </span>
            ))
          }
        </div>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-0.5"/>
      </button>
      {open&&(
        <div className="absolute z-50 w-full mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg max-h-52 overflow-y-auto">
          {options.map(opt=>(
            <button key={opt} type="button" onClick={()=>toggle(opt)} className={`w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-blue-50 transition-colors ${selected.includes(opt)?"bg-blue-50/60 text-[#1e3a5f] font-semibold":"text-gray-700"}`}>
              <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${selected.includes(opt)?"bg-[#1e3a5f] border-[#1e3a5f]":"border-gray-300"}`}>
                {selected.includes(opt)&&<Check className="w-2.5 h-2.5 text-white"/>}
              </span>
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// INCL/EXCL DETAIL MODAL
// ═══════════════════════════════════════════════════════════════════════════════
function InclExclDetailModal({
  type,
  initialData,
  onSave,
  onClose,
}:{
  type:string;
  initialData: Record<string,string>;
  onSave:(data:Record<string,string>)=>void;
  onClose:()=>void;
}){
  const [form, setForm] = useState<Record<string,string>>(initialData);
  const isExcl = type.startsWith("Exclusion");
  const suffix  = isExcl ? "for Exclusion" : "for Inclusion";

  const [continentOptions,    setContinentOptions]    = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);
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
      })
      .catch(()=>{});
    api.get<{iata_code:string;country:string|null}[]>("/airports/?limit=5000")
      .then(r=>{
        setAllAirports(r.data.map(a=>a.iata_code).filter(Boolean));
        const countries=[...new Set(r.data.map(a=>a.country).filter(Boolean))] as string[];
        setAllCountries(countries.sort());
      })
      .catch(()=>{});
  },[]);

  const origContinent = form["originContinents"] ?? "";
  const destContinent = form["destContinents"]   ?? "";
  const origCountry   = form["originCountry"]    ?? "";
  const destCountry   = form["destCountry"]      ?? "";

  useEffect(()=>{
    if(!origContinent){setOriginCountries([]);return;}
    api.get<{countries:string[]}>(`/airports/options?continent=${encodeURIComponent(origContinent)}`)
      .then(r=>setOriginCountries(r.data.countries??[]))
      .catch(()=>setOriginCountries([]));
  },[origContinent]);

  useEffect(()=>{
    if(!destContinent){setDestCountries([]);return;}
    api.get<{countries:string[]}>(`/airports/options?continent=${encodeURIComponent(destContinent)}`)
      .then(r=>setDestCountries(r.data.countries??[]))
      .catch(()=>setDestCountries([]));
  },[destContinent]);

  useEffect(()=>{
    if(!origCountry){setOriginAirports([]);return;}
    api.get<{airports:string[]}>(`/airports/options?country=${encodeURIComponent(origCountry)}`)
      .then(r=>setOriginAirports(r.data.airports??[]))
      .catch(()=>setOriginAirports([]));
  },[origCountry]);

  useEffect(()=>{
    if(!destCountry){setDestAirports([]);return;}
    api.get<{airports:string[]}>(`/airports/options?country=${encodeURIComponent(destCountry)}`)
      .then(r=>setDestAirports(r.data.airports??[]))
      .catch(()=>setDestAirports([]));
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
    city:CITIES, fareTypeCategory:FARE_TYPE_CATS,
    class:INCL_CLASS_OPTIONS, tourCode:TOUR_CODES, domesticCountry:DOMESTIC_CTRS,
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
      {key:"originCountry",label:`Origin Country ${suffix}`,placeholder:"Search and select"},
      {key:"destCountry",  label:`Destination Country ${suffix}`,placeholder:"Search and select"},
    ],
    [
      {key:"originAirport",label:`Origin Airport ${suffix}`,placeholder:"Search and select"},
      {key:"destAirport",  label:`Destination Airport ${suffix}`,placeholder:"Search and select"},
    ],
    [{key:"city",label:`City ${suffix}`},{key:"fareTypeCategory",label:`Fare Type Category ${suffix}`}],
    [
      {key:"class",label:`Class ${suffix}`},
      isExcl
        ?{key:"soto",label:"SOTO for Exclusion",isSelect:true,options:SOTO_OPTIONS}
        :{key:"tourCode",label:`Tour Code ${suffix}`},
    ],
    ...(isExcl
      ?[[{key:"tourCode",label:`Tour Code ${suffix}`},{key:"domesticCountry",label:`Domestic Country ${suffix}`}]]
      :[[{key:"domesticCountry",label:`Domestic Country ${suffix}`}]]
    ),
  ];

  return(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Configure — {type}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Fill the applicable fields for this rule</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500"/></button>
        </div>
        <div className="overflow-y-auto flex-1 p-5 space-y-3">
          <div className="grid gap-3 grid-cols-1 max-w-[50%]">
            <MultiCheckboxDropdown
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
                    <SelectField label={f.label} options={f.options??[]} value={form[f.key]??""} onChange={v=>handleChange(f.key,v)}/>
                  ):(
                    <SearchSelectField label={f.label} placeholder={f.placeholder} options={opts[f.key]??[]} value={form[f.key]??""} onChange={v=>handleChange(f.key,v)}/>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="flex gap-3 px-5 py-3.5 border-t border-gray-100">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm font-medium hover:bg-gray-50">Cancel</button>
          <button onClick={()=>onSave(form)} className="flex-1 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-semibold hover:bg-[#16304f]">Save →</button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// INCL/EXCL POPUP (checkbox panel per row)
// ═══════════════════════════════════════════════════════════════════════════════
function InclExclPopup({
  rowIdx,
  rowState,
  onToggleType,
  onOpenType,
  onRemoveType,
  onClose,
}:{
  rowIdx:number;
  rowState: RowInclExcl;
  onToggleType:(type:string)=>void;
  onOpenType:(type:string)=>void;
  onRemoveType:(type:string)=>void;
  onClose:()=>void;
}){
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const h=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node))onClose();};
    document.addEventListener("mousedown",h);
    return()=>document.removeEventListener("mousedown",h);
  },[onClose]);

  return(
    <div ref={ref} className="absolute z-40 top-full mt-1 right-0 bg-white border border-gray-200 rounded-xl shadow-xl p-3 w-64">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wide mb-2">Inclusions &amp; Exclusions</p>
      {INCLUSIONS_EXCLUSIONS.map(type=>{
        const isSelected=rowState.types.includes(type);
        return(
          <div key={type} className="flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-blue-50">
            <button
              onClick={()=>isSelected?onOpenType(type):onToggleType(type)}
              className="flex items-center gap-2 flex-1 text-left"
            >
              <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${isSelected?"bg-[#1e3a5f] border-[#1e3a5f]":"border-gray-300"}`}>
                {isSelected&&<Check className="w-2.5 h-2.5 text-white"/>}
              </span>
              <span className={`text-[11px] ${isSelected?"text-[#1e3a5f] font-semibold":"text-gray-700"}`}>{type}</span>
            </button>
            {isSelected&&(
              <button onClick={()=>onRemoveType(type)} className="p-0.5 hover:bg-red-50 rounded text-red-400 flex-shrink-0" title="Remove">
                <X className="w-3 h-3"/>
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// STEP 2 — COLUMN MAPPING
// ═══════════════════════════════════════════════════════════════════════════════
function ColumnMappingStep({
  preview, columnMap, onMapChange, selectedIncentives, selectedInclExcl, dealType, onConfirm, onBack
}:{
  preview:ExtractionPreview;
  columnMap:Record<string,string>;
  onMapChange:(ourKey:string,docCol:string)=>void;
  selectedIncentives:string[];
  selectedInclExcl:string[];
  dealType:string;
  onConfirm:(contract:Record<string,string>,rows:ReviewRow[],rowInclExcl:Record<number,RowInclExcl>)=>void;
  onBack:()=>void;
}){
  const docCols:string[] = preview.doc_columns?.length
    ? preview.doc_columns
    : (preview.rows[0] ? Object.keys(preview.rows[0]).filter(k=>k!=="row_order") : []);
  const rawRows = preview.raw_rows?.length ? preview.raw_rows : [];
  const contractCols = getContractCols(dealType);

  // Normalize a raw cell value to YYYY-MM-DD for date inputs
  const toDateStr=(v:string):string=>{
    if(!v)return v;
    // Already YYYY-MM-DD
    if(/^\d{4}-\d{2}-\d{2}$/.test(v.trim()))return v.trim();
    // YYYY-MM-DD HH:MM:SS or YYYY-MM-DDTHH:MM:SS
    const m=v.trim().match(/^(\d{4}-\d{2}-\d{2})[T ]?/);
    if(m)return m[1];
    // Fallback: try Date parse
    try{const d=new Date(v);if(!isNaN(d.getTime()))return d.toISOString().split("T")[0];}catch{}
    return v;
  };

  const applyAndContinue=()=>{
    const cellVal=(row:Record<string,string>,docCol:string)=>(row[docCol]??"").trim();
    // Extract contract-level values from first data row (used as global fallback)
    const contract:Record<string,string>={};
    for(const col of contractCols){
      const dc=columnMap[col.key];
      if(dc){for(const row of rawRows){let v=cellVal(row,dc);if(v){if(col.key==="c__valid_from"||col.key==="c__valid_to")v=toDateStr(v);contract[col.key]=v;break;}}}
    }
    // Use rawRows as primary row source so XLS uploads (where preview.rows may be empty) still work
    const rowCount=Math.max(preview.rows.length,rawRows.length);
    const rows:ReviewRow[]=Array.from({length:rowCount},(_,i)=>{
      const base=preview.rows[i]??EMPTY_ROW();
      const rawRow=rawRows[i];
      const extra:Record<string,string>={};
      // Per-row contract column values extracted from rawRow
      if(rawRow){
        for(const col of contractCols){
          const dc=columnMap[col.key];
          if(dc){let v=cellVal(rawRow,dc);if(v){if(col.key==="c__valid_from"||col.key==="c__valid_to")v=toDateStr(v);extra[col.key]=v;}}
        }
      }
      // Per-row incentive column values
      for(const inc of selectedIncentives){
        for(const f of INCENTIVE_FIELDS[inc]??[]){
          const colKey=`i__${inc}__${f.key}`;
          const dc=columnMap[colKey];
          if(dc&&rawRow){let v=cellVal(rawRow,dc);if(v){if(f.type==="date")v=toDateStr(v);else{const opts=FIELD_OPTIONS[f.key];if(opts)v=normalizeSelectValue(v,opts);}extra[`inc::${inc}::${f.key}`]=v;}}
        }
      }
      const remDc=columnMap[REMARKS_COL.key];
      const remVal=remDc&&rawRow?cellVal(rawRow,remDc):base.remarks;
      return{...base,row_order:i,remarks:remVal||base.remarks,extra};
    });
    // Extract incl/excl column values per row from XLS
    const rowInclExclFromXLS:Record<number,RowInclExcl>={};
    for(let i=0;i<rowCount;i++){
      const rawRow=rawRows[i];
      if(!rawRow)continue;
      const inclExclData:Record<string,Record<string,string>>={};
      for(const type of selectedInclExcl){
        for(const f of INCL_EXCL_FIELDS){
          const colKey=`ie__${type}__${f.key}`;
          const dc=columnMap[colKey];
          if(dc){let v=cellVal(rawRow,dc);if(v){
            if(f.type==="date")v=toDateStr(v);
            if(!inclExclData[type])inclExclData[type]={};
            if(f.key==="_dateExclusion"){
              // Expand combined column into two bool flags
              const lower=v.toLowerCase();
              if(lower.includes("ticket"))inclExclData[type]["dateExclusionTicket"]="true";
              if(lower.includes("travel"))inclExclData[type]["dateExclusionTravel"]="true";
            }else{
              inclExclData[type][f.key]=v;
            }
          }}
        }
      }
      const types=Object.keys(inclExclData).filter(t=>Object.keys(inclExclData[t]).length>0);
      if(types.length>0)rowInclExclFromXLS[i]={types,data:inclExclData,viceVersa:{}};
    }
    onConfirm(contract,rows,rowInclExclFromXLS);
  };

  const groups=[
    {label:"Airline Contract Details",cols:contractCols},
    ...selectedIncentives.map(inc=>({label:`Incentive Types — ${inc}`,cols:incentiveMapCols(inc)})),
    ...selectedInclExcl.map(type=>({label:`Incl/Excl — ${type}`,cols:inclExclMapCols(type)})),
    {label:"Remarks",cols:[REMARKS_COL]},
  ];

  return(
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center"><ArrowRight className="w-4 h-4 text-blue-600"/></div>
          <div>
            <h2 className="text-sm font-bold text-gray-800">Column Mapping</h2>
            <p className="text-xs text-gray-500 mt-0.5">Match your document&apos;s column headers to our system fields.</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5 text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded-lg px-2.5 py-1.5">
            <Info className="w-3.5 h-3.5"/>
            {preview.rows.length} rows · {Math.round(preview.confidence*100)}% confidence
          </div>
        </div>

        <div className="p-4 space-y-5">
          {groups.map(group=>(
            <div key={group.label}>
              <p className="text-[11px] font-bold text-[#1e3a5f] uppercase tracking-wide mb-2 pb-1 border-b border-gray-100">{group.label}</p>
              <div className="grid grid-cols-2 gap-3 px-3 mb-1">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Our System Field</p>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Document Column</p>
              </div>
              <div className="space-y-1">
                {group.cols.map(col=>(
                  <div key={col.key} className="grid grid-cols-2 gap-3 items-center bg-gray-50/40 rounded-lg px-3 py-1.5 border border-gray-100 hover:border-blue-200 transition-colors">
                    <span className="text-xs font-medium text-gray-700">{col.label}</span>
                    <div className="flex items-center gap-2">
                      <select value={columnMap[col.key]??""} onChange={e=>onMapChange(col.key,e.target.value)}
                        className="flex-1 border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
                        <option value="">— not found in document —</option>
                        {docCols.map(dc=><option key={dc} value={dc}>{dc}</option>)}
                      </select>
                      {columnMap[col.key]?<Check className="w-3.5 h-3.5 text-green-500 flex-shrink-0"/>:<span className="w-3.5 h-3.5 flex-shrink-0"/>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {rawRows.length>0&&docCols.length>0&&(
          <div className="px-4 pb-4">
            <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Sample document data (first 3 rows)</p>
            <div className="overflow-x-auto border border-gray-200 rounded-lg">
              <table className="w-full min-w-max">
                <thead><tr style={{background:"#1e3a5f"}}>
                  {docCols.map(c=><th key={c} className="px-2.5 py-1.5 text-left text-[10px] font-semibold text-white whitespace-nowrap">{c}</th>)}
                </tr></thead>
                <tbody>
                  {rawRows.slice(0,3).map((row,i)=>(
                    <tr key={i} className={i%2===0?"bg-white":"bg-gray-50/40"}>
                      {docCols.map(c=><td key={c} className="px-2.5 py-1.5 text-[11px] text-gray-700 max-w-32 truncate">{row[c]??"—"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="px-4 pb-4 flex gap-3">
          <button onClick={onBack} className="border border-gray-200 text-gray-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50">← Back</button>
          <button onClick={applyAndContinue} className="flex-1 bg-[#1e3a5f] text-white px-6 py-2.5 rounded-lg text-sm font-semibold hover:bg-[#16304f] flex items-center justify-center gap-2">
            <ArrowRight className="w-4 h-4"/> Apply Mapping &amp; Review
          </button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// STEP 3 — REVIEW TABLE
// ═══════════════════════════════════════════════════════════════════════════════
// Dropdown options for contract-level table cells
const CONTRACT_COL_OPTIONS: Record<string, string[]> = {
  "c__airline_type":  ["GDS","LCC"],
  "c__contract_year": CONTRACT_YEARS,
  "c__trigger_type":  TRIGGER_TYPES,
  "c__payout_type":   PAYOUT_TYPES,
  "c__business_type": BUSINESS_TYPES,
};

// Render config for incentive sub-field cells (keyed by field key inside inc::{})
const INC_FIELD_CELL: Record<string, {type:"select"|"number"|"date"; options?:string[]}> = {
  validFrom:          {type:"date"},
  validTo:            {type:"date"},
  frequency:          {type:"select", options:FREQUENCY_OPTIONS},
  flightType:         {type:"select", options:FLIGHT_TYPE_OPTIONS},
  class:              {type:"select", options:CLASS_OPTIONS},
  targetCalcCols:     {type:"select", options:TARGET_CALC_OPTIONS},
  payoutCalcCols:     {type:"select", options:PAYOUT_CALC_OPTIONS},
  targetBased:        {type:"select", options:TARGET_BASED_OPTIONS},
  amountBasedType:    {type:"select", options:["Fixed","Slab Based"]},
  baseTargetAmount:   {type:"number"},
  segmentBasedType:   {type:"select", options:["Fixed","Slab Based"]},
  baseTargetSegments: {type:"number"},
  incentiveNumPct:    {type:"select", options:["Number","Percentage"]},
  incentiveAmtPct:    {type:"number"},
  cappedIncentive:    {type:"number"},
};

const CELL_PLACEHOLDER: Record<string, string> = {
  "c__airline_type":  "GDS / LCC",
  "c__airline_name":  "e.g. Emirates (EK)",
  "c__contract_year": "Calendar / Financial year",
  "c__valid_from":    "",
  "c__valid_to":      "",
  "c__trigger_type":  "Flown / Sales",
  "c__payout_type":   "Flown / Sales",
  "c__entity_lcc":    "ATB / TSI / YOL",
  "c__business_type": "B2B / B2C / B2E",
  "c__login_id":      "Agent login ID",
  "airline_name":     "Airline name",
  "iata_code":        "IATA code",
  "eco_commission":   "ECO %",
  "peco_commission":  "P.ECO %",
  "bus_commission":   "BUS %",
  "valid_on":         "e.g. MON,WED",
  "validity_raw":     "e.g. 01 Jan – 31 Mar",
  "remarks":          "Enter remarks",
};

type ColGroup={label:string;color:string;cols:{key:string;label:string}[]};

function getColMeta(key:string):{type:"date"|"select"|"number"|"text";options?:string[]}{
  if(key==="c__valid_from"||key==="c__valid_to")return{type:"date"};
  if(key==="c__entity_lcc")return{type:"select",options:ENTITIES};
  if(CONTRACT_COL_OPTIONS[key])return{type:"select",options:CONTRACT_COL_OPTIONS[key]};
  if(key.startsWith("inc::")){const fk=key.split("::")[2];const cfg=INC_FIELD_CELL[fk];if(cfg)return{type:cfg.type,options:cfg.options};}
  return{type:"text"};
}

function buildColGroups(selectedIncentives:string[], dealType:string):ColGroup[]{
  const contractCols = getContractCols(dealType);
  const groups:ColGroup[]=[
    {label:"Airline Contract Details",color:"#1e3a5f",cols:contractCols},
  ];
  for(const inc of selectedIncentives){
    groups.push({
      label:`Incentive Types — ${inc}`,color:"#4f46e5",
      cols:(INCENTIVE_FIELDS[inc]??[]).map(f=>({
        key:`inc::${inc}::${f.key}`,
        label:f.label.replace(` for ${inc}`,"").replace(/ for .*/,"").replace(/ \(.*\)/,""),
      })),
    });
  }
  groups.push({label:"Remarks",color:"#64748b",cols:[{key:"remarks",label:"Remarks"}]});
  groups.push({label:"Incl / Excl",color:"#059669",cols:[{key:"__incl_excl__",label:"Incl / Excl"}]});
  return groups;
}

function ReviewTable({
  rows, colGroups, onChange, onDelete, onAdd,
  rowInclExcl, inclExclPopup, setInclExclPopup, onToggleInclExclType,
  onOpenInclExclType, onRemoveInclExclType,
  filterText, selectedRows, onToggleRow, onToggleAllFiltered,
}:{
  rows:ReviewRow[];
  colGroups:ColGroup[];
  onChange:(idx:number,key:string,val:string)=>void;
  onDelete:(idx:number)=>void;
  onAdd:()=>void;
  rowInclExcl:Record<number,RowInclExcl>;
  inclExclPopup:number|null;
  setInclExclPopup:(idx:number|null)=>void;
  onToggleInclExclType:(rowIdx:number,type:string)=>void;
  onOpenInclExclType:(rowIdx:number,type:string)=>void;
  onRemoveInclExclType:(rowIdx:number,type:string)=>void;
  filterText:string;
  selectedRows:Set<number>;
  onToggleRow:(idx:number)=>void;
  onToggleAllFiltered:(filteredIndices:number[],allSelected:boolean)=>void;
}){
  const allCols=colGroups.flatMap(g=>g.cols);
  const inp="w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[80px]";

  const getCellValue=(row:ReviewRow,key:string):string=>{
    if(key.startsWith("inc::")||key.startsWith("ie::")||key.startsWith("c__"))return row.extra[key]??"";
    return (row as unknown as Record<string,string>)[key]??"";
  };

  const renderCell=(row:ReviewRow,idx:number,colKey:string)=>{
    // Special: Incl/Excl column
    if(colKey==="__incl_excl__"){
      const state=rowInclExcl[idx];
      const hasConfig=state&&state.types.length>0;
      return(
        <td key={colKey} className="px-1 py-1 border-l border-gray-100 relative">
          <div className="relative">
            <button
              onClick={()=>setInclExclPopup(inclExclPopup===idx?null:idx)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-colors ${hasConfig?"bg-green-100 text-green-700 border-green-300":"bg-gray-100 text-gray-500 border-gray-200 hover:border-emerald-300 hover:text-emerald-700"}`}
            >
              {hasConfig?<><Check className="w-2.5 h-2.5"/>{state.types.length} type{state.types.length>1?"s":""}</>:<><Settings2 className="w-2.5 h-2.5"/>Add</>}
            </button>
            {inclExclPopup===idx&&(
              <InclExclPopup
                rowIdx={idx}
                rowState={state?? {types:[],data:{},viceVersa:{}}}
                onToggleType={(type)=>onToggleInclExclType(idx,type)}
                onOpenType={(type)=>onOpenInclExclType(idx,type)}
                onRemoveType={(type)=>onRemoveInclExclType(idx,type)}
                onClose={()=>setInclExclPopup(null)}
              />
            )}
          </div>
        </td>
      );
    }

    const sel = "w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[80px] border-0";
    const val = getCellValue(row,colKey);
    const change = (v:string)=>onChange(idx,colKey,v);

    // Entity dropdown
    if(colKey==="c__entity_lcc"){
      return(
        <td key={colKey} className="px-1 py-1 border-l border-gray-100">
          <select value={val} onChange={e=>change(e.target.value)} className={sel}>
            <option value="">—</option>
            {ENTITIES.map(e=><option key={e} value={e}>{e}</option>)}
          </select>
        </td>
      );
    }

    // Contract col dropdowns (airline type, contract year, trigger/payout type, business type)
    if(CONTRACT_COL_OPTIONS[colKey]){
      return(
        <td key={colKey} className="px-1 py-1 border-l border-gray-100">
          <select value={val} onChange={e=>change(e.target.value)} className={sel}>
            <option value="">—</option>
            {CONTRACT_COL_OPTIONS[colKey].map(o=><option key={o} value={o}>{o}</option>)}
          </select>
        </td>
      );
    }

    // Date cells (contract valid from/to)
    if(colKey==="c__valid_from"||colKey==="c__valid_to"){
      return(
        <td key={colKey} className="px-1 py-1 border-l border-gray-100">
          <input type="date" className={inp} value={val} onChange={e=>change(e.target.value)}/>
        </td>
      );
    }

    // Incentive sub-field cells: inc::{IncName}::{fieldKey}
    if(colKey.startsWith("inc::")){
      const fieldKey = colKey.split("::")[2];
      const cfg = INC_FIELD_CELL[fieldKey];
      if(cfg){
        if(cfg.type==="date") return(
          <td key={colKey} className="px-1 py-1 border-l border-gray-100">
            <input type="date" className={inp} value={val} onChange={e=>change(e.target.value)}/>
          </td>
        );
        if(cfg.type==="number") return(
          <td key={colKey} className="px-1 py-1 border-l border-gray-100">
            <input type="number" className={inp} value={val} onChange={e=>change(e.target.value)} placeholder="0"/>
          </td>
        );
        if(cfg.type==="select"&&cfg.options) return(
          <td key={colKey} className="px-1 py-1 border-l border-gray-100">
            <select value={val} onChange={e=>change(e.target.value)} className={sel}>
              <option value="">—</option>
              {cfg.options.map(o=><option key={o} value={o}>{o}</option>)}
            </select>
          </td>
        );
      }
    }

    // Default text input
    return(
      <td key={colKey} className="px-1 py-1 border-l border-gray-100">
        <input
          className={inp}
          value={val}
          onChange={e=>change(e.target.value)}
          placeholder={CELL_PLACEHOLDER[colKey]??"—"}
        />
      </td>
    );
  };

  // Filter rows by search text
  const filteredIndices:number[]=rows.reduce<number[]>((acc,row,i)=>{
    if(!filterText){acc.push(i);return acc;}
    const haystack=[row.airline_name,row.remarks,row.validity_raw,...Object.values(row.extra)].join(" ").toLowerCase();
    if(haystack.includes(filterText.toLowerCase()))acc.push(i);
    return acc;
  },[]);
  const allFilteredSelected=filteredIndices.length>0&&filteredIndices.every(i=>selectedRows.has(i));
  const someFilteredSelected=filteredIndices.some(i=>selectedRows.has(i));

  return(
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="w-full min-w-max border-collapse">
        <thead>
          <tr>
            {/* Select-all checkbox */}
            <th className="px-2 py-2 sticky left-0 z-10" style={{background:"#1e3a5f"}}>
              <input
                type="checkbox"
                checked={allFilteredSelected}
                ref={el=>{if(el)el.indeterminate=!allFilteredSelected&&someFilteredSelected;}}
                onChange={()=>onToggleAllFiltered(filteredIndices,allFilteredSelected)}
                className="accent-blue-400 cursor-pointer"
                title={allFilteredSelected?"Deselect all visible":"Select all visible"}
              />
            </th>
            <th className="px-2 py-2 text-[10px] text-white font-semibold sticky left-9 z-10 whitespace-nowrap" style={{background:"#1e3a5f"}}>#</th>
            {colGroups.map(g=>(
              <th key={g.label} colSpan={g.cols.length} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{background:g.color}}>
                {g.label}
              </th>
            ))}
            <th className="px-2 py-2" style={{background:"#1e3a5f"}}/>
          </tr>
          <tr style={{background:"#2d4f7c"}}>
            <th className="px-2 py-1.5 sticky left-0 z-10" style={{background:"#2d4f7c"}}/>
            <th className="px-2 py-1.5 sticky left-9 z-10" style={{background:"#2d4f7c"}}/>
            {allCols.map(c=>(
              <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{c.label}</th>
            ))}
            <th className="px-2 py-1.5"/>
          </tr>
        </thead>
        <tbody>
          {filteredIndices.length===0?(
            <tr><td colSpan={allCols.length+3} className="px-4 py-10 text-center text-xs text-gray-400">
              {rows.length===0?"No rows extracted. Add a row manually.":"No rows match the filter."}
            </td></tr>
          ):filteredIndices.map(idx=>{
            const row=rows[idx];
            const isSelected=selectedRows.has(idx);
            return(
              <tr key={idx} className={`border-b border-gray-100 group ${isSelected?"bg-blue-50":"hover:bg-blue-50/20"}`}>
                <td className={`px-2 py-1.5 sticky left-0 ${isSelected?"bg-blue-50":"bg-white group-hover:bg-blue-50/20"}`}>
                  <input type="checkbox" checked={isSelected} onChange={()=>onToggleRow(idx)} className="accent-blue-500 cursor-pointer"/>
                </td>
                <td className={`px-2 py-1.5 text-[10px] text-gray-400 sticky left-9 ${isSelected?"bg-blue-50":"bg-white group-hover:bg-blue-50/20"}`}>{idx+1}</td>
                {allCols.map(c=>renderCell(row,idx,c.key))}
                <td className="px-2 py-1.5">
                  <button onClick={()=>onDelete(idx)} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded text-red-400"><Trash2 className="w-3.5 h-3.5"/></button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="px-4 py-2.5 border-t border-gray-100">
        <button onClick={onAdd} className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline">
          <Plus className="w-3.5 h-3.5"/> Add row manually
        </button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// XLS TEMPLATE GENERATOR
// ═══════════════════════════════════════════════════════════════════════════════
// Template uses CONTRACT_COLS_ALL labels exactly + full incentive labels (e.g. "Contract Valid from for PLB")
// so that initColumnMap can auto-match them without case-insensitive collisions.
function downloadXLSTemplate(incentiveTypes: string[], inclExclTypes: string[]){
  const contractHeaders = CONTRACT_COLS_ALL.map(c => c.label);
  // Use FULL INCENTIVE_FIELDS labels (not stripped) to avoid collision with contract col labels
  const incentiveHeaders = incentiveTypes.flatMap(inc =>
    (INCENTIVE_FIELDS[inc]??[]).map(f => f.label)
  );
  const inclExclHeaders = inclExclTypes.flatMap(type =>
    INCL_EXCL_FIELDS.map(f => `${f.label} for ${type}`)
  );
  const headers = [...contractHeaders, ...incentiveHeaders, ...inclExclHeaders, REMARKS_COL.label];

  const sampleRow = [
    "GDS","Airline Name","Calendar year","B2C",
    "2025-01-01","2025-12-31","Sales","Sales","ATB","",
    ...incentiveTypes.flatMap(inc => (INCENTIVE_FIELDS[inc]??[]).map(() => "")),
    ...inclExclTypes.flatMap(() => INCL_EXCL_FIELDS.map(() => "")),
    "",
  ];
  const ws = XLSX.utils.aoa_to_sheet([headers, sampleRow]);
  ws["!cols"] = headers.map(h => ({ wch: Math.max(h.length + 2, 14) }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Deal Template");
  XLSX.writeFile(wb, "deal_template.xlsx");
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════════
export default function UploadDealPage(){
  const router=useRouter();
  const [step,setStep]=useState<1|2|3|4>(1);

  // ── Step 1 state ────────────────────────────────────────────────────────────
  const [dealType,      setDealType]      = useState("");           // "airline" | "b2b"
  const [supplierName,  setSupplierName]  = useState("");
  const [supplierOptions, setSupplierOptions] = useState<string[]>([]);
  const [validFromDate, setValidFromDate] = useState("");
  const [file,          setFile]          = useState<File|null>(null);
  const [dragging,     setDragging]     = useState(false);
  const [uploading,    setUploading]    = useState(false);
  const [uploadError,  setUploadError]  = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [selectedIncentives, setSelectedIncentives] = useState<string[]>([]);
  const [selectedInclExcl,   setSelectedInclExcl]   = useState<string[]>([]);

  // ── Step 2 state ────────────────────────────────────────────────────────────
  const [preview,   setPreview]   = useState<ExtractionPreview|null>(null);
  const [columnMap, setColumnMap] = useState<Record<string,string>>({});

  const initColumnMap=(p:ExtractionPreview)=>{
    const docCols=p.doc_columns?.length?p.doc_columns:(p.rows[0]?Object.keys(p.rows[0]).filter(k=>k!=="row_order"):[]);
    const auto:Record<string,string>={};
    // Auto-map contract columns by exact label match
    for(const col of getContractCols(dealType)){
      const match=docCols.find(dc=>dc.toLowerCase().trim()===col.label.toLowerCase());
      if(match)auto[col.key]=match;
    }
    // Auto-map incentive columns — try stripped label first, then full original label
    for(const inc of selectedIncentives){
      for(const col of incentiveMapCols(inc)){
        const fullLabel=(INCENTIVE_FIELDS[inc]??[]).find(f=>`i__${inc}__${f.key}`===col.key)?.label??col.label;
        const match=docCols.find(dc=>
          dc.toLowerCase().trim()===col.label.toLowerCase()||
          dc.toLowerCase().trim()===fullLabel.toLowerCase()
        );
        if(match)auto[col.key]=match;
      }
    }
    // Auto-map incl/excl columns by full label "Field for Type"
    for(const type of selectedInclExcl){
      for(const f of INCL_EXCL_FIELDS){
        const colKey=`ie__${type}__${f.key}`;
        const fullLabel=`${f.label} for ${type}`;
        const match=docCols.find(dc=>dc.toLowerCase().trim()===fullLabel.toLowerCase());
        if(match)auto[colKey]=match;
      }
    }
    // Remarks: try exact label, then common synonyms
    const remMatch=docCols.find(dc=>
      dc.toLowerCase().trim()===REMARKS_COL.label.toLowerCase()||
      ["remark","conditions"].includes(dc.toLowerCase().trim())
    );
    if(remMatch)auto[REMARKS_COL.key]=remMatch;
    setColumnMap(auto);
    setPreview(p);
  };

  // ── AI Mode state ───────────────────────────────────────────────────────────
  const [aiMode,       setAiMode]       = useState(false);
  const [aiFileName,   setAiFileName]   = useState("");
  const [aiConfidence, setAiConfidence] = useState(0);

  // ── Step 3 state ────────────────────────────────────────────────────────────
  const [rows,          setRows]          = useState<ReviewRow[]>([]);
  const [rowInclExcl,   setRowInclExcl]   = useState<Record<number,RowInclExcl>>({});
  const [inclExclPopup, setInclExclPopup] = useState<number|null>(null);
  const [inclExclModal, setInclExclModal] = useState<{rowIdx:number;type:string}|null>(null);
  const [saving,        setSaving]        = useState(false);
  const [saveError,     setSaveError]     = useState("");
  const [filterText,    setFilterText]    = useState("");
  const [selectedRows,  setSelectedRows]  = useState<Set<number>>(new Set());
  const [bulkColKey,    setBulkColKey]    = useState("");
  const [bulkColValue,  setBulkColValue]  = useState("");
  const [savedBatchId,  setSavedBatchId]  = useState<string|null>(null);

  useEffect(()=>{
    api.get<{id:number;name:string}[]>("/suppliers/?limit=5000")
      .then(r=>setSupplierOptions(r.data.map(s=>s.name)))
      .catch(()=>{});
  },[]);

  const colGroups = buildColGroups(selectedIncentives, dealType);

  // ── Row incl/excl helpers ──────────────────────────────────────────────────
  const getOrInitRowInclExcl=(idx:number):RowInclExcl=>(
    rowInclExcl[idx]??{types:[],data:{},viceVersa:{}}
  );

  const handleToggleInclExclType=useCallback((rowIdx:number,type:string)=>{
    const state=getOrInitRowInclExcl(rowIdx);
    const alreadySelected=state.types.includes(type);
    if(alreadySelected){
      // Remove type
      const next={
        types:state.types.filter(t=>t!==type),
        data:{...state.data},
        viceVersa:{...state.viceVersa},
      };
      delete next.data[type];
      delete next.viceVersa[type];
      setRowInclExcl(p=>({...p,[rowIdx]:next}));
    }else{
      // Add type → open modal for details
      setRowInclExcl(p=>({...p,[rowIdx]:{...state,types:[...state.types,type]}}));
      setInclExclPopup(null);
      setInclExclModal({rowIdx,type});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[rowInclExcl]);

  const handleInclExclModalSave=(data:Record<string,string>)=>{
    if(!inclExclModal)return;
    const {rowIdx,type}=inclExclModal;
    setRowInclExcl(p=>{
      const state=p[rowIdx]??{types:[],data:{},viceVersa:{}};
      return{...p,[rowIdx]:{...state,data:{...state.data,[type]:data}}};
    });
    setInclExclModal(null);
  };

  const handleOpenInclExclType=useCallback((rowIdx:number,type:string)=>{
    setInclExclPopup(null);
    setInclExclModal({rowIdx,type});
  },[]);

  const handleRemoveInclExclType=useCallback((rowIdx:number,type:string)=>{
    setRowInclExcl(p=>{
      const state=p[rowIdx]??{types:[],data:{},viceVersa:{}};
      const next={types:state.types.filter(t=>t!==type),data:{...state.data},viceVersa:{...state.viceVersa}};
      delete next.data[type];delete next.viceVersa[type];
      return{...p,[rowIdx]:next};
    });
  },[]);

  // ── Table row helpers ──────────────────────────────────────────────────────
  const handleRowChange=useCallback((idx:number,key:string,val:string)=>{
    setRows(prev=>prev.map((r,i)=>{
      if(i!==idx)return r;
      if(key.startsWith("inc::")||key.startsWith("ie::")||key.startsWith("c__"))
        return{...r,extra:{...r.extra,[key]:val}};
      return{...r,[key]:val};
    }));
  },[]);
  const handleDeleteRow=useCallback((idx:number)=>setRows(prev=>prev.filter((_,i)=>i!==idx)),[]);
  const handleAddRow=()=>{
    const newIdx=rows.length;
    setRows(prev=>[...prev,{...EMPTY_ROW(),row_order:prev.length}]);
    if(selectedInclExcl.length>0){
      setRowInclExcl(prev=>({...prev,[newIdx]:{types:selectedInclExcl,data:{},viceVersa:{}}}));
    }
  };

  // ── Filter + bulk edit helpers ─────────────────────────────────────────────
  const handleToggleRow=useCallback((idx:number)=>{
    setSelectedRows(prev=>{const next=new Set(prev);next.has(idx)?next.delete(idx):next.add(idx);return next;});
  },[]);
  const handleToggleAllFiltered=useCallback((filteredIndices:number[],allSelected:boolean)=>{
    setSelectedRows(prev=>{const next=new Set(prev);if(allSelected)filteredIndices.forEach(i=>next.delete(i));else filteredIndices.forEach(i=>next.add(i));return next;});
  },[]);
  const handleBulkApply=()=>{
    if(!bulkColKey||bulkColValue==="")return;
    setRows(prev=>prev.map((r,i)=>{
      if(!selectedRows.has(i))return r;
      if(bulkColKey.startsWith("inc::")||bulkColKey.startsWith("ie::")||bulkColKey.startsWith("c__"))
        return{...r,extra:{...r.extra,[bulkColKey]:bulkColValue}};
      return{...r,[bulkColKey]:bulkColValue};
    }));
    setBulkColValue("");
  };

  // ── Step 1 → 2/3: Extract ───────────────────────────────────────────────────
  const handleExtract=async()=>{
    if(!file){setUploadError("Please select a file.");return;}
    if(!dealType){setUploadError("Please select a deal type.");return;}
    if(dealType==="b2b"&&!supplierName){setUploadError("Please select a supplier name for B2B deal.");return;}
    setUploading(true);setUploadError("");
    try{
      const form=new FormData();form.append("file",file);
      if(aiMode){
        if(validFromDate) form.append("valid_from",validFromDate);
        const {data}=await api.post<AIExtractResponse>("/deals/upload/ai-extract",form,{headers:{"Content-Type":"multipart/form-data"}});
        const converted=convertAIDealsToRows(data.deals);
        converted.forEach(r=>{
          if(!r.extra["c__valid_from"] && validFromDate)     r.extra["c__valid_from"]          = validFromDate;
          if(!r.extra["inc::PLB::validFrom"] && validFromDate) r.extra["inc::PLB::validFrom"]  = validFromDate;
          if(!r.extra["c__business_type"] && dealType==="b2b") r.extra["c__business_type"]     = "B2B";
        });
        setRows(converted);
        setSelectedIncentives(["PLB"]);
        if(selectedInclExcl.length>0){
          const initRIE:Record<number,RowInclExcl>={};
          converted.forEach((_,i)=>{initRIE[i]={types:selectedInclExcl,data:{},viceVersa:{}};});
          setRowInclExcl(initRIE);
        }
        setAiFileName(data.file_name);
        setAiConfidence(data.confidence);
        setFilterText("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
        setStep(3);
      }else{
        const {data}=await api.post<ExtractionPreview>("/deals/upload/extract",form,{headers:{"Content-Type":"multipart/form-data"}});
        initColumnMap(data);
        setStep(2);
      }
    }catch(err:unknown){
      const msg=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
      setUploadError(msg??"Extraction failed. Please check the file and try again.");
    }finally{setUploading(false);}
  };

  // ── Step 2 → 3: Apply mapping ────────────────────────────────────────────────
  const handleMappingConfirm=(contract:Record<string,string>,mappedRows:ReviewRow[],prePopulatedInclExcl:Record<number,RowInclExcl>)=>{
    const fallbackContract: Record<string, string> = {
      c__airline_type:  contract.c__airline_type  || "GDS",
      c__trigger_type:  contract.c__trigger_type  || "Sales",
      c__payout_type:   contract.c__payout_type   || "Sales",
    };
    const rowsWithContract=mappedRows.map(r=>({
      ...r,
      extra:{
        ...fallbackContract,
        ...contract,
        ...r.extra,
        c__airline_name: r.extra.c__airline_name || contract.c__airline_name || r.airline_name || "",
        c__valid_from:   r.extra.c__valid_from   || contract.c__valid_from   || validFromDate || "",
        c__valid_to:     r.extra.c__valid_to     || contract.c__valid_to     || "",
      },
    }));
    const finalRowInclExcl:Record<number,RowInclExcl>={};
    for(let i=0;i<rowsWithContract.length;i++){
      const fromXLS=prePopulatedInclExcl[i];
      const xlsTypes=fromXLS?.types??[];
      const xlsData=fromXLS?.data??{};
      const types=[...new Set([...selectedInclExcl,...xlsTypes])];
      if(types.length>0){
        finalRowInclExcl[i]={types,data:xlsData,viceVersa:fromXLS?.viceVersa??{}};
      }
    }
    setRows(rowsWithContract);
    setRowInclExcl(finalRowInclExcl);
    setFilterText("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
    setStep(3);
  };

  // ── Step 3 → 4: Save ────────────────────────────────────────────────────────
  const handleConfirm=async()=>{
    if(rows.length===0){setSaveError("Add at least one commission row before saving.");return;}
    setSaving(true);setSaveError("");
    const ext=file?.name.split(".").pop()?.toLowerCase()??"unknown";
    const fileType=ext==="pdf"?"pdf":["xls","xlsx"].includes(ext)?"excel":["doc","docx"].includes(ext)?"word":["png","jpg","jpeg"].includes(ext)?"image":"unknown";
    const sourceAgent=dealType==="b2b"?supplierName:(file?.name.replace(/\.[^/.]+$/,"")??"upload");

    const getContractVal=(key:string)=>{for(const r of rows){if(r.extra[key])return r.extra[key];}return "";};

    try{
      const {data:confirmData}=await api.post<{created_count:number;created_ids:number[];batch_id?:string}>(
        `/deals/upload/confirm?file_name=${encodeURIComponent(file?.name??"")}&file_type=${fileType}&supplier_name=${encodeURIComponent(supplierName||sourceAgent)}`,
        {
          source_agent:    sourceAgent,
          source_type:     "upload",
          airline_type:    getContractVal("c__airline_type")||null,
          airline_name:    getContractVal("c__airline_name")||null,
          contract_year:   dealType==="airline"?(getContractVal("c__contract_year")||null):null,
          valid_from:      getContractVal("c__valid_from")||null,
          valid_to:        getContractVal("c__valid_to")||null,
          trigger_type:    dealType==="airline"?(getContractVal("c__trigger_type")||null):null,
          payout_type:     dealType==="airline"?(getContractVal("c__payout_type")||null):null,
          entity_lcc:      getContractVal("c__entity_lcc")||null,
          business_type:   getContractVal("c__business_type")||null,
          login_id:        getContractVal("c__login_id")||null,
          incentive_types: selectedIncentives,
          incentive_data:  {},
          incl_excl_types: selectedInclExcl,
          incl_excl_data:  {},
          vice_versa:      {},
          column_map:      columnMap,
          rows: rows.map((r,i)=>{
            // Build this row's own incentive_data from its inc:: extra keys
            const rowIncData:Record<string,Record<string,string>>={};
            for(const [k,v] of Object.entries(r.extra)){
              if(k.startsWith("inc::")&&v){
                const parts=k.split("::");const inc=parts[1];const field=parts[2];
                if(!rowIncData[inc])rowIncData[inc]={};
                rowIncData[inc][field]=v;
              }
            }
            const ie=rowInclExcl[i]??{types:[],data:{},viceVersa:{}};
            return{
              row_order:i,
              airline_name:r.extra["c__airline_name"]||r.airline_name||null,
              valid_from:  r.extra["c__valid_from"]||null,
              valid_to:    r.extra["c__valid_to"]||null,
              iata_code:r.iata_code,
              eco_commission:r.eco_commission,
              peco_commission:r.peco_commission,
              bus_commission:r.bus_commission,
              valid_on:r.valid_on,
              validity_raw:r.validity_raw,
              remarks:r.remarks,
              incentive_data:  rowIncData,
              incl_excl_types: ie.types,
              incl_excl_data:  ie.data,
              vice_versa:      ie.viceVersa,
            };
          }),
        }
      );
      setSavedBatchId(confirmData.batch_id ?? null);
      setStep(4);
    }catch(err:unknown){
      const msg=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
      setSaveError(msg??"Failed to save. Please try again.");
    }finally{setSaving(false);}
  };

  const confColor=(c:number)=>c>=0.8?"bg-green-100 text-green-700 border-green-200":c>=0.5?"bg-yellow-100 text-yellow-700 border-yellow-200":"bg-red-100 text-red-600 border-red-200";

  // ── Step 4: Success ──────────────────────────────────────────────────────────
  if(step===4)return(
    <div className="max-w-lg mx-auto mt-16 text-center space-y-4">
      <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto"><Check className="w-8 h-8 text-green-500"/></div>
      <h2 className="text-xl font-bold text-gray-900">Deal Saved Successfully</h2>
      <p className="text-sm text-gray-500">
        <span className="font-medium">{rows.length} row{rows.length!==1?"s":""}</span> saved and submitted for approval.
        {selectedIncentives.length>0&&<> Incentives: <span className="font-medium">{selectedIncentives.join(", ")}</span>.</>}
      </p>
      <div className="flex gap-3 justify-center pt-2 flex-wrap">
        {savedBatchId&&(
          <button onClick={()=>router.push(`/deals/${savedBatchId}`)} className="bg-[#1e3a5f] text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-[#16304f]">View Batch</button>
        )}
        <button onClick={()=>router.push("/deals")} className="border border-[#1e3a5f] text-[#1e3a5f] px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-50">View All Deals</button>
        <button onClick={()=>{setStep(1);setFile(null);setPreview(null);setRows([]);setDealType("");setSupplierName("");setValidFromDate("");setColumnMap({});setSelectedIncentives([]);setSelectedInclExcl([]);setRowInclExcl({});setAiMode(false);setAiFileName("");setAiConfidence(0);setSavedBatchId(null);}}
          className="border border-gray-200 text-gray-700 px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-50">Upload Another</button>
      </div>
    </div>
  );

  return(
    <div className="space-y-4">
      {/* Incl/Excl Detail Modal */}
      {inclExclModal&&(
        <InclExclDetailModal
          type={inclExclModal.type}
          initialData={rowInclExcl[inclExclModal.rowIdx]?.data[inclExclModal.type]??{}}
          onSave={handleInclExclModalSave}
          onClose={()=>setInclExclModal(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Deals</p>
          <h1 className="text-xl font-bold text-gray-900">Upload Deal File</h1>
          <p className="text-xs text-gray-500 mt-0.5">Import deal sheets — automated extraction with manual review</p>
        </div>
        <StepBar step={step}/>
      </div>

      {/* ══ STEP 1 ══ */}
      {step===1&&(
        <div className="grid grid-cols-5 gap-4">
          {/* LEFT: deal info */}
          <div className="col-span-2 space-y-3">
            <SectionCard title="Deal Details">
              <div className="px-4 py-3 space-y-3">
                <SelectField
                  label="Deal Type"
                  required
                  placeholder="Select deal type…"
                  options={["Airline","B2B"]}
                  value={dealType==="airline"?"Airline":dealType==="b2b"?"B2B":""}
                  onChange={v=>{ setDealType(v==="Airline"?"airline":v==="B2B"?"b2b":""); setSupplierName(""); }}
                />
                {dealType==="b2b"&&(
                  <SearchSelectField
                    label="Supplier Name *"
                    placeholder="Search supplier…"
                    options={supplierOptions}
                    value={supplierName}
                    onChange={setSupplierName}
                  />
                )}
                <MultiSelectDropdown
                  label="Incentive Types"
                  options={INCENTIVE_TYPES}
                  selected={selectedIncentives}
                  onChange={setSelectedIncentives}
                />
                {selectedIncentives.length>0&&(
                  <p className="text-[10px] text-blue-600">
                    {selectedIncentives.join(", ")} — column mapping in Step 2, editable in Step 3.
                  </p>
                )}
                <MultiSelectDropdown
                  label="Inclusions & Exclusions"
                  options={INCLUSIONS_EXCLUSIONS}
                  selected={selectedInclExcl}
                  onChange={setSelectedInclExcl}
                />
                {selectedInclExcl.length>0&&(
                  <p className="text-[10px] text-emerald-600">
                    {selectedInclExcl.join(", ")} — columns in XLS template, editable in Step 3.
                  </p>
                )}
                <div>
                  <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Valid From Date</label>
                  <input
                    type="date"
                    value={validFromDate}
                    onChange={e=>setValidFromDate(e.target.value)}
                    className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-800"
                  />
                  {validFromDate&&<p className="text-[10px] text-blue-600 mt-1">Will pre-fill Contract Valid From in Review &amp; Edit.</p>}
                </div>
              </div>
            </SectionCard>
          </div>

          {/* RIGHT: file drop */}
          <div className="col-span-3 space-y-3">
            <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Deal File</h2>
                <div className="flex items-center gap-3">
                  <span className="text-[11px] text-gray-400">PDF · Excel · Word · Image</span>
                  <button
                    type="button"
                    onClick={()=>downloadXLSTemplate(selectedIncentives,selectedInclExcl)}
                    className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 hover:underline font-medium"
                  >
                    <FileSpreadsheet className="w-3 h-3"/>Download XLS Template
                  </button>
                </div>
              </div>
              <div
                onDragOver={e=>{e.preventDefault();setDragging(true);}}
                onDragLeave={()=>setDragging(false)}
                onDrop={e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f){setFile(f);if(/\.pdf$/i.test(f.name))setAiMode(true);else if(/\.xlsx?$/i.test(f.name))setAiMode(false);}}}
                onClick={()=>fileRef.current?.click()}
                className={`border-2 border-dashed rounded-xl flex flex-col items-center justify-center py-16 gap-3 cursor-pointer transition-all ${dragging?"border-[#1e3a5f] bg-blue-50/40":file?"border-green-400 bg-green-50/30":"border-gray-200 hover:border-blue-300 hover:bg-blue-50/20"}`}
              >
                <input ref={fileRef} type="file" accept=".pdf,.xls,.xlsx,.doc,.docx,.png,.jpg,.jpeg" className="hidden"
                  onChange={e=>{const f=e.target.files?.[0];if(f){setFile(f);if(/\.pdf$/i.test(f.name))setAiMode(true);else if(/\.xlsx?$/i.test(f.name))setAiMode(false);}}}/>
                {file?(
                  <div className="flex items-center gap-3 bg-white rounded-xl px-4 py-3 border border-gray-200 shadow-sm">
                    <FileIcon name={file.name}/>
                    <div><p className="text-sm font-semibold text-gray-800">{file.name}</p><p className="text-xs text-gray-400">{(file.size/1024).toFixed(1)} KB</p></div>
                    <button onClick={e=>{e.stopPropagation();setFile(null);}} className="ml-2 p-1 hover:bg-gray-100 rounded"><X className="w-4 h-4 text-gray-400"/></button>
                  </div>
                ):(
                  <>
                    <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center"><Upload className="w-7 h-7 text-gray-400"/></div>
                    <div className="text-center"><p className="text-sm font-semibold text-gray-700">Drop your deal file here</p><p className="text-xs text-gray-400 mt-1">or click to browse</p></div>
                    <div className="flex gap-2">
                      {[["PDF","text-red-500 bg-red-50"],["Excel","text-green-600 bg-green-50"],["Word","text-blue-500 bg-blue-50"]].map(([l,c])=>(
                        <span key={l} className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${c}`}>{l}</span>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {uploadError&&(
                <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0"/>
                  <p className="text-xs text-red-600">{uploadError}</p>
                </div>
              )}

              {/* AI Mode toggle */}
              {(()=>{const isExcel=!!file?.name.match(/\.xlsx?$/i);return(
              <label className={`flex items-center gap-2.5 select-none py-1 ${isExcel?"opacity-40 cursor-not-allowed":"cursor-pointer"}`}>
                <div
                  onClick={()=>{if(!isExcel)setAiMode(m=>!m);}}
                  className={`relative w-10 h-5 rounded-full transition-colors duration-200 flex-shrink-0 ${aiMode&&!isExcel?"bg-[#1e3a5f]":"bg-gray-200"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${aiMode&&!isExcel?"translate-x-5":"translate-x-0"}`}/>
                </div>
                <span className="text-xs font-medium text-gray-700">
                  Use AI Extraction
                  <span className="ml-1.5 text-[11px] text-gray-400 font-normal">
                    {isExcel?"Not available for Excel — use column mapping":"Standard extraction with column mapping"}
                  </span>
                </span>
              </label>
              );})()}

              <button onClick={handleExtract} disabled={!file||!dealType||(dealType==="b2b"&&!supplierName)||uploading}
                className="w-full bg-[#1e3a5f] text-white rounded-xl py-3 text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                {uploading
                  ?<><RefreshCw className="w-4 h-4 animate-spin"/>{aiMode?"Analyzing with AI…":"Extracting columns…"}</>
                  :aiMode
                    ?<><Settings2 className="w-4 h-4"/>Extract &amp; Structure with AI</>
                    :<><Upload className="w-4 h-4"/>Extract &amp; Map Columns</>
                }
              </button>

              <div className={`rounded-lg px-3 py-2.5 text-[11px] ${aiMode?"bg-purple-50 border border-purple-200 text-purple-700":"bg-blue-50 border border-blue-200 text-blue-700"}`}>
                {aiMode
                  ?"AI will read the PDF, split each airline's deal into Economy / Premium / Business rows, and skip column mapping."
                  :"After upload you'll map document columns to our fields, then review & edit all data before saving."
                }
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ══ STEP 2 ══ */}
      {step===2&&preview&&(
        <ColumnMappingStep
          preview={preview}
          columnMap={columnMap}
          onMapChange={(key,val)=>setColumnMap(p=>({...p,[key]:val}))}
          selectedIncentives={selectedIncentives}
          selectedInclExcl={selectedInclExcl}
          dealType={dealType}
          onConfirm={handleMappingConfirm}
          onBack={()=>setStep(1)}
        />
      )}

      {/* ══ STEP 3 ══ */}
      {step===3&&(preview||aiMode)&&(
        <div className="space-y-3">
          {/* File summary bar */}
          <div className="bg-white rounded-xl border border-gray-200 px-4 py-2.5 flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2.5">
              <FileIcon name={aiMode?(aiFileName||file?.name||""):(preview?.file_name??"")}/>
              <div>
                <p className="text-sm font-semibold text-gray-800">{aiMode?(aiFileName||file?.name):(preview?.file_name)}</p>
                <p className="text-xs text-gray-400">{aiMode?"AI-extracted · PLB per class":(dealType==="b2b"?supplierName:"Airline upload")}</p>
              </div>
            </div>
            <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${confColor(aiMode?aiConfidence:(preview?.confidence??0))}`}>
              {Math.round((aiMode?aiConfidence:(preview?.confidence??0))*100)}% confidence
            </span>
            <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold border bg-blue-50 text-blue-700 border-blue-200">{rows.length} rows</span>
            {aiMode
              ?<span className="px-2.5 py-1 rounded-full text-[11px] font-semibold border bg-purple-50 text-purple-700 border-purple-200">AI Extraction</span>
              :<span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${dealType==="b2b"?"bg-violet-50 text-violet-700 border-violet-200":"bg-sky-50 text-sky-700 border-sky-200"}`}>{dealType==="b2b"?"B2B":"Airline"}</span>
            }
            {selectedIncentives.map(t=><span key={t} className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-50 text-purple-700 border border-purple-200">{t}</span>)}
            {!aiMode&&preview?.warning&&<span className="flex items-center gap-1 text-[11px] text-amber-600"><AlertTriangle className="w-3.5 h-3.5"/>{preview.warning}</span>}
          </div>

          {/* Filter + Bulk Edit Toolbar */}
          <div className="bg-white rounded-xl border border-gray-200 px-4 py-2.5 space-y-2">
            {/* Row 1: Filter */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none"/>
                <input
                  type="text"
                  placeholder="Filter by airline, class, or any value…"
                  value={filterText}
                  onChange={e=>setFilterText(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              {filterText&&(
                <>
                  <span className="text-[11px] text-gray-400 whitespace-nowrap">
                    {rows.filter(row=>{const h=[row.airline_name,row.remarks,row.validity_raw,...Object.values(row.extra)].join(" ").toLowerCase();return h.includes(filterText.toLowerCase());}).length} of {rows.length} rows
                  </span>
                  <button onClick={()=>setFilterText("")} title="Clear filter" className="p-1 hover:bg-gray-100 rounded-lg">
                    <X className="w-3.5 h-3.5 text-gray-500"/>
                  </button>
                </>
              )}
            </div>
            {/* Row 2: Bulk Edit (only when rows are selected) */}
            {selectedRows.size>0&&(
              <div className="flex items-center gap-2 flex-wrap border-t border-gray-100 pt-2">
                <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap">
                  ● {selectedRows.size} row{selectedRows.size!==1?"s":""} selected
                </span>
                <select
                  value={bulkColKey}
                  onChange={e=>{setBulkColKey(e.target.value);setBulkColValue("");}}
                  className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-700"
                >
                  <option value="">Column to edit…</option>
                  {colGroups.filter(g=>g.label!=="Incl / Excl").map(g=>(
                    <optgroup key={g.label} label={g.label}>
                      {g.cols.filter(c=>c.key!=="__incl_excl__").map(c=>(
                        <option key={c.key} value={c.key}>{c.label}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                {bulkColKey&&(()=>{
                  const meta=getColMeta(bulkColKey);
                  if(meta.type==="date")return(
                    <input type="date" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
                  );
                  if(meta.type==="select"&&meta.options)return(
                    <select value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-700">
                      <option value="">Choose value…</option>
                      {meta.options.map(o=><option key={o} value={o}>{o}</option>)}
                    </select>
                  );
                  if(meta.type==="number")return(
                    <input type="number" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      placeholder="Enter value…"
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 w-28"/>
                  );
                  return(
                    <input type="text" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      placeholder="Enter value…"
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 w-36"/>
                  );
                })()}
                <button
                  onClick={handleBulkApply}
                  disabled={!bulkColKey||bulkColValue===""}
                  className="px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  Apply to {selectedRows.size} row{selectedRows.size!==1?"s":""}
                </button>
                <button
                  onClick={()=>setSelectedRows(new Set())}
                  className="px-3 py-1.5 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50 whitespace-nowrap"
                >
                  Deselect All
                </button>
              </div>
            )}
          </div>

          <div className="bg-white rounded-lg border border-gray-200">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Review &amp; Edit — All Data</h2>
              <span className="text-[10px] text-gray-400 ml-auto">Scroll horizontally · Click any cell to edit · Use Incl/Excl column to add per-row rules</span>
            </div>
            <ReviewTable
              rows={rows}
              colGroups={colGroups}
              onChange={handleRowChange}
              onDelete={handleDeleteRow}
              onAdd={handleAddRow}
              rowInclExcl={rowInclExcl}
              inclExclPopup={inclExclPopup}
              setInclExclPopup={setInclExclPopup}
              onToggleInclExclType={handleToggleInclExclType}
              onOpenInclExclType={handleOpenInclExclType}
              onRemoveInclExclType={handleRemoveInclExclType}
              filterText={filterText}
              selectedRows={selectedRows}
              onToggleRow={handleToggleRow}
              onToggleAllFiltered={handleToggleAllFiltered}
            />
          </div>

          {saveError&&(
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
              <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0"/>
              <p className="text-xs text-red-600">{saveError}</p>
            </div>
          )}

          <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 z-40">
            <div className="flex items-center justify-center gap-3 py-2.5">
              <button type="button" onClick={()=>setStep(aiMode?1:2)}
                className="px-7 py-1.5 border border-gray-300 text-gray-600 rounded-full text-xs font-medium hover:bg-gray-50 transition-colors">
                {aiMode?"← Back to Upload":"← Remap Columns"}
              </button>
              <button type="button" onClick={handleConfirm} disabled={saving}
                className="px-7 py-1.5 bg-blue-600 text-white rounded-full text-xs font-medium hover:bg-blue-700 transition-colors disabled:opacity-60 flex items-center gap-2">
                {saving?<><RefreshCw className="w-3.5 h-3.5 animate-spin"/>Saving…</>:<><Save className="w-3.5 h-3.5"/>Confirm &amp; Save ({rows.length} rows)</>}
              </button>
            </div>
          </div>
          <div className="h-14"/>
        </div>
      )}
    </div>
  );
}
