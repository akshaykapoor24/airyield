"use client";

import { useCallback, useState, useRef, useEffect, useMemo } from "react";
import {
  Upload, FileText, FileSpreadsheet, File, Check,
  ChevronRight, AlertTriangle, X, RefreshCw, Save,
  Plus, Trash2, ChevronDown, ArrowLeft, ArrowRight, Info, Settings2,
} from "lucide-react";
import * as XLSX from "xlsx";
import Link from "next/link";
import api from "@/lib/api";
import { useRouter } from "next/navigation";
import {
  IEFieldValue,
  CONTINENTS, COUNTRY_GROUPS,
  INCENTIVE_FIELDS, FIELD_OPTIONS, ANCILLARY_ITEMS,
  DATE_WISE_INCENTIVES, FLIGHT_TYPE_OPTIONS, CLASS_OPTIONS, PAYOUT_CALC_OPTIONS,
  TabBar, IncentiveTabContent, InclExclTabContent,
} from "@/components/deals/IncentiveInclExclShared";
import OutgoingScopeFields, { type ScopeSelection } from "@/components/deals/OutgoingScopeFields";
import { loadVendorAgencies, vendorAgencyOptions, type VendorAgency } from "@/lib/vendorAgency";
import {
  OUTGOING_DEAL_KINDS, KIND_BUSINESS_TYPE, buildScopePayload, dealsHref, scopeLabel, toScopeType,
  type DealScopeType, type OutgoingDealKind,
} from "@/lib/dealScope";
import { missingFields, missingMessage, notifyRequired } from "@/lib/requiredFields";

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════════
// An incoming B2B upload's Supplier Name is picked from the user's own Agency Master —
// see lib/vendorAgency.ts, shared with Create Deal.
const CONTRACT_YEARS = ["Calendar year", "Financial year"];
const TRIGGER_TYPES  = ["Flown", "Sales"];
const PAYOUT_TYPES   = ["Flown", "Sales"];
const BUSINESS_TYPES = ["B2B", "B2C", "B2E", "MICE"];

const DEAL_TAG_OPTIONS = ["Standard", "Adhoc"];

const INCENTIVE_TYPES = [
  "PLB","Super PLB","Transaction Fee","Deposit Incentive (DI)","Marketing Fund",
  "Ancillary","Frontend","Backend","Cashback","Segment Incentive","Push Action",
];

const INCLUSIONS_EXCLUSIONS = [
  "Inclusion For Trigger","Exclusion For Trigger",
  "Inclusion For Payout","Exclusion For Payout",
];

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

// Matches every field in InclExclRuleModal (Exclusion + Inclusion).
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

// INCENTIVE_FIELDS now imported from the shared module (same field set the manual
// create-deal form uses) — ensures upload and manual stay in lockstep by construction.

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
  {key:"c__entity",    label:"Entity"},
  {key:"c__login_id",      label:"Login ID"},
  {key:"c__iata_commission", label:"IATA Commission (%)"},
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
// MULTI-TAB (TABBED) TEMPLATE — one sheet per incentive, joined by "Deal No"
// ═══════════════════════════════════════════════════════════════════════════════
const MT_CONTRACT_SHEET = "Airline Contract Details";

// Files AI Extraction can read. PDFs (on by default — their tables are reconstructed
// from the page) and spreadsheets (off by default, for sheets too free-form to map:
// vendor comparisons, house formats).
const AI_READABLE_RE = /\.(pdf|xlsx|xlsm|xls|csv)$/i;
// What a deal file may be: PDF or Excel only — Word and images are not accepted.
const UPLOAD_FILE_RE = /\.(pdf|xlsx|xls)$/i;
const UPLOAD_FILE_ERROR = "Only PDF and Excel (.xls / .xlsx) files can be uploaded.";

// Header-sheet columns. Keys mirror the upload field keys (c__*) so the existing
// review/confirm path consumes them unchanged. The full superset is used when
// parsing (maps whatever columns are present); generation filters per deal type
// (B2B hides Contract Year / Trigger / Payout, like the single-sheet flow).
const MT_CONTRACT_COLS_ALL: {key:string;label:string}[] = [
  {key:"__dealno",           label:"Deal No"},
  // Incoming B2B only: the supplier's Agency Code (AG-0001), pre-filled from Step 1. The
  // server checks it against the picked supplier before anything is extracted — see
  // backend services/deal_supplier_check.py. Not a deal field, so never mapped.
  {key:"__supplier_code",    label:"Supplier Code"},
  // Outgoing: the CUSTOMER's code, pre-filled from the deal's scope — "Agency Code" for a
  // sub-agency (AG-0001), "Corporate Code" for a corporate (CO-0001). Checked on upload by
  // /deals/upload/check-scope. Like Supplier Code, never a deal field.
  {key:"__agency_code",      label:"Agency Code"},
  {key:"__corporate_code",   label:"Corporate Code"},
  {key:"c__airline_type",    label:"Airline Type"},
  {key:"c__airline_name",    label:"Airline Name"},
  {key:"c__contract_year",   label:"Contract Year"},
  {key:"c__business_type",   label:"Business Type"},
  {key:"c__valid_from",      label:"Contract Valid From"},
  {key:"c__valid_to",        label:"Contract Valid To"},
  {key:"c__trigger_type",    label:"Trigger Type"},
  {key:"c__payout_type",     label:"Payout Type"},
  {key:"c__entity",      label:"Entity"},
  {key:"c__login_id",        label:"Login ID"},
  {key:"c__iata_commission", label:"IATA Commission (%)"},
  {key:"c__supplier_name",   label:"Supplier"},
  {key:"c__deal_maker_name", label:"Deal Maker"},
  {key:"r__remarks",         label:"Remarks"},
];
const MT_B2B_HIDDEN = new Set(["c__contract_year","c__trigger_type","c__payout_type"]);
type MtCodeKey = "__supplier_code"|"__agency_code"|"__corporate_code";
function mtContractCols(dealType:string, codeKey:MtCodeKey|null=null){
  // Supplier is already picked in Deal Details (Step 1), so its NAME never goes in the
  // sheet — its CODE does, on an incoming B2B template, so the file says whose it is.
  return MT_CONTRACT_COLS_ALL.filter(c=>{
    if(c.key==="c__supplier_name") return false;
    if(c.key==="__supplier_code"||c.key==="__agency_code"||c.key==="__corporate_code") return c.key===codeKey;
    if(dealType==="b2b" && MT_B2B_HIDDEN.has(c.key)) return false;
    return true;
  });
}
const mtContractSample=(key:string):string=>({
  __dealno:"1", c__airline_type:"GDS", c__airline_name:"Air France",
  c__contract_year:"Calendar year", c__business_type:"B2B",
  c__valid_from:"2026-01-01", c__valid_to:"2026-12-31",
  c__trigger_type:"Sales", c__payout_type:"Sales",
}[key] ?? "");

// Ancillary & Segment Incentive aren't in INCENTIVE_FIELDS (custom-rendered), so list
// their FIXED columns explicitly (slab columns are intentionally omitted everywhere).
const ANCILLARY_FIXED_COLS: {key:string;label:string}[] = ANCILLARY_ITEMS.flatMap(it=>[
  {key:it.key,       label:it.label},
  {key:it.numPctKey, label:`${it.label} Number or Percentage`},
  {key:it.amtKey,    label:`${it.label} Amount`},
]);
const SI_FIXED_COLS: {key:string;label:string}[] = [
  {key:"siPeriodFrom",  label:"Period From for Segment Incentive"},
  {key:"siPeriodTo",    label:"Period To for Segment Incentive"},
  {key:"siTargetType",  label:"Target in Percent or Amount for Segment Incentive"},
  {key:"siTargetValue", label:"Target Percent or Amount for Segment Incentive"},
  {key:"siClass",       label:"Class for Segment Incentive"},
  {key:"siFlightType",  label:"Flight Type for Segment Incentive"},
];

function incentiveFixedCols(inc:string): {key:string;label:string}[] {
  if(inc==="Ancillary")          return ANCILLARY_FIXED_COLS;
  if(inc==="Segment Incentive")  return SI_FIXED_COLS;
  return (INCENTIVE_FIELDS[inc]??[]).map(f=>({key:f.key,label:f.label}));
}

// Option lists used to normalize select cells while parsing (fuzzy-matched).
const MT_SELECT_OPTIONS: Record<string,string[]> = {
  ...FIELD_OPTIONS,
  c__airline_type:  ["GDS","LCC"],
  c__business_type: BUSINESS_TYPES,
  siTargetType:     ["Amount","Percentage"],
  siClass:          ["All","Economy","Premium","Business"],
  siFlightType:     ["All","Domestic","International"],
  ...Object.fromEntries(ANCILLARY_ITEMS.flatMap(it=>[
    [it.key,       [it.withValue, it.withoutValue]],
    [it.numPctKey, ["Number","Percentage"]],
  ])),
};

// Normalize a cell value to YYYY-MM-DD for date columns (module-level twin of the
// ColumnMappingStep's local toDateStr, usable from the multi-tab parser).
function mtDateStr(v:string):string{
  if(!v) return v;
  const t=v.trim();
  if(/^\d{4}-\d{2}-\d{2}$/.test(t)) return t;
  const m=t.match(/^(\d{4}-\d{2}-\d{2})[T ]?/);
  if(m) return m[1];
  try{const d=new Date(t);if(!isNaN(d.getTime()))return d.toISOString().split("T")[0];}catch{}
  return t;
}
const mtIsDateLabel=(label:string)=>/valid from|valid to|period from|period to/.test(label);

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

// ruleType -> incentiveType -> field -> value (each incentive type on a row gets
// its own independent rule set, mirroring the manual create-deal form)
type RowInclExcl = {
  types:     string[];
  data:      Record<string, Record<string, Record<string, IEFieldValue>>>;
  viceVersa: Record<string, Record<string, boolean>>;
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
  // Airline-master resolution. airline_name above is ALREADY the master's
  // canonical name when airline_status is "resolved"; for every other status it
  // is the sheet's own wording with the channel qualifier removed — the master's
  // name is deliberately NOT applied when the match is not trustworthy.
  airline_code?: string | null;
  airline_status?: string | null;   // resolved|new|conflict|multi_carrier|ambiguous|unresolved
  airline_master_name?: string | null;
  airline_note?: string | null;
  iata_commission: string | number | null;
  contract_valid_from: string | null;
  contract_valid_to: string | null;
  incentive_types: string[];
  incentive_data: Record<string, Record<string, string | number | null> | undefined>;
  remark: string;
  // Where this deal came from in the source PDF, and whether it needs manual entry.
  src_n?: number | null;
  src_page?: number | null;
  src_text?: string | null;
  needs_manual?: boolean;
  // Multi-supplier sheets: the row's Source cell as printed ("YATRA(TSI)"). On an
  // All-suppliers extract also its line in supplier_summary, how it resolved, and the
  // agency pre-selected for it (only when remembered / matched — never a guess).
  supplier_cell?: string | null;
  supplier_group?: string | null;
  vendor_status?: string | null;
  vendor_agency_id?: number | null;
};

// "All suppliers": one Source value of the sheet and the Agency Master row it resolved
// to — see backend services/deal_vendor_resolver.py for what each status means.
type SupplierSource = {
  group: string;                 // joins rows to this line (extra.__src_group)
  source: string;                // as printed; "" for rows with no Source
  channel: string|null;          // GDS | LCC — agencies are onboarded per channel
  rows: number; deals: number;
  status: "remembered"|"matched"|"suggested"|"ambiguous"|"not_onboarded"|"blank";
  agency_id: number|null;        // pre-selected: remembered / matched only
  candidates: number[];          // offered: suggested / ambiguous
  note?: string|null;
};

type AIExtractResponse = {
  deals: AIDeal[];
  file_name: string;
  confidence: number;
  warning?: string;
  // Counted over DISTINCT airlines, not rows — "12 will be added", not "36 rows".
  airline_summary?: Record<string,number>;
  supplier_summary?: SupplierSource[];
};

// The Supplier Name option that loads a multi-supplier sheet in one go.
const ALL_SUPPLIERS_LABEL = "All suppliers — multi-vendor sheet";

function convertAIDealsToRows(deals: AIDeal[]): ReviewRow[] {
  return deals.map((deal, idx) => {
    const extra: Record<string, string> = {};
    if (deal.airline_type)        extra["c__airline_type"] = deal.airline_type;
    if (deal.airline_name)        extra["c__airline_name"]  = deal.airline_name;
    // The carrier code reaches the save payload (handleConfirm sends it explicitly)
    // so the backend can create a missing master row — airlines.iata_code is NOT
    // NULL. It is NOT the agency IATA number, which travels as `iata_code`.
    if (deal.airline_code)        extra["c__airline_code"] = deal.airline_code;
    // Resolution status is advisory display only. "__"-prefixed keys are
    // structurally incapable of reaching the payload — same guarantee __src relies
    // on — and the server re-resolves from scratch anyway, so a tampered status
    // cannot influence what gets written.
    if (deal.airline_status)      extra["__air_status"] = deal.airline_status;
    if (deal.airline_master_name) extra["__air_master"] = deal.airline_master_name;
    if (deal.airline_note)        extra["__air_note"]   = deal.airline_note;
    if (deal.iata_commission != null && deal.iata_commission !== "")
                                  extra["c__iata_commission"] = String(deal.iata_commission);
    if (deal.contract_valid_from) extra["c__valid_from"]    = deal.contract_valid_from;
    if (deal.contract_valid_to)   extra["c__valid_to"]      = deal.contract_valid_to;
    // Provenance for the read-only Source column. Deliberately NOT a "c__" key:
    // those are contract fields, and this must never reach the save payload.
    if (deal.src_page != null || deal.src_n != null) {
      extra["__src"] = `p.${deal.src_page ?? "?"} r${deal.src_n ?? "?"} · ${deal.src_text ?? ""}`.trim();
    }
    if (deal.needs_manual) extra["__needs_manual"] = "1";
    // All suppliers. The row's supplier is its own editable c__vendor_agency_id; the
    // Source cell travels to the save too (it is remembered against the agency picked
    // for it), so like c__airline_code it is a c__ key handleConfirm reads explicitly.
    // Its group and status are advisory "__" keys, like __air_status.
    if (deal.supplier_cell != null)     extra["c__supplier_cell"] = deal.supplier_cell;
    if (deal.supplier_group)            extra["__src_group"] = deal.supplier_group;
    if (deal.vendor_status)             extra["__vendor_status"] = deal.vendor_status;
    if (deal.vendor_agency_id != null)  extra["c__vendor_agency_id"] = String(deal.vendor_agency_id);
    for (const [incType, incFields] of Object.entries(deal.incentive_data ?? {})) {
      if (!incFields) continue;
      for (const [field, value] of Object.entries(incFields)) {
        if (value != null && value !== "") {
          extra[`inc::${incType}::${field}`] = String(value);
        }
      }
      // A flat commission % is a Fixed amount-based payout — set the payout-mode
      // fields so the form shows "Incentive Percentage or Amount" pre-filled, even
      // if the AI returned them null.
      const amt = (incFields as Record<string, unknown>)["incentiveAmtPct"];
      if (amt != null && amt !== "") {
        if (!extra[`inc::${incType}::targetBased`])     extra[`inc::${incType}::targetBased`]     = "Amount Based";
        if (!extra[`inc::${incType}::amountBasedType`]) extra[`inc::${incType}::amountBasedType`] = "Fixed";
        if (!extra[`inc::${incType}::incentiveNumPct`]) extra[`inc::${incType}::incentiveNumPct`] = "Percentage";
      }
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

// Contract columns every review row must carry before it can be saved. These
// are the four the manual deal API declares required (airline_type,
// airline_name, valid_from, valid_to) — the upload confirm payload leaves them
// all Optional, so without this check a blank one saved silently as NULL.
// Contract Year / Trigger / Payout are NOT here: the mapping step fills them
// with GDS / Sales / Sales fallbacks, so they are never blank by this point.
const REQUIRED_ROW_COLUMNS:{key:string;label:string;dealTypes:string[]}[] = [
  {key:"c__airline_name",label:"Airline Name",         dealTypes:["airline","b2b"]},
  {key:"c__airline_type",label:"Airline Type",         dealTypes:["airline","b2b"]},
  {key:"c__valid_from",  label:"Contract Valid From",  dealTypes:["airline","b2b"]},
  {key:"c__valid_to",    label:"Contract Valid To",    dealTypes:["airline","b2b"]},
];

const EMPTY_ROW = ():ReviewRow => ({
  row_order:0,airline_name:"",iata_code:"",eco_commission:"",
  peco_commission:"",bus_commission:"",valid_on:"",validity_raw:"",remarks:"",
  extra:{},
});

// The incentive fields the review table shows as columns of their own, in reading order —
// what a reviewer checks on every row. Only the standard-shaped incentives have them
// (DATE_WISE_INCENTIVES); the rest of each incentive, and its rules, stay in the popup.
// A column's key is the row's own storage key, inc::{incentive}::{field}.
const INLINE_INC_FIELDS:{field:string;label:string}[] = [
  {field:"travelValidFrom", label:"Travel From"},
  {field:"travelValidTo",   label:"Travel To"},
  {field:"flightType",      label:"Flight Type"},
  {field:"class",           label:"Class"},
  {field:"payoutCalcCols",  label:"Calc On"},
  {field:"incentiveAmtPct", label:"Rate"},
];
const inlineIncentives=(incentives:string[])=>incentives.filter(i=>DATE_WISE_INCENTIVES.has(i));
const incCellField=(key:string)=>key.startsWith("inc::")?(key.split("::")[2]??""):"";
const isSlabPayout=(extra:Record<string,string>,inc:string)=>extra[`inc::${inc}::amountBasedType`]==="Slab Based";
// A FLAT deal: a fixed amount per ticket (Fixed → Number), so it has no calc columns.
const isFlatPayout=(extra:Record<string,string>,inc:string)=>extra[`inc::${inc}::incentiveNumPct`]==="Number";

// An edit to one of those columns, with what the popup would do alongside it. A rate typed
// on a row with no payout mode yet (an unread row) makes it the Fixed percentage the
// extractor gives a read row; a slab payout has no single rate, so it is left alone. The rate
// cell's % / ₹ switch (incentiveNumPct) turns a row into a FLAT deal — Amount Based → Fixed
// → Number, the shape a sheet's FLAT rows come in — and keeps the amount typed. Calc On
// carries Target Calc Columns with it wherever the two still agreed. A new Flight Type
// drops slabs laid out for the old one's columns.
function withIncentiveCellChange(extra:Record<string,string>,key:string,val:string):Record<string,string>{
  const [,inc,field]=key.split("::");
  const k=(f:string)=>`inc::${inc}::${f}`;
  if((field==="incentiveAmtPct"||field==="incentiveNumPct")&&isSlabPayout(extra,inc))return extra;
  const out={...extra,[key]:val};
  if((field==="incentiveAmtPct"&&val!=="")||field==="incentiveNumPct"){
    if(!out[k("targetBased")])     out[k("targetBased")]="Amount Based";
    if(!out[k("amountBasedType")]) out[k("amountBasedType")]="Fixed";
    if(!out[k("incentiveNumPct")]) out[k("incentiveNumPct")]="Percentage";
  }else if(field==="payoutCalcCols"){
    if(!out[k("targetCalcCols")]||out[k("targetCalcCols")]===(extra[key]??"")) out[k("targetCalcCols")]=val;
  }else if(field==="flightType"&&val!==(extra[key]??"")){
    for(const s of ["amountSlabs","segmentSlabs"]) if(out[k(s)]) out[k(s)]="[]";
  }
  return out;
}

// Rows the AI extractor could not read. They arrive holding only what the row's place in
// the file gave away (airline, dates, Source) — see backend _manual_placeholder.
const isUnreadRow=(r:ReviewRow)=>r.extra["__needs_manual"]==="1";

// What an unread row still lacks, as column keys so the table can mark those cells; empty
// once it is filled in, and always empty for a row that was read. A read row always has
// these, so a hand-filled one is done when it has them too. Checked on the incentives the
// row already carries (the extractor gives a placeholder PLB), else the first inline one.
function unreadGaps(r:ReviewRow,inline:string[]):string[]{
  if(!isUnreadRow(r))return [];
  const gaps:string[]=[];
  if(!(r.extra["c__airline_name"]||r.airline_name||"").trim()) gaps.push("c__airline_name");
  const own=inline.filter(inc=>Object.keys(r.extra).some(k=>k.startsWith(`inc::${inc}::`)));
  for(const inc of own.length?own:inline.slice(0,1)){
    const blank=(f:string)=>!(r.extra[`inc::${inc}::${f}`]??"").trim();
    // A flat amount is paid as it stands — there is no Calc On to fill in.
    const needed=isFlatPayout(r.extra,inc)?["flightType","class"]:["flightType","class","payoutCalcCols"];
    for(const f of needed) if(blank(f)) gaps.push(`inc::${inc}::${f}`);
    if(!isSlabPayout(r.extra,inc)&&blank("incentiveAmtPct")) gaps.push(`inc::${inc}::incentiveAmtPct`);
  }
  return gaps;
}
function gapLabels(gaps:string[]):string[]{
  const incs=new Set(gaps.filter(g=>g.startsWith("inc::")).map(g=>g.split("::")[1]));
  return gaps.map(g=>{
    if(g==="c__airline_name")return "Airline Name";
    const [,inc,f]=g.split("::");
    const label=INLINE_INC_FIELDS.find(x=>x.field===f)?.label??f;
    return incs.size>1?`${inc} ${label}`:label;
  });
}

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

// MultiCheckboxDropdown / MultiSearchSelectField / TagInput now come from the shared
// module via InclExclTabContent — InclExclRuleModal below uses that directly.

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
// INCL/EXCL RULE MODAL — reuses the shared InclExclTabContent (multi-value, same
// component the manual create-deal form uses), with one sub-tab per incentive type
// on the row so each incentive type gets its own independent rule set.
// ═══════════════════════════════════════════════════════════════════════════════
function InclExclRuleModal({
  type, incentiveTypes, selectedRows, rowIdx,
  getData, onFieldChange, getViceVersa, onToggleViceVersa,
  onCopyToSelected, onClose,
}:{
  type:string;
  incentiveTypes:string[];
  selectedRows:Set<number>;
  rowIdx:number;
  getData:(incType:string)=>Record<string,IEFieldValue>;
  onFieldChange:(incType:string,key:string,value:IEFieldValue)=>void;
  getViceVersa:(incType:string)=>boolean;
  onToggleViceVersa:(incType:string)=>void;
  onCopyToSelected:()=>void;
  onClose:()=>void;
}){
  const [activeIncType, setActiveIncType] = useState(incentiveTypes[0] ?? "");
  const incType = incentiveTypes.includes(activeIncType) ? activeIncType : (incentiveTypes[0] ?? "");
  const isExclusion = type.startsWith("Exclusion");
  const suffix = isExclusion ? "for Exclusion" : "for Inclusion";

  const [continentOptions, setContinentOptions] = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);

  useEffect(()=>{
    api.get<{continents:string[];country_groups:string[]}>("/airports/options")
      .then(r=>{
        if(r.data.continents?.length)     setContinentOptions(r.data.continents);
        if(r.data.country_groups?.length) setCountryGroupOptions(r.data.country_groups);
      })
      .catch(()=>{});
  },[]);

  const otherSelectedCount = [...selectedRows].filter(i=>i!==rowIdx).length;

  return(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Configure — {type}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Each incentive type gets its own independent rule set. All fields support multiple selections.</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500"/></button>
        </div>
        {incentiveTypes.length===0?(
          <p className="px-5 py-8 text-xs text-gray-400 text-center">Select at least one Incentive Type first.</p>
        ):(
          <>
            {incentiveTypes.length>1&&(
              <TabBar tabs={incentiveTypes} active={incType} onSelect={setActiveIncType}/>
            )}
            <div className="overflow-y-auto flex-1">
              {incType&&(
                <InclExclTabContent
                  suffix={suffix}
                  isExclusion={isExclusion}
                  data={getData(incType)}
                  onChange={(k,v)=>onFieldChange(incType,k,v)}
                  viceVersa={getViceVersa(incType)}
                  onViceVersa={()=>onToggleViceVersa(incType)}
                  continentOptions={continentOptions}
                  countryGroupOptions={countryGroupOptions}
                />
              )}
            </div>
          </>
        )}
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-t border-gray-100">
          <button
            onClick={onCopyToSelected}
            disabled={otherSelectedCount===0}
            className="text-xs text-blue-600 hover:text-blue-700 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Copy this row&apos;s Incl/Excl to {otherSelectedCount} selected row{otherSelectedCount!==1?"s":""}
          </button>
          <button onClick={onClose} className="bg-[#1e3a5f] text-white rounded-lg px-5 py-2 text-sm font-semibold hover:bg-[#16304f]">Done</button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// INCENTIVE & RULES ROW MODAL — one tab per incentive type. Each tab shows the
// shared IncentiveTabContent (payout fields, same as the manual create-deal form)
// AND that incentive's inclusion/exclusion rules (4 rule sub-tabs) below it, so
// everything for one incentive is edited in a single place.
// ═══════════════════════════════════════════════════════════════════════════════
function IncentiveDataRowModal({
  rowIdx, incentiveTypes, selectedRows,
  getData, onFieldChange,
  getInclExclData, onInclExclChange, getInclExclViceVersa, onInclExclViceVersa,
  onCopyToSelected, onClose, bulk,
}:{
  rowIdx:number;
  incentiveTypes:string[];
  selectedRows:Set<number>;
  /** Bulk mode: the modal edits a blank draft, not a row; only what is filled in is
   *  written to the target rows when the user presses Apply. */
  bulk?:{ count:number; airline:string; onApply:()=>void };
  getData:(incType:string)=>Record<string,string>;
  onFieldChange:(incType:string,key:string,value:string)=>void;
  getInclExclData:(incType:string,ruleType:string)=>Record<string,IEFieldValue>;
  onInclExclChange:(incType:string,ruleType:string,key:string,value:IEFieldValue)=>void;
  getInclExclViceVersa:(incType:string,ruleType:string)=>boolean;
  onInclExclViceVersa:(incType:string,ruleType:string)=>void;
  onCopyToSelected:()=>void;
  onClose:()=>void;
}){
  const [activeIncType, setActiveIncType] = useState(incentiveTypes[0] ?? "");
  // Land on the first rule type that already has data so parsed rules are visible.
  const [activeRuleType, setActiveRuleType] = useState(
    INCLUSIONS_EXCLUSIONS.find(rt=>Object.keys(getInclExclData(incentiveTypes[0]??"",rt)).length>0) ?? INCLUSIONS_EXCLUSIONS[0]
  );
  const incType = incentiveTypes.includes(activeIncType) ? activeIncType : (incentiveTypes[0] ?? "");
  const otherSelectedCount = [...selectedRows].filter(i=>i!==rowIdx).length;

  const [continentOptions, setContinentOptions] = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);
  useEffect(()=>{
    api.get<{continents:string[];country_groups:string[]}>("/airports/options")
      .then(r=>{
        if(r.data.continents?.length)     setContinentOptions(r.data.continents);
        if(r.data.country_groups?.length) setCountryGroupOptions(r.data.country_groups);
      })
      .catch(()=>{});
  },[]);

  const isExclusion = activeRuleType.startsWith("Exclusion");
  const ieSuffix = isExclusion ? "for Exclusion" : "for Inclusion";

  return(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">
              {bulk
                ? <>Incentive &amp; Rules — {bulk.count} row{bulk.count!==1?"s":""}{bulk.airline?` · ${bulk.airline}`:""}</>
                : <>Incentive &amp; Rules — Row {rowIdx+1}</>}
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              {bulk
                ? "Fill in only what should change. Every field you leave blank keeps each row's own value — rates included."
                : "Per incentive type: payout details and its inclusion / exclusion rules, all in one place."}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500"/></button>
        </div>
        {incentiveTypes.length===0?(
          <p className="px-5 py-8 text-xs text-gray-400 text-center">Select at least one Incentive Type first.</p>
        ):(
          <>
            <TabBar tabs={incentiveTypes} active={incType} onSelect={setActiveIncType}/>
            <div className="overflow-y-auto flex-1">
              {incType&&(
                <>
                  <IncentiveTabContent
                    name={incType}
                    data={getData(incType)}
                    onChange={(k,v)=>onFieldChange(incType,k,v)}
                    // Travel Date Valid From/To, as on Create Deal — saved per incentive
                    // (inc::{inc}::travelValidFrom / travelValidTo) like every other field.
                    travelDates
                  />

                  {/* Inclusion / Exclusion rules for THIS incentive type */}
                  <div className="border-t border-gray-100 mt-1 pt-3">
                    <h3 className="px-4 text-[11px] font-bold text-gray-500 uppercase tracking-wide">Inclusion / Exclusion Rules</h3>
                    <div className="px-4 mt-2">
                      <div className="flex gap-1 border-b border-gray-100 flex-wrap">
                        {INCLUSIONS_EXCLUSIONS.map(rt=>{
                          const hasVals=Object.keys(getInclExclData(incType,rt)).length>0;
                          return(
                            <button key={rt} type="button" onClick={()=>setActiveRuleType(rt)}
                              className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap ${activeRuleType===rt?"border-[#1e3a5f] text-[#1e3a5f]":"border-transparent text-gray-400 hover:text-gray-600"}`}>
                              {rt}{hasVals&&<span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 align-middle"/>}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <InclExclTabContent
                      key={`${incType}:${activeRuleType}`}
                      suffix={ieSuffix}
                      isExclusion={isExclusion}
                      data={getInclExclData(incType,activeRuleType)}
                      onChange={(k,v)=>onInclExclChange(incType,activeRuleType,k,v)}
                      viceVersa={getInclExclViceVersa(incType,activeRuleType)}
                      onViceVersa={()=>onInclExclViceVersa(incType,activeRuleType)}
                      continentOptions={continentOptions}
                      countryGroupOptions={countryGroupOptions}
                    />
                  </div>
                </>
              )}
            </div>
          </>
        )}
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-t border-gray-100">
          {bulk ? (
            <>
              <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-700 font-medium">Cancel</button>
              <button onClick={()=>{bulk.onApply();onClose();}}
                className="bg-[#1e3a5f] text-white rounded-lg px-5 py-2 text-sm font-semibold hover:bg-[#16304f]">
                Apply to {bulk.count} row{bulk.count!==1?"s":""}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onCopyToSelected}
                disabled={otherSelectedCount===0}
                className="text-xs text-blue-600 hover:text-blue-700 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Copy this row to {otherSelectedCount} selected row{otherSelectedCount!==1?"s":""}
              </button>
              <button onClick={onClose} className="bg-[#1e3a5f] text-white rounded-lg px-5 py-2 text-sm font-semibold hover:bg-[#16304f]">Done</button>
            </>
          )}
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
        const byIncType=rowState.data[type]??{};
        // Collect all filled values across every incentive type's rule set as chips
        const valueSummary=Object.values(byIncType).flatMap(typeData=>
          Object.entries(typeData??{})
            .filter(([k])=>!["dateExclusionTicket","dateExclusionTravel"].includes(k))
            .flatMap(([,v])=>Array.isArray(v)?v:[v])
        ).filter(Boolean);
        const dateExclParts=Object.values(byIncType).flatMap(typeData=>[
          typeData?.["dateExclusionTicket"]==="true"?"Ticket Date":null,
          typeData?.["dateExclusionTravel"]==="true"?"Travel Date":null,
        ]).filter(Boolean) as string[];
        const allValues=[...new Set([...dateExclParts,...valueSummary])];
        return(
          <div key={type} className="px-2 py-1.5 rounded-lg hover:bg-blue-50">
            <div className="flex items-center gap-1">
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
            {isSelected&&allValues.length>0&&(
              <div className="flex flex-wrap gap-1 mt-1 ml-5">
                {allValues.map((v,i)=>(
                  <span key={i} className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-blue-50 text-blue-700 border border-blue-100">{v}</span>
                ))}
              </div>
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
  preview, columnMap, onMapChange, selectedIncentives, selectedInclExcl, dealType, onConfirm, onBack, contractOnly=false
}:{
  preview:ExtractionPreview;
  columnMap:Record<string,string>;
  onMapChange:(ourKey:string,docCol:string)=>void;
  selectedIncentives:string[];
  selectedInclExcl:string[];
  dealType:string;
  onConfirm:(contract:Record<string,string>,rows:ReviewRow[],rowInclExcl:Record<number,RowInclExcl>)=>void;
  onBack:()=>void;
  contractOnly?:boolean;   // multi-tab: map only the contract sheet (incentive/rules live on other sheets)
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
      // Per-row incentive column values (skipped for multi-tab — those live on other sheets)
      if(!contractOnly) for(const inc of selectedIncentives){
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
    // Extract incl/excl column values per row from XLS (flat per rule type, then
    // duplicated across every selected incentive type so each starts with the same
    // data — independently editable afterward via the per-row Incl/Excl modal)
    const rowInclExclFromXLS:Record<number,RowInclExcl>={};
    if(!contractOnly) for(let i=0;i<rowCount;i++){
      const rawRow=rawRows[i];
      if(!rawRow)continue;
      const flatByType:Record<string,Record<string,IEFieldValue>>={};
      for(const type of selectedInclExcl){
        for(const f of INCL_EXCL_FIELDS){
          const colKey=`ie__${type}__${f.key}`;
          const dc=columnMap[colKey];
          if(dc){let v=cellVal(rawRow,dc);if(v){
            if(f.type==="date")v=toDateStr(v);
            if(!flatByType[type])flatByType[type]={};
            if(f.key==="_dateExclusion"){
              // Expand combined column into two bool flags
              const lower=v.toLowerCase();
              if(lower.includes("ticket"))flatByType[type]["dateExclusionTicket"]="true";
              if(lower.includes("travel"))flatByType[type]["dateExclusionTravel"]="true";
            }else if(f.type==="date"){
              flatByType[type][f.key]=v;
            }else{
              // Split pipe-separated multi-values (e.g. "Asia|Europe")
              const parts=v.split("|").map((s:string)=>s.trim()).filter(Boolean);
              flatByType[type][f.key]=parts.length>1?parts:parts[0];
            }
          }}
        }
      }
      const types=Object.keys(flatByType).filter(t=>Object.keys(flatByType[t]).length>0);
      if(types.length>0){
        const incTypesForRow=selectedIncentives.length?selectedIncentives:["_default"];
        const data:Record<string,Record<string,Record<string,IEFieldValue>>>={};
        for(const type of types){
          data[type]={};
          for(const inc of incTypesForRow)data[type][inc]=flatByType[type];
        }
        rowInclExclFromXLS[i]={types,data,viceVersa:{}};
      }
    }
    onConfirm(contract,rows,rowInclExclFromXLS);
  };

  const groups=contractOnly?[
    {label:"Airline Contract Details",cols:contractCols},
    {label:"Remarks",cols:[REMARKS_COL]},
  ]:[
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

const CELL_PLACEHOLDER: Record<string, string> = {
  "c__airline_type":  "GDS / LCC",
  "c__airline_name":  "e.g. Emirates",
  "c__airline_code":  "AI",
  "c__contract_year": "Calendar / Financial year",
  "c__valid_from":    "",
  "c__valid_to":      "",
  "c__trigger_type":  "Flown / Sales",
  "c__payout_type":   "Flown / Sales",
  "c__entity":        "Entity",
  "c__business_type": "B2B / B2C / B2E",
  "c__login_id":      "Agent login ID",
  "c__iata_commission": "IATA %",
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

// Each editable cell's width, sized to what it holds. An input left to size itself is
// ~150px wide, which made a two-letter airline code as wide as the airline's name.
// Incentive columns are keyed by field (inc::{incentive}::{field} → field).
const CELL_WIDTH:Record<string,string>={
  c__airline_name:"w-40",     c__airline_code:"w-12",
  c__airline_type:"w-16",     c__business_type:"w-16",
  c__contract_year:"w-28",    c__trigger_type:"w-20",    c__payout_type:"w-20",
  c__deal_tag:"w-20",         c__entity:"w-32",          c__login_id:"w-28",
  c__iata_commission:"w-14",
  c__valid_from:"w-[108px]",  c__valid_to:"w-[108px]",
  travelValidFrom:"w-[108px]",travelValidTo:"w-[108px]",
  flightType:"w-[100px]",     class:"w-[84px]",          payoutCalcCols:"w-[108px]",
  remarks:"w-48",
};
const cellWidth=(key:string)=>CELL_WIDTH[incCellField(key)||key]??"w-28";

// `entityOptions` are the step-1 entity choices — see the page's stepEntityOptions.
// `vendorLabels` are the Agency Master labels an All-suppliers row's supplier is picked from.
function getColMeta(key:string,entityOptions:string[],vendorLabels:string[]=[]):{type:"date"|"select"|"number"|"text";options?:string[]}{
  if(key==="c__deal_tag")return{type:"select",options:DEAL_TAG_OPTIONS};
  if(key==="c__valid_from"||key==="c__valid_to")return{type:"date"};
  if(key==="c__entity")return{type:"select",options:entityOptions};
  if(key==="c__vendor_agency_id")return{type:"select",options:vendorLabels};
  if(CONTRACT_COL_OPTIONS[key])return{type:"select",options:CONTRACT_COL_OPTIONS[key]};
  const incField=incCellField(key);
  if(incField==="travelValidFrom"||incField==="travelValidTo")return{type:"date"};
  if(incField==="flightType")return{type:"select",options:FLIGHT_TYPE_OPTIONS};
  if(incField==="class")return{type:"select",options:CLASS_OPTIONS};
  if(incField==="payoutCalcCols")return{type:"select",options:PAYOUT_CALC_OPTIONS};
  if(incField==="incentiveAmtPct")return{type:"number"};
  return{type:"text"};
}

// Incentive sub-fields (slabs, matrices, DI tree, etc.) are no longer expanded into
// flat table columns — they're configured per row via the Incentive Data modal
// (IncentiveDataRowModal), which reuses the same IncentiveTabContent the manual
// create-deal form uses, so they get full slab/matrix/dependency support.
// Left to right by what a reviewer reads first: whose deal (All suppliers), which
// airline, its class / rate / rules, then the contract fields, and the read-only
// notes last. `color` is the group's accent line in the table header.
function buildColGroups(dealType:string,aiMode=false,multiVendor=false,incentives:string[]=[]):ColGroup[]{
  const groups:ColGroup[]=[];
  // All suppliers: whose deal each row is, first — on a vendor sheet that is the
  // column a wrong value in costs the most. The sheet's own Source beside the pick.
  if(multiVendor) groups.push({label:"Supplier",color:"#f97316",cols:[
    {key:"__supplier_src__",label:"In Sheet"},
    {key:"c__vendor_agency_id",label:"Agency Master"},
  ]});
  // The airline, and how it resolved against the airline master. The code is
  // editable because it is the only way a reviewer can rescue a row the sheet left
  // without one — without a code the airline cannot be added to the master at all.
  groups.push({label:"Airline",color:"#14b8a6",cols:[
    {key:"c__airline_name",label:"Airline Name"},
    ...(aiMode?[{key:"c__airline_code",label:"Code"},{key:"__airline_master__",label:"Master"}]:[]),
  ]});
  // The incentive, column by column: travel window, flight type, class, what the rate is
  // calculated on, and the rate — so an airline's ECO / PEY / BUS rows read side by side
  // without opening anything. The last column opens every other field of the row's
  // incentives and their inclusion / exclusion rules. Several incentives: a group each.
  const inline=inlineIncentives(incentives);
  const incCols=(inc:string)=>INLINE_INC_FIELDS.map(f=>({key:`inc::${inc}::${f.field}`,label:f.label}));
  const rulesCol={key:"__incentive_data__",label:inline.length?"Rules & More":"Class · Rate · Rules"};
  if(inline.length===1){
    groups.push({label:"Incentive & Rules",color:"#818cf8",cols:[...incCols(inline[0]),rulesCol]});
  }else{
    inline.forEach(inc=>groups.push({label:inc,color:"#818cf8",cols:incCols(inc)}));
    groups.push({label:inline.length?"Rules":"Incentive & Rules",color:"#818cf8",cols:[rulesCol]});
  }
  groups.push({label:"Contract Details",color:"#60a5fa",cols:[
    {key:"c__deal_tag",label:"Deal Tag"},
    ...getContractCols(dealType).filter(c=>c.key!=="c__airline_name"),
  ]});
  // Where each AI-extracted row came from in the file. With 300+ rows, spot-checking
  // against the printed contract is impractical without the page/row it came from.
  groups.push({label:"Notes",color:"#94a3b8",cols:[
    {key:"remarks",label:"Remarks"},
    ...(aiMode?[{key:"__src__",label:"Source in File"}]:[]),
  ]});
  return groups;
}

// Review columns the bulk bar's "Column to edit" never offers: read-only or edited in a popup.
const BULK_SKIP_COLS=new Set(["__incl_excl__","__incentive_data__","__src__","__airline_master__","__supplier_src__"]);

// What the Incentive & Rules button says about a row: the first incentive's class and
// rate ("Economy · 2%"), "slabs" for a slab payout, and how many more incentives are set.
function incentiveSummary(row:ReviewRow,incentives:string[]):{text:string;title:string}|null{
  const parts=incentives.map(inc=>{
    const g=(f:string)=>(row.extra[`inc::${inc}::${f}`]??"").trim();
    const amt=g("incentiveAmtPct");
    const rate=g("amountBasedType")==="Slab Based"?"slabs":amt?(g("incentiveNumPct")==="Number"?amt:`${amt}%`):"";
    const text=[g("class"),rate].filter(Boolean).join(" · ");
    return text?{inc,text}:null;
  }).filter((p):p is {inc:string;text:string}=>!!p);
  if(!parts.length)return null;
  return{
    text:parts[0].text+(parts.length>1?` +${parts.length-1}`:""),
    title:parts.map(p=>`${p.inc}: ${p.text}`).join("\n"),
  };
}

function ReviewTable({
  rows, colGroups, onChange, onDelete, onAdd,
  rowInclExcl, inclExclPopup, setInclExclPopup, onToggleInclExclType,
  onOpenInclExclType, onRemoveInclExclType,
  selectedIncentives, onOpenIncentiveData,
  airlineFilter, selectedRows, onToggleRow, onToggleAllFiltered,
  entityOptions, lockedCols, vendorChoices, entityOptionsFor, rowFilter,
}:{
  rows:ReviewRow[];
  colGroups:ColGroup[];
  /** The step-1 entity choices — the Entity cell offers exactly these. */
  entityOptions:string[];
  /** All suppliers: the agencies a row's supplier is picked from. */
  vendorChoices?:{id:number;label:string}[];
  /** All suppliers: the Entity cell offers the ROW's own agency's entities instead. */
  entityOptionsFor?:(row:ReviewRow)=>string[];
  /** The toolbar's other filters — one Source (All suppliers), Rows not read. */
  rowFilter?:(row:ReviewRow)=>boolean;
  /** Columns fixed by step 1 that the save ignores per row — shown, not editable. */
  lockedCols:string[];
  onChange:(idx:number,key:string,val:string)=>void;
  onDelete:(idx:number)=>void;
  onAdd:()=>void;
  rowInclExcl:Record<number,RowInclExcl>;
  selectedIncentives:string[];
  onOpenIncentiveData:(idx:number)=>void;
  inclExclPopup:number|null;
  setInclExclPopup:(idx:number|null)=>void;
  onToggleInclExclType:(rowIdx:number,type:string)=>void;
  onOpenInclExclType:(rowIdx:number,type:string)=>void;
  onRemoveInclExclType:(rowIdx:number,type:string)=>void;
  /** The airline picked in the bulk bar — the table shows only that airline's rows. */
  airlineFilter?:string;
  selectedRows:Set<number>;
  onToggleRow:(idx:number)=>void;
  onToggleAllFiltered:(filteredIndices:number[],allSelected:boolean)=>void;
}){
  const allCols=colGroups.flatMap(g=>g.cols);
  // Width comes from cellWidth, per column.
  const inp="bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5";
  // Incentives shown as columns of their own, and the rest (edited in the popup only).
  const inline=inlineIncentives(selectedIncentives);
  const popupOnly=selectedIncentives.filter(i=>!inline.includes(i));

  // Master airline names, for the Airline Name type-ahead. Fetched once when the
  // review table mounts — one shared <datalist> rather than a picker component
  // per cell, which on a 345-row sheet would be 345 identical requests. It stays
  // a free-text field on purpose: an airline missing from the master is exactly
  // the case this flow exists to add, so a hard picker would block it.
  const [masterNames,setMasterNames]=useState<string[]>([]);
  useEffect(()=>{
    let alive=true;
    api.get<{name:string}[]>("/airlines/",{params:{limit:5000}})
      .then(({data})=>{if(alive)setMasterNames(data.map(a=>a.name).filter(Boolean));})
      .catch(()=>{/* type-ahead is a convenience; the field works without it */});
    return()=>{alive=false;};
  },[]);

  const getCellValue=(row:ReviewRow,key:string):string=>{
    if(key.startsWith("inc::")||key.startsWith("ie::")||key.startsWith("c__"))return row.extra[key]??"";
    return (row as unknown as Record<string,string>)[key]??"";
  };

  // `gaps`: what this row still needs filling in by hand (unreadGaps) — those cells are marked.
  const renderCell=(row:ReviewRow,idx:number,colKey:string,gaps:string[])=>{
    // Special: read-only provenance. Never edited, never saved — it exists so the
    // reviewer can find this row on the printed page.
    if(colKey==="__src__"){
      const src=row.extra["__src"]??"";
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100">
          {isUnreadRow(row)&&(gaps.length?(
            <span className="mr-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold bg-red-100 text-red-700 border border-red-300">
              <AlertTriangle className="w-2.5 h-2.5"/>fill in
            </span>
          ):(
            <span className="mr-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold bg-gray-50 text-gray-500 border border-gray-200">
              <Check className="w-2.5 h-2.5"/>filled by hand
            </span>
          ))}
          <span className="text-[10px] text-gray-400 whitespace-nowrap" title={src}>
            {src.length>60?src.slice(0,60)+"…":src}
          </span>
        </td>
      );
    }
    // Special: read-only airline-master resolution. Advisory — the server
    // re-resolves on save, so what shows here is what WOULD happen if the row is
    // saved as it currently stands.
    if(colKey==="__airline_master__"){
      const status=row.extra["__air_status"]??"";
      const master=row.extra["__air_master"]??"";
      const note=row.extra["__air_note"]??"";
      const code=row.extra["c__airline_code"]??"";
      const badge=(cls:string,text:string,icon?:React.ReactNode)=>(
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold border ${cls}`}>
          {icon}{text}
        </span>
      );
      let content:React.ReactNode=null;
      // The master's name only when it differs from the row's — repeating the Airline
      // Name cell next to it says nothing and doubles the column's width.
      const rowName=(row.extra["c__airline_name"]||row.airline_name||"").trim().toLowerCase();
      if(status==="resolved"){
        content=badge("bg-emerald-50 text-emerald-700 border-emerald-200",
          "✓ "+(master&&master.trim().toLowerCase()!==rowName?master:"matched"));
      }else if(status==="new"){
        content=badge("bg-sky-50 text-sky-700 border-sky-200",`+ will be added${code?` (${code})`:""}`);
      }else if(status==="conflict"||status==="ambiguous"){
        content=badge("bg-red-50 text-red-700 border-red-300","needs a look",<AlertTriangle className="w-2.5 h-2.5"/>);
      }else if(status==="multi_carrier"){
        content=badge("bg-amber-50 text-amber-700 border-amber-300","multi-carrier",<AlertTriangle className="w-2.5 h-2.5"/>);
      }else if(status){
        content=badge("bg-gray-50 text-gray-500 border-gray-200","not in master");
      }
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100 whitespace-nowrap" title={note||undefined}>
          {content}
        </td>
      );
    }
    // Special: the sheet's own Source cell (All suppliers). Read-only — what the row
    // SAID; the Agency Master column beside it is what it will be saved as.
    if(colKey==="__supplier_src__"){
      const src=row.extra["c__supplier_cell"]??"";
      const set=!!row.extra["c__vendor_agency_id"];
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100 whitespace-nowrap"
          title={set?undefined:"No supplier picked for this row yet"}>
          <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${set?"bg-emerald-500":"bg-red-500"}`}/>
          <span className={`text-[11px] font-semibold ${src?"text-gray-700":"text-gray-400 italic"}`}>{src||"no Source"}</span>
        </td>
      );
    }
    // Special: the row's supplier (All suppliers) — an Agency Master row, by id.
    if(colKey==="c__vendor_agency_id"){
      const val=row.extra["c__vendor_agency_id"]??"";
      return(
        <td key={colKey} className={`px-1 py-1 border-l border-gray-100 ${val?"":"bg-red-50"}`}>
          <select value={val} onChange={e=>onChange(idx,colKey,e.target.value)}
            title={vendorChoices?.find(v=>String(v.id)===val)?.label}
            className={`w-[190px] bg-transparent text-[11px] focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 border-0 truncate ${val?"text-gray-800":"text-red-600 font-semibold"}`}>
            <option value="">— pick supplier —</option>
            {(vendorChoices??[]).map(v=><option key={v.id} value={String(v.id)}>{v.label}</option>)}
          </select>
        </td>
      );
    }
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

    // Special: Incentive Data column. Beside the inline incentive columns it is the way
    // into everything else — it says how many rules the row has, and sums up any incentive
    // that has no columns of its own. Without inline columns it keeps the class and rate.
    if(colKey==="__incentive_data__"&&inline.length){
      const rules=rowInclExcl[idx]?.types?.length??0;
      const other=popupOnly.some(inc=>Object.entries(row.extra).some(([k,v])=>k.startsWith(`inc::${inc}::`)&&v))
        ?(incentiveSummary(row,popupOnly)?.text??popupOnly.join(", ")):"";
      const parts=[other,rules?`${rules} rule${rules!==1?"s":""}`:""].filter(Boolean);
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100 whitespace-nowrap">
          <button
            onClick={()=>onOpenIncentiveData(idx)}
            title="Every field of this row's incentives, and their inclusion / exclusion rules"
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-colors ${parts.length?"bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100":"bg-gray-100 text-gray-500 border-gray-200 hover:border-indigo-300 hover:text-indigo-700"}`}
          >
            {parts.length
              ?<><Check className="w-2.5 h-2.5"/>{parts.join(" · ")}</>
              :<><Settings2 className="w-2.5 h-2.5"/>Edit</>}
          </button>
        </td>
      );
    }
    if(colKey==="__incentive_data__"){
      const hasData=Object.entries(row.extra).some(([k,v])=>k.startsWith("inc::")&&v)
        || ((rowInclExcl[idx]?.types?.length??0)>0);
      const summary=hasData?incentiveSummary(row,selectedIncentives):null;
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100 whitespace-nowrap">
          <button
            onClick={()=>onOpenIncentiveData(idx)}
            disabled={selectedIncentives.length===0}
            title={summary?`${summary.title}\nClick to edit incentive fields and rules`:undefined}
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${hasData?"bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100":"bg-gray-100 text-gray-500 border-gray-200 hover:border-indigo-300 hover:text-indigo-700"}`}
          >
            {hasData
              ?<><Check className="w-2.5 h-2.5"/>{summary?.text??"Configured"}</>
              :<><Settings2 className="w-2.5 h-2.5"/>Configure ({selectedIncentives.length})</>}
          </button>
        </td>
      );
    }

    const w = cellWidth(colKey);
    const sel = `${w} bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 border-0`;
    const txt = `${inp} ${w}`;
    const val = getCellValue(row,colKey);
    const change = (v:string)=>onChange(idx,colKey,v);
    // A cell an unread row still needs — outlined red until it is filled in.
    const td = `px-1 py-1 border-l border-gray-100${gaps.includes(colKey)?" bg-red-100/70 ring-1 ring-inset ring-red-300":""}`;

    // The incentive's own columns (INLINE_INC_FIELDS) — the same values the popup edits.
    const incField=incCellField(colKey);
    if(incField){
      if(incField==="travelValidFrom"||incField==="travelValidTo")return(
        <td key={colKey} className={td}>
          <input type="date" className={txt} value={val} onChange={e=>change(e.target.value)}/>
        </td>
      );
      if(incField==="incentiveAmtPct"){
        const inc=colKey.split("::")[1];
        // A slab payout has no single rate — its slabs are edited in the popup.
        if(isSlabPayout(row.extra,inc))return(
          <td key={colKey} className={td}>
            <button onClick={()=>onOpenIncentiveData(idx)} title="Paid by slabs — open to edit them"
              className="px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100">
              slabs
            </button>
          </td>
        );
        const flat=isFlatPayout(row.extra,inc);
        return(
          <td key={colKey} className={td}>
            <div className="flex items-center gap-0.5">
              {flat&&<span className="text-[11px] text-gray-500">₹</span>}
              <input type="number" step="any" min={0} value={val} onChange={e=>change(e.target.value)} placeholder="—"
                title={flat?"Fixed amount per ticket (a FLAT deal)":"Rate in percent"}
                className="w-16 bg-transparent text-[11px] font-semibold text-gray-800 text-right tabular-nums focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5"/>
              {/* % ⇄ ₹: a percentage of the fare, or a FLAT amount per ticket. */}
              <button type="button" onClick={()=>onChange(idx,`inc::${inc}::incentiveNumPct`,flat?"Percentage":"Number")}
                title={flat?"Flat amount per ticket — click to make it a percentage":"Percentage — click to make it a flat amount per ticket"}
                className={`text-[10px] font-semibold rounded px-1 py-0.5 border ${flat
                  ?"bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100"
                  :"bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"}`}>
                {flat?"flat":"%"}
              </button>
            </div>
          </td>
        );
      }
      // A FLAT deal is paid as it stands, so it has no Calc On.
      if(incField==="payoutCalcCols"&&isFlatPayout(row.extra,colKey.split("::")[1]))return(
        <td key={colKey} className={td} title="A flat amount is paid per ticket as it stands — no Basic / + YQ base to take it on">
          <span className={`text-[11px] text-gray-400 italic ${cellWidth(colKey)} inline-block px-1`}>flat amount</span>
        </td>
      );
      // Flight Type / Class / Calc On. A sheet value outside the list stays visible, to change.
      const base=getColMeta(colKey,entityOptions).options??[];
      const opts=val&&!base.includes(val)?[val,...base]:base;
      return(
        <td key={colKey} className={td}>
          <select value={val} onChange={e=>change(e.target.value)} className={sel}>
            <option value="">—</option>
            {opts.map(o=><option key={o} value={o}>{o}</option>)}
          </select>
        </td>
      );
    }

    if(lockedCols.includes(colKey)){
      return(
        <td key={colKey} className="px-2 py-1 border-l border-gray-100" title="Set in Deal Details — go back to change it">
          <span className="text-[11px] text-gray-500 whitespace-nowrap">{val||"—"}</span>
        </td>
      );
    }

    // Entity dropdown — the same choices step 1 offered. A sheet value outside them
    // is still shown, so it is visibly there to change rather than silently saved.
    if(colKey==="c__entity"){
      const base=entityOptionsFor?entityOptionsFor(row):entityOptions;
      const opts=val&&!base.includes(val)?[val,...base]:base;
      return(
        <td key={colKey} className="px-1 py-1 border-l border-gray-100">
          <select value={val} onChange={e=>change(e.target.value)} className={sel}>
            <option value="">—</option>
            {opts.map(e=><option key={e} value={e}>{e}</option>)}
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
          <input type="date" className={txt} value={val} onChange={e=>change(e.target.value)}/>
        </td>
      );
    }

    // Default text input
    return(
      <td key={colKey} className={td}>
        <input
          className={txt}
          list={colKey==="c__airline_name"?"airline-master-names":undefined}
          value={val}
          onChange={e=>change(e.target.value)}
          placeholder={CELL_PLACEHOLDER[colKey]??"—"}
        />
      </td>
    );
  };

  // Rows the toolbar's Airline / Supplier filters leave
  const filteredIndices:number[]=rows.reduce<number[]>((acc,row,i)=>{
    if(airlineFilter&&(row.extra["c__airline_name"]||row.airline_name||"").trim()!==airlineFilter)return acc;
    if(rowFilter&&!rowFilter(row))return acc;
    acc.push(i);
    return acc;
  },[]);
  const allFilteredSelected=filteredIndices.length>0&&filteredIndices.every(i=>selectedRows.has(i));
  const someFilteredSelected=filteredIndices.some(i=>selectedRows.has(i));

  // Header: one navy for every group, each group marked by its accent line underneath.
  // Both header rows stick to the top of the scroll area (the second one 32px down,
  // under the first's fixed h-8), and the checkbox / # cells also stick to the left.
  const HEAD="#1e3a5f", SUBHEAD="#2d4f7c";
  return(
    <div className="border-t border-gray-200">
      {/* One shared options list for every Airline Name cell. */}
      <datalist id="airline-master-names">
        {masterNames.map(n=><option key={n} value={n}/>)}
      </datalist>
      {/* Its own scroll area, so the horizontal scrollbar stays in view instead of
          sitting under the last of 300 rows. */}
      <div className="overflow-auto max-h-[70vh]">
      <table className="w-full min-w-max border-collapse">
        <thead>
          <tr className="h-8">
            {/* Select-all checkbox */}
            <th className="w-9 min-w-9 px-2 sticky top-0 left-0 z-30" style={{background:HEAD}}>
              <input
                type="checkbox"
                checked={allFilteredSelected}
                ref={el=>{if(el)el.indeterminate=!allFilteredSelected&&someFilteredSelected;}}
                onChange={()=>onToggleAllFiltered(filteredIndices,allFilteredSelected)}
                className="accent-blue-400 cursor-pointer"
                title={allFilteredSelected?"Deselect all visible":"Select all visible"}
              />
            </th>
            <th className="px-2 text-[10px] text-white font-semibold sticky top-0 left-9 z-30 whitespace-nowrap" style={{background:HEAD}}>#</th>
            {colGroups.map(g=>(
              <th key={g.label} colSpan={g.cols.length}
                className="px-2 text-[10px] text-white font-bold uppercase tracking-wider text-left border-l border-white/15 whitespace-nowrap sticky top-0 z-20"
                style={{background:HEAD,boxShadow:`inset 0 -3px 0 ${g.color}`}}>
                {g.label}
              </th>
            ))}
            <th className="px-2 sticky top-0 z-20" style={{background:HEAD}}/>
          </tr>
          <tr>
            <th className="px-2 py-1.5 sticky top-8 left-0 z-30" style={{background:SUBHEAD}}/>
            <th className="px-2 py-1.5 sticky top-8 left-9 z-30" style={{background:SUBHEAD}}/>
            {allCols.map(c=>(
              <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white/85 whitespace-nowrap border-l border-white/10 sticky top-8 z-20" style={{background:SUBHEAD}}>{c.label}</th>
            ))}
            <th className="px-2 py-1.5 sticky top-8 z-20" style={{background:SUBHEAD}}/>
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
            // A row the file could not be read for is red until it is filled in; the #
            // cell says what it still needs and what the file printed for it.
            const unread=isUnreadRow(row);
            const gaps=unreadGaps(row,inline);
            const blank=gaps.length>0;
            const stickyBg=blank?(isSelected?"bg-red-100":"bg-red-50 group-hover:bg-red-100")
              :isSelected?"bg-blue-50":"bg-white group-hover:bg-blue-50";
            const unreadTitle=unread?[
              blank?`Could not be read from the file — fill in ${gapLabels(gaps).join(", ")}.`
                :"Could not be read from the file — filled in by hand.",
              row.extra["__src"]?`In the file: ${row.extra["__src"]}`:"",
            ].filter(Boolean).join("\n"):undefined;
            return(
              <tr key={idx} className={`border-b group ${blank
                ?`border-red-200 ${isSelected?"bg-red-100":"bg-red-50 hover:bg-red-100/60"}`
                :`border-gray-100 ${isSelected?"bg-blue-50":"hover:bg-blue-50/40"}`}`}>
                <td className={`w-9 min-w-9 px-2 py-1.5 sticky left-0 z-10 ${stickyBg}`}
                  style={blank?{boxShadow:"inset 3px 0 0 #ef4444"}:undefined}>
                  <input type="checkbox" checked={isSelected} onChange={()=>onToggleRow(idx)} className="accent-blue-500 cursor-pointer"/>
                </td>
                <td className={`px-2 py-1.5 text-[10px] sticky left-9 z-10 whitespace-nowrap ${stickyBg}`} title={unreadTitle}>
                  {unread
                    ?<span className={`inline-flex items-center gap-0.5 font-semibold ${blank?"text-red-600":"text-emerald-600"}`}>
                      {blank?<AlertTriangle className="w-3 h-3"/>:<Check className="w-3 h-3"/>}{idx+1}
                    </span>
                    :<span className="text-gray-400">{idx+1}</span>}
                </td>
                {allCols.map(c=>renderCell(row,idx,c.key,gaps))}
                <td className="px-2 py-1.5">
                  <button onClick={()=>onDelete(idx)} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded text-red-400"><Trash2 className="w-3.5 h-3.5"/></button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <div className="px-4 py-2.5 border-t border-gray-100">
        <button onClick={onAdd} className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline">
          <Plus className="w-3.5 h-3.5"/> Add row manually
        </button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// XLS TEMPLATE GENERATOR — tab-wise workbook (one sheet per incentive type)
// ═══════════════════════════════════════════════════════════════════════════════
// ── Multi-tab (tabbed) template: 1 contract sheet + 1 sheet per incentive type ──
// Each incentive sheet = "Deal No" + that incentive's FIXED fields + the selected
// incl/excl rule blocks. Sheets join on "Deal No". The template reflects the Step-1
// selection: only the chosen incentive types get a sheet, and only the chosen
// inclusion/exclusion rule types become columns. Empty selection ⇒ everything.
function downloadMultiTabTemplate(dealType:string, incentiveTypes:string[], inclExclTypes:string[], code?:{key:MtCodeKey;value:string}|null){
  const incs = incentiveTypes.length ? incentiveTypes : INCENTIVE_TYPES;
  const ies  = inclExclTypes.length  ? inclExclTypes  : INCLUSIONS_EXCLUSIONS;

  const wb = XLSX.utils.book_new();
  const addSheet=(name:string, headers:string[], sample:string[])=>{
    const ws = XLSX.utils.aoa_to_sheet([headers, sample]);
    ws["!cols"] = headers.map(h => ({ wch: Math.max(h.length + 2, 14) }));
    // Excel sheet names: max 31 chars, no []:*?/\
    XLSX.utils.book_append_sheet(wb, ws, name.replace(/[[\]:*?/\\]/g,"").slice(0,31));
  };

  // Sheet 1 — contract header (columns vary by deal type)
  const cCols = mtContractCols(dealType, code?.key ?? null);
  addSheet(MT_CONTRACT_SHEET, cCols.map(c=>c.label),
    cCols.map(c=>c.key===code?.key ? (code.value ?? "") : mtContractSample(c.key)));

  // One sheet per selected incentive type
  for(const inc of incs){
    const fixed = incentiveFixedCols(inc).map(c=>c.label);
    const ie = ies.flatMap(rt => INCL_EXCL_FIELDS.map(f=>`${f.label} for ${rt}`));
    const headers = ["Deal No", ...fixed, ...ie];
    const sample  = ["1", ...headers.slice(1).map(()=>"")];
    addSheet(inc, headers, sample);
  }

  XLSX.writeFile(wb, "deal_template.xlsx");
}

// Parse a filled multi-tab workbook entirely in the browser: read all sheets, join
// rows by "Deal No", and assemble the same ReviewRow[] + rowInclExcl the Step-3
// review uses. Returns unions of incentive/rule types for grid visibility.
function parseMultiTabWorkbook(wb: XLSX.WorkBook, dealType:string): {
  rows: ReviewRow[];
  rowInclExcl: Record<number, RowInclExcl>;
  incentiveUnion: string[];
  inclExclUnion: string[];
}{
  const json=(name:string)=>XLSX.utils.sheet_to_json<Record<string,string>>(wb.Sheets[name], {defval:"", raw:false});

  // ── Contract sheet → Map<dealNo, contract extra> (order preserved) ──
  const contractRev=new Map<string,string>();
  for(const c of MT_CONTRACT_COLS_ALL) contractRev.set(c.label.toLowerCase(), c.key);

  const dealOrder:string[]=[];
  const contractByDeal=new Map<string,Record<string,string>>();
  for(const row of json(MT_CONTRACT_SHEET)){
    const dealNo=String(row["Deal No"]??"").trim();
    if(!dealNo) continue;
    if(contractByDeal.has(dealNo)) continue;
    const extra:Record<string,string>={};
    for(const [label,raw] of Object.entries(row)){
      const key=contractRev.get(label.toLowerCase().trim());
      if(!key||key.startsWith("__")) continue;   // Deal No / Supplier Code are not deal fields
      let v=String(raw??"").trim();
      if(!v) continue;
      if(key==="c__valid_from"||key==="c__valid_to") v=mtDateStr(v);
      else { const opts=MT_SELECT_OPTIONS[key]; if(opts) v=normalizeSelectValue(v,opts); }
      extra[key]=v;
    }
    if(!extra["c__business_type"] && dealType==="b2b") extra["c__business_type"]="B2B";
    extra["c__deal_tag"]="Standard";
    contractByDeal.set(dealNo, extra);
    dealOrder.push(dealNo);
  }

  // ── Incl/Excl header reverse map: "<field> for <ruleType>" → {rt, key} ──
  const ieRev=new Map<string,{rt:string;key:string}>();
  for(const rt of INCLUSIONS_EXCLUSIONS)
    for(const f of INCL_EXCL_FIELDS)
      ieRev.set(`${f.label} for ${rt}`.toLowerCase(), {rt, key:f.key});

  // ── Each incentive sheet → per-deal incentive data + incl/excl ──
  const incExtraByDeal=new Map<string,Record<string,string>>();
  const incTypesByDeal=new Map<string,Set<string>>();
  const ieByDeal=new Map<string,{types:Set<string>;data:Record<string,Record<string,Record<string,IEFieldValue>>>}>();

  for(const inc of INCENTIVE_TYPES.filter(i=>wb.SheetNames.includes(i))){
    const fixedRev=new Map<string,string>();
    for(const c of incentiveFixedCols(inc)) fixedRev.set(c.label.toLowerCase(), c.key);

    for(const row of json(inc)){
      const dealNo=String(row["Deal No"]??"").trim();
      if(!dealNo||!contractByDeal.has(dealNo)) continue;
      const incExtra=incExtraByDeal.get(dealNo)??{};
      const ie=ieByDeal.get(dealNo)??{types:new Set<string>(),data:{}};
      let hasFixed=false;

      for(const [label,raw] of Object.entries(row)){
        const lab=label.toLowerCase().trim();
        if(lab==="deal no") continue;
        const v0=String(raw??"").trim();
        if(!v0) continue;

        const fkey=fixedRev.get(lab);
        if(fkey){
          let v=v0;
          if(mtIsDateLabel(lab)) v=mtDateStr(v);
          else { const opts=MT_SELECT_OPTIONS[fkey]; if(opts) v=normalizeSelectValue(v,opts); }
          incExtra[`inc::${inc}::${fkey}`]=v;
          hasFixed=true;
          continue;
        }

        const ier=ieRev.get(lab);
        if(ier){
          if(!ie.data[ier.rt]) ie.data[ier.rt]={};
          if(!ie.data[ier.rt][inc]) ie.data[ier.rt][inc]={};
          const tgt=ie.data[ier.rt][inc];
          if(ier.key==="_dateExclusion"){
            const lower=v0.toLowerCase();
            if(lower.includes("ticket")) tgt["dateExclusionTicket"]="true";
            if(lower.includes("travel")) tgt["dateExclusionTravel"]="true";
          } else if(mtIsDateLabel(lab)){
            tgt[ier.key]=mtDateStr(v0);
          } else {
            const parts=v0.split("|").map(s=>s.trim()).filter(Boolean);
            tgt[ier.key]=parts.length>1?parts:parts[0];
          }
          ie.types.add(ier.rt);
        }
      }

      incExtraByDeal.set(dealNo, incExtra);
      ieByDeal.set(dealNo, ie);
      if(hasFixed){ const s=incTypesByDeal.get(dealNo)??new Set<string>(); s.add(inc); incTypesByDeal.set(dealNo,s); }
    }
  }

  // ── Assemble rows in contract-sheet order ──
  const rows:ReviewRow[]=[];
  const rowInclExcl:Record<number,RowInclExcl>={};
  const incentiveUnion=new Set<string>();
  const inclExclUnion=new Set<string>();

  dealOrder.forEach((dealNo,i)=>{
    const cExtra=contractByDeal.get(dealNo)??{};
    const incExtra=incExtraByDeal.get(dealNo)??{};
    (incTypesByDeal.get(dealNo)??new Set<string>()).forEach(t=>incentiveUnion.add(t));
    rows.push({
      row_order:i, airline_name:"", iata_code:"",
      eco_commission:"", peco_commission:"", bus_commission:"",
      valid_on:"", validity_raw:"", remarks:cExtra["r__remarks"]??"",
      extra:{...cExtra, ...incExtra},
    });
    const ie=ieByDeal.get(dealNo);
    if(ie && ie.types.size>0){
      [...ie.types].forEach(t=>inclExclUnion.add(t));
      rowInclExcl[i]={types:[...ie.types], data:ie.data, viceVersa:{}};
    }
  });

  return {rows, rowInclExcl, incentiveUnion:[...incentiveUnion], inclExclUnion:[...inclExclUnion]};
}

// ═══════════════════════════════════════════════════════════════════════════════
// ALL SUPPLIERS — one line per Source value of a multi-supplier sheet
// ═══════════════════════════════════════════════════════════════════════════════
// Map a Source once and every row of it follows; drop the rows of a supplier that is
// not yours to load (an OTA's own "YATRA" lines on the sheet it compiles). Rows stay
// editable one by one in the table — a line whose rows no longer agree says "mixed".
const SOURCE_STATE: Record<string,{label:string;cls:string}> = {
  remembered:    {label:"✓ saved mapping",    cls:"bg-emerald-50 text-emerald-700 border-emerald-200"},
  matched:       {label:"✓ matched",          cls:"bg-emerald-50 text-emerald-700 border-emerald-200"},
  suggested:     {label:"check suggestion",   cls:"bg-amber-50 text-amber-700 border-amber-300"},
  ambiguous:     {label:"pick the branch",    cls:"bg-amber-50 text-amber-700 border-amber-300"},
  not_onboarded: {label:"not onboarded",      cls:"bg-red-50 text-red-700 border-red-300"},
  blank:         {label:"no Source in sheet", cls:"bg-gray-50 text-gray-500 border-gray-200"},
  set:           {label:"set by you",         cls:"bg-blue-50 text-blue-700 border-blue-200"},
  mixed:         {label:"mixed",              cls:"bg-blue-50 text-blue-700 border-blue-200"},
};

function SupplierSourcesPanel({
  summary, rows, vendorChoices, filter, onFilter, onAssign, onRemove, onRefresh, refreshing,
}:{
  summary:SupplierSource[];
  rows:ReviewRow[];
  vendorChoices:{id:number;label:string}[];
  filter:string;
  onFilter:(group:string)=>void;
  onAssign:(group:string,agencyId:string)=>void;
  onRemove:(group:string)=>void;
  onRefresh:()=>void;
  refreshing:boolean;
}){
  const labelOf=new Map(vendorChoices.map(v=>[String(v.id),v.label]));
  const lines=summary.map((s,order)=>{
    const mine=rows.filter(r=>r.extra["__src_group"]===s.group);
    const picks=new Set(mine.map(r=>r.extra["c__vendor_agency_id"]??""));
    const current=picks.size===1?[...picks][0]:picks.size>1?"mixed":"";
    const missing=mine.filter(r=>!r.extra["c__vendor_agency_id"]).length;
    const state=current==="mixed"?"mixed":!current?s.status:current===String(s.agency_id??"")?s.status:"set";
    return{s,order,count:mine.length,current,missing,state};
  })
    .filter(l=>l.count>0)
    // What still needs a person first; sheet order otherwise.
    .sort((a,b)=>(Number(b.missing>0)-Number(a.missing>0))||(a.order-b.order));
  // Over EVERY row, not just the lines: a row added by hand belongs to no Source and
  // still cannot be saved without a supplier.
  const unassigned=rows.filter(r=>!r.extra["c__vendor_agency_id"]).length;
  const total=rows.length;
  // Folded to its header once every row has a supplier — the table is what is left to
  // review then — and opened by itself whenever a row needs one.
  // (Adjusted during render, not in an effect: reopen on the change to "needs work".)
  const needsWork=unassigned>0;
  const [open,setOpen]=useState(needsWork);
  const [prevNeedsWork,setPrevNeedsWork]=useState(needsWork);
  if(needsWork!==prevNeedsWork){ setPrevNeedsWork(needsWork); if(needsWork) setOpen(true); }

  return(
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className={`px-4 py-2.5 flex items-center gap-3 flex-wrap ${open?"border-b border-gray-100":""}`}>
        <button type="button" onClick={()=>setOpen(o=>!o)} className="flex items-center gap-1.5 group"
          title={open?"Hide the supplier mapping":"Show the supplier mapping"}>
          <ChevronDown className={`w-3.5 h-3.5 text-[#9a3412] transition-transform ${open?"":"-rotate-90"}`}/>
          <h2 className="text-xs font-semibold text-[#9a3412] uppercase tracking-wide group-hover:underline">Suppliers in this sheet</h2>
        </button>
        <span className="text-[11px] text-gray-400">{lines.length} source{lines.length!==1?"s":""} · {total} rows</span>
        {unassigned>0
          ?<span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-50 text-red-700 border border-red-300">
              {unassigned} row{unassigned!==1?"s":""} still need{unassigned===1?"s":""} a supplier
            </span>
          :<span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              ✓ every row has a supplier
            </span>}
        <div className="ml-auto flex items-center gap-3">
          {/* A new tab: leaving this page would lose the whole review. */}
          <Link href="/user-master/agency-master" target="_blank" className="text-[11px] font-semibold text-sky-600 hover:underline">
            Onboard an agency ↗
          </Link>
          <button type="button" onClick={onRefresh} disabled={refreshing}
            className="flex items-center gap-1 text-[11px] font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50">
            <RefreshCw className={`w-3 h-3 ${refreshing?"animate-spin":""}`}/>Refresh agency list
          </button>
          {!open&&(
            <button type="button" onClick={()=>setOpen(true)} className="text-[11px] font-semibold text-blue-600 hover:underline">
              Review mapping
            </button>
          )}
        </div>
      </div>
      {open&&<table className="w-full">
        <thead>
          <tr className="bg-gray-50 text-[10px] uppercase tracking-wide text-gray-500">
            <th className="px-4 py-1.5 text-left font-semibold">In sheet</th>
            <th className="px-2 py-1.5 text-right font-semibold">Rows</th>
            <th className="px-3 py-1.5 text-left font-semibold">Saved under (Agency Master)</th>
            <th className="px-2 py-1.5 text-left font-semibold">Status</th>
            <th className="px-4 py-1.5"/>
          </tr>
        </thead>
        <tbody>
          {lines.map(({s,count,current,missing,state})=>{
            const badge=SOURCE_STATE[state]??SOURCE_STATE.not_onboarded;
            const offered=s.candidates.map(String).filter(id=>labelOf.has(id));
            const showing=filter===s.group;
            return(
              <tr key={s.group} className={`border-t border-gray-100 align-top ${missing?"bg-red-50/30":""}`}>
                <td className="px-4 py-1.5 whitespace-nowrap">
                  <span className="text-xs font-bold text-gray-800">
                    {s.source||<span className="italic font-normal text-gray-400">no Source</span>}
                  </span>
                  {s.channel&&<span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-gray-100 text-gray-500">{s.channel}</span>}
                </td>
                <td className="px-2 py-1.5 text-right text-xs text-gray-600 tabular-nums">{count}</td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <select value={current==="mixed"?"":current} onChange={e=>{if(e.target.value)onAssign(s.group,e.target.value);}}
                      className={`w-full max-w-sm border rounded-md px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${current?"border-gray-200 text-gray-800":"border-red-300 text-red-600"}`}>
                      <option value="">{current==="mixed"?"— mixed: pick one for every row —":"— pick supplier —"}</option>
                      {offered.length>0&&(
                        <optgroup label={s.status==="suggested"?"Suggested":"Possible matches"}>
                          {offered.map(id=><option key={`c${id}`} value={id}>{labelOf.get(id)}</option>)}
                        </optgroup>
                      )}
                      <optgroup label="All agencies">
                        {vendorChoices.map(v=><option key={v.id} value={String(v.id)}>{v.label}</option>)}
                      </optgroup>
                    </select>
                    {!current&&offered.length===1&&(
                      <button type="button" onClick={()=>onAssign(s.group,offered[0])}
                        className="whitespace-nowrap text-[11px] font-semibold text-blue-700 hover:underline">
                        Use suggestion
                      </button>
                    )}
                  </div>
                  {missing>0&&s.note&&<p className="text-[10px] text-gray-500 mt-0.5">{s.note}</p>}
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap" title={s.note??undefined}>
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border ${badge.cls}`}>
                    {badge.label}
                  </span>
                </td>
                <td className="px-4 py-1.5 whitespace-nowrap text-right">
                  {s.status==="not_onboarded"&&missing>0&&(
                    <Link href="/user-master/agency-master" target="_blank" className="text-[11px] font-semibold text-sky-600 hover:underline mr-3">
                      Onboard ↗
                    </Link>
                  )}
                  <button type="button" onClick={()=>onFilter(showing?"":s.group)} className="text-[11px] font-medium text-blue-600 hover:underline mr-3">
                    {showing?"Show all rows":"Show rows"}
                  </button>
                  <button type="button" onClick={()=>onRemove(s.group)} className="text-[11px] font-medium text-red-500 hover:underline">
                    Remove rows
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════════
export default function UploadDealPage(){
  const router=useRouter();
  const [step,setStep]=useState<1|2|3|4>(1);

  // ── Step 1 state ────────────────────────────────────────────────────────────
  const [dealType,      setDealType]      = useState("");           // "airline" | "b2b"
  const [direction,     setDirection]     = useState("inbound");    // "inbound" (received) | "outbound" (floated)
  const [dealTag,       setDealTag]       = useState("standard");   // "standard" | "adhoc"
  const [supplierName,  setSupplierName]  = useState("");
  // The Agency Master row an incoming B2B upload is signed with. The server derives the
  // deals' supplier name AND supplier-master id from it, which also gives an uploaded deal
  // a supplier id for the first time — before this an upload carried only the name.
  const [agencies,       setAgencies]       = useState<VendorAgency[]>([]);
  const [vendorAgencyId, setVendorAgencyId] = useState<number | null>(null);
  const vendorOptions = useMemo(() => vendorAgencyOptions(agencies), [agencies]);
  const vendorAgency = vendorAgencyId != null ? agencies.find(a => a.id === vendorAgencyId) ?? null : null;
  // "All suppliers": a multi-vendor sheet — one row per airline per supplier, the supplier
  // in a Source column — loaded in one go. No supplier is picked for the upload; each
  // row's is read from its Source, matched to Agency Master and settled in review.
  const [allSuppliers, setAllSuppliers] = useState(false);
  // What a row's supplier is picked from: the same agencies, labels and order as above.
  const vendorChoices = useMemo(
    () => vendorOptions.labels.map(label => ({ id: vendorOptions.byLabel.get(label)!.id, label })),
    [vendorOptions]);
  // Entity the deal is signed under — the user's own entities from My Profile, EXCEPT on an
  // incoming B2B deal, where it is one of the picked supplier's entities from Agency Master
  // (see `agencyParty` below).
  const [entity,        setEntity]        = useState("");
  const [entityOptions, setEntityOptions] = useState<string[]>([]);
  // The picked supplier agency's own entities and credentials (User master → Agency Master
  // → Agency Entities / Agency Login IDs), and the credentials chosen for this upload.
  const [agencyEntities, setAgencyEntities] = useState<{id:number;name:string;code:string}[]>([]);
  const [agencyLoginIds, setAgencyLoginIds] = useState<{id:number;login_id:string;entity_id:number|null}[]>([]);
  const [loginIds,       setLoginIds]       = useState<string[]>([]);
  const [validFromDate, setValidFromDate] = useState("");
  const [file,          setFile]          = useState<File|null>(null);
  const [dragging,     setDragging]     = useState(false);
  const [uploading,    setUploading]    = useState(false);
  const [uploadError,  setUploadError]  = useState("");
  // Is the file from the supplier picked in Step 1? Checked on the server before an
  // incoming B2B file is extracted. A mismatch stops the upload until the user switches
  // supplier, picks another file, or says it is right anyway; "unknown" (a file that
  // names nobody) is let through with a note.
  type SupplierCheck={status:"match"|"mismatch"|"unknown";message:string;found:string|null;found_agency_ids:number[];basis:string};
  const [supplierCheck, setSupplierCheck] = useState<SupplierCheck|null>(null);
  const [supplierOverride, setSupplierOverride] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [selectedIncentives, setSelectedIncentives] = useState<string[]>([]);
  const [selectedInclExcl,   setSelectedInclExcl]   = useState<string[]>([]);
  const [copyPrevInclExcl,   setCopyPrevInclExcl]   = useState(true);

  // ── Outgoing-deal scope: WHO the deal is floated to ────────────────────────
  // Orthogonal to `dealType`, which stays "b2b" for every outgoing deal.
  const [scopeKind, setScopeKind] = useState<OutgoingDealKind>("b2b");
  const [scopeSel,  setScopeSel]  = useState<ScopeSelection>({
    agencyId:null, corporateId:null, agencyEntityId:null, entity:"", loginIds:[],
  });
  const [scopeTouched, setScopeTouched] = useState(false);
  const outbound  = direction==="outbound";
  const multiVendor = !outbound && dealType==="b2b" && allSuppliers;
  const scopeType: DealScopeType = outbound ? toScopeType(scopeKind) : "all";
  /** Is the counterparty answered? A Common deal needs no party. */
  const scopeComplete = !outbound
    || scopeType==="all"
    || (scopeType==="agency"    && scopeSel.agencyId    != null)
    || (scopeType==="corporate" && scopeSel.corporateId != null);

  // Do Entity + Login ID / IATA come from the picked supplier's Agency Master records?
  // EXACTLY when Create Deal says so (deals/new/page.tsx::agencyParty): every incoming B2B
  // deal, Standard and Adhoc alike. The server applies the same rule
  // (api/v1/deals.py::confirm_upload, `party_from_agency`), so the two cannot disagree about
  // which rows the picked credentials land on.
  const agencyParty = !outbound && dealType==="b2b";
  const agencyEntityId = agencyParty ? (agencyEntities.find(e=>e.name===entity)?.id ?? null) : null;

  // An incoming B2B upload starts with PLB picked and today as Valid From — both still
  // editable. Functional updates, so a choice already made (or an email's valid_from) stays.
  useEffect(()=>{
    if(outbound||dealType!=="b2b") return;
    setSelectedIncentives(p=>p.length?p:["PLB"]);
    setValidFromDate(p=>p||new Date().toLocaleDateString("en-CA"));   // local YYYY-MM-DD
  },[outbound,dealType]);

  // A different supplier (or leaving B2B Standard) means a different set of entities, so
  // the entity and credentials picked for the old one are dropped rather than carried
  // across onto a supplier they do not belong to.
  useEffect(()=>{
    setEntity("");
    setLoginIds([]);
    setAgencyLoginIds([]);
    if(!agencyParty||vendorAgencyId==null){ setAgencyEntities([]); return; }
    api.get<{id:number;name:string;code:string}[]>("/agency-entities/",{params:{agency_id:vendorAgencyId,limit:1000}})
      .then(r=>setAgencyEntities(r.data))
      .catch(()=>setAgencyEntities([]));
  },[agencyParty,vendorAgencyId]);

  // Credentials belong to an ENTITY, so they are loaded for the one picked — the same
  // agency_id + entity_id pair Create Deal asks for.
  useEffect(()=>{
    setLoginIds([]);
    if(!agencyParty||vendorAgencyId==null||agencyEntityId==null){ setAgencyLoginIds([]); return; }
    // The whole agency, narrowed here — as on Create Deal: a login id saved WITHOUT an
    // entity belongs to every entity of the agency, and a server-side entity filter can
    // never return it. Deactivated credentials are not offered.
    api.get<{id:number;login_id:string;entity_id:number|null;is_active?:boolean}[]>("/agency-login-ids/",{params:{agency_id:vendorAgencyId,limit:1000}})
      .then(r=>setAgencyLoginIds(r.data.filter(l=>l.is_active!==false&&(l.entity_id==null||l.entity_id===agencyEntityId))))
      .catch(()=>setAgencyLoginIds([]));
  },[agencyParty,vendorAgencyId,agencyEntityId]);

  const agencyEntityNames = Array.from(new Set(agencyEntities.map(e=>e.name).filter(Boolean)));
  const agencyLoginIdOptions = Array.from(new Set(agencyLoginIds.map(l=>l.login_id).filter(Boolean)));
  const agencyEntityPlaceholder =
      vendorAgencyId==null         ? "Select a supplier first"
    : agencyEntities.length===0    ? "No entities for this agency"
    :                                "Search entity…";
  const agencyLoginPlaceholder =
      !entity                      ? "Select an entity first"
    : agencyLoginIds.length===0    ? "No login IDs for this entity"
    :                                "Select…";

  // What the review table's Entity and Login ID columns are filled from and offer: the
  // entity and credentials picked in step 1 — the scoped agency's outgoing, the picked
  // supplier's on incoming B2B, the user's own profile entities on any other incoming deal.
  const stepEntity        = outbound ? scopeSel.entity : entity;
  const stepLoginIds      = outbound ? scopeSel.loginIds : agencyParty ? loginIds : [];
  const stepLoginValue    = stepLoginIds.join(", ");
  const stepEntityOptions = outbound ? (scopeSel.entity ? [scopeSel.entity] : [])
                          : agencyParty ? agencyEntityNames
                          : entityOptions;
  // Outgoing, the server files every row under the scoped agency's entity, and under its
  // login IDs when any were picked (api/v1/deals.py::confirm_upload), whatever the row
  // says. Those cells are shown read-only in review, so an edit cannot be silently dropped.
  const lockedPartyCols = outbound ? (stepLoginIds.length ? ["c__entity","c__login_id"] : ["c__entity"]) : [];

  // Fills a row's Entity / Login ID from step 1. Incoming, a sheet Entity naming one of the
  // step-1 options is kept (normalized); anything else becomes the step-1 entity. The
  // picked credentials belong to the step-1 entity, so they go only on rows filed under
  // it, and a Login ID the sheet already has is not overwritten unless it is locked.
  const fillStepParty=(extra:Record<string,string>):Record<string,string>=>{
    const sheetEntity=(extra["c__entity"]??"").trim();
    const known=sheetEntity?stepEntityOptions.find(o=>o.toLowerCase()===sheetEntity.toLowerCase()):undefined;
    const rowEntity=outbound?stepEntity:(known??(stepEntity||sheetEntity));
    const underStepEntity=!stepEntity||rowEntity===stepEntity;
    return{
      ...extra,
      c__entity:   rowEntity,
      c__login_id: lockedPartyCols.includes("c__login_id")
        ? stepLoginValue
        : extra["c__login_id"]||(underStepEntity?stepLoginValue:""),
    };
  };

  // Moving a row onto another entity takes the step-1 credentials off it (they belong to
  // the step-1 entity); moving it back puts them back if the cell was left empty.
  const withEntityChange=(extra:Record<string,string>,next:string):Record<string,string>=>{
    const login=extra["c__login_id"]??"";
    if(!stepLoginValue||!stepEntity) return{...extra,c__entity:next};
    if(next!==stepEntity&&login===stepLoginValue) return{...extra,c__entity:next,c__login_id:""};
    if(next===stepEntity&&!login)                 return{...extra,c__entity:next,c__login_id:stepLoginValue};
    return{...extra,c__entity:next};
  };

  // Direction is fixed by the entry point (Incoming vs Outgoing repo) — read it from
  // the ?direction query param instead of asking. Outgoing deals are B2B only at the
  // contract level; who they reach is the scope above.
  useEffect(()=>{
    if(new URLSearchParams(window.location.search).get("direction")==="outbound"){
      setDirection("outbound");
      setDealType("b2b");
    }
  },[]);

  // ── Opened from an email (Email intake → Process) ─────────────────────────
  // ?from_mail=<message id>&item=<att:ID | table:N | text:deals>&agency=<Agency Master id>
  // &valid_from=YYYY-MM-DD. The deal sheet (an attachment, a table pasted in the body, or a
  // deal written as text and read into a sheet) is loaded as the upload file; the sender is the
  // B2B supplier; the circular's effective date is Valid From. Everything after that is this
  // page's normal flow — review, edit, save, approvals — and the email is marked as imported.
  const [fromMail,     setFromMail]     = useState<{mid:number;key:string}|null>(null);
  const [mailAgencyId, setMailAgencyId] = useState<number|null>(null);
  const [mailNote,     setMailNote]     = useState("");
  useEffect(()=>{
    const q=new URLSearchParams(window.location.search);
    const mid=Number(q.get("from_mail")); const key=q.get("item");
    if(!mid||!key) return;
    setFromMail({mid,key});
    const agency=Number(q.get("agency"))||null;
    if(agency){ setDealType("b2b"); setMailAgencyId(agency); }
    const vf=q.get("valid_from"); if(vf) setValidFromDate(vf);
    const url = key.startsWith("att:")   ? `/mail/attachments/${key.slice(4)}/download`
              : key.startsWith("table:") ? `/mail/messages/${mid}/tables/${key.slice(6)}/file`
              :                            `/mail/messages/${mid}/text-deals/file`;
    setMailNote(key==="text:deals"?"Reading the deal from the email text…":"Loading the deal sheet from the email…");
    (async()=>{
      try{
        const res=await api.get(url,{responseType:"blob"});
        const cd=String(res.headers["content-disposition"]??"");
        const m=/filename\*=UTF-8''([^;]+)/i.exec(cd);
        const name=m?decodeURIComponent(m[1]):"deal-from-email.xlsx";
        const blob=res.data as Blob;
        setFile(new globalThis.File([blob],name,{type:blob.type||"application/octet-stream"}));
        setAiMode(/\.pdf$/i.test(name));
        setMailNote(key==="text:deals"
          ?"The deal written in the email was read into a sheet — check every row in the review step."
          :"Deal sheet loaded from the email.");
      }catch(e){
        // Errors come back as a Blob because of responseType — read the server's sentence out.
        let msg="Could not load the deal from the email.";
        const data=(e as {response?:{data?:unknown}})?.response?.data;
        if(data instanceof Blob){ try{ const j=JSON.parse(await data.text()); if(typeof j.detail==="string") msg=j.detail; }catch{ /* keep default */ } }
        setMailNote("");
        setUploadError(msg);
      }
    })();
  },[]);
  // The sender is the supplier — set once Agency Master has loaded, exactly as a pick would.
  useEffect(()=>{
    if(mailAgencyId==null||!agencies.length) return;
    const a=agencies.find(x=>x.id===mailAgencyId);
    if(a){ setVendorAgencyId(a.id); setSupplierName(a.name); }
    setMailAgencyId(null);
  },[mailAgencyId,agencies]);

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
  // The extractor reports partial failures (skipped rows, failed sections, the
  // per-upload row cap) through `warning`. It used to be dropped on the floor
  // here while confidence WAS rendered — so a truncated extraction showed as
  // "312 rows · 78% confidence" with nothing saying why.
  const [aiWarning,    setAiWarning]    = useState("");
  const [airlineSummary, setAirlineSummary] = useState<Record<string,number>>({});
  // All suppliers: what each Source of the sheet resolved to, a filter showing one
  // Source's rows, and every agency's entities — a row's Entity cell offers its OWN
  // supplier's, since no step-1 entity exists to offer.
  const [sourceSummary, setSourceSummary] = useState<SupplierSource[]>([]);
  const [sourceFilter,  setSourceFilter]  = useState("");
  // Review: show only the rows the file could not be read for (isUnreadRow).
  const [unreadOnly,    setUnreadOnly]    = useState(false);
  const [refreshingAgencies, setRefreshingAgencies] = useState(false);
  const [entitiesByAgency, setEntitiesByAgency] = useState<Record<number,string[]>>({});
  const loadAgencyEntities=useCallback(()=>
    api.get<{agency_id:number;name:string;is_active:boolean}[]>("/agency-entities/",{params:{limit:1000}})
      .then(r=>{
        const m:Record<number,string[]>={};
        for(const e of r.data){
          if(e.is_active===false||!e.name) continue;
          const list=m[e.agency_id]??(m[e.agency_id]=[]);
          if(!list.includes(e.name)) list.push(e.name);
        }
        setEntitiesByAgency(m);
      })
      .catch(()=>setEntitiesByAgency({}))
  ,[]);
  useEffect(()=>{
    if(!multiVendor){ setEntitiesByAgency({}); return; }
    loadAgencyEntities();
  },[multiVendor,loadAgencyEntities]);
  const rowEntityOptions=useCallback((r:ReviewRow)=>entitiesByAgency[Number(r.extra["c__vendor_agency_id"])]??[],[entitiesByAgency]);
  // Reading a whole contract takes 30-60s. Without a ticker the button looks
  // hung, and people re-click or navigate away mid-extraction.
  const [uploadSecs,   setUploadSecs]   = useState(0);

  // ── Step 3 state ────────────────────────────────────────────────────────────
  const [rows,          setRows]          = useState<ReviewRow[]>([]);
  const [rowInclExcl,   setRowInclExcl]   = useState<Record<number,RowInclExcl>>({});
  const [inclExclPopup, setInclExclPopup] = useState<number|null>(null);
  const [inclExclModal, setInclExclModal] = useState<{rowIdx:number;type:string}|null>(null);
  const [incentiveDataModal, setIncentiveDataModal] = useState<number|null>(null);
  const [saving,        setSaving]        = useState(false);
  const [saveError,     setSaveError]     = useState("");
  const [selectedRows,  setSelectedRows]  = useState<Set<number>>(new Set());
  const [bulkColKey,    setBulkColKey]    = useState("");
  const [bulkColValue,  setBulkColValue]  = useState("");
  // Bulk edit can be narrowed to one airline among the selected rows ("" = all of them).
  const [bulkAirline,   setBulkAirline]   = useState("");
  // Bulk Incentive & Rules: a blank draft edited in the row modal, applied field by
  // field. Only keys present in the draft are written — never a whole-row copy,
  // because every row carries its own rate and a copy would flatten them.
  const [bulkIncOpen,   setBulkIncOpen]   = useState(false);
  const [bulkIncDraft,  setBulkIncDraft]  = useState<Record<string,Record<string,string>>>({});
  const [bulkIeDraft,   setBulkIeDraft]   = useState<Record<string,Record<string,Record<string,IEFieldValue>>>>({});
  const [bulkVvDraft,   setBulkVvDraft]   = useState<Record<string,Record<string,boolean>>>({});
  const [savedBatchId,  setSavedBatchId]  = useState<string|null>(null);
  // Saved: tell the email it was imported, so its Process panel says so.
  useEffect(()=>{
    if(!savedBatchId||!fromMail) return;
    api.post(`/mail/messages/${fromMail.mid}/processed`,{key:fromMail.key,destination:"deals",ref:savedBatchId}).catch(()=>{});
  },[savedBatchId,fromMail]);
  // Set when the deals saved but storing the source contract failed. Reported on
  // the success screen so "Saved Successfully" never overstates what happened.
  const [fileStoreError,setFileStoreError]= useState("");
  const [isMultiTab,    setIsMultiTab]    = useState(false);   // multi-tab workbook upload
  // parsed multi-tab rows held aside while the user reviews/adjusts column mapping
  const [mtParsed,      setMtParsed]      = useState<{rows:ReviewRow[];rowInclExcl:Record<number,RowInclExcl>}|null>(null);

  useEffect(()=>{
    if(!uploading){setUploadSecs(0);return;}
    const started=Date.now();
    const id=setInterval(()=>setUploadSecs(Math.round((Date.now()-started)/1000)),1000);
    return ()=>clearInterval(id);
  },[uploading]);

  useEffect(()=>{
    // User master → Agency Master: the Supplier Name options for an incoming B2B upload.
    loadVendorAgencies().then(setAgencies).catch(()=>{});
    // My Profile → Entities. Names only; the deal stores the name in deals.entity.
    api.get<{id:number;name:string;is_active:boolean}[]>("/user-entities/",{params:{limit:1000}})
      .then(r=>setEntityOptions(
        Array.from(new Set(r.data.filter(e=>e.is_active).map(e=>e.name).filter(Boolean)))))
      .catch(()=>{});
  },[]);

  const colGroups = buildColGroups(dealType,aiMode,multiVendor,selectedIncentives);

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

  // Live per-field update for the InclExclRuleModal (mirrors setInclExclField in the
  // manual create-deal form): ruleType -> incentiveType -> field -> value.
  const handleInclExclFieldChange=useCallback((rowIdx:number,type:string,incType:string,key:string,value:IEFieldValue)=>{
    setRowInclExcl(p=>{
      const state=p[rowIdx]??{types:[],data:{},viceVersa:{}};
      // Editing a rule type's field in the combined modal marks it active (so it's
      // sent on confirm) — there's no separate "add rule type" step anymore.
      const types=state.types.includes(type)?state.types:[...state.types,type];
      return{
        ...p,
        [rowIdx]:{
          ...state,
          types,
          data:{
            ...state.data,
            [type]:{ ...(state.data[type]??{}), [incType]:{ ...(state.data[type]?.[incType]??{}), [key]:value } },
          },
        },
      };
    });
  },[]);

  const handleInclExclViceVersaToggle=useCallback((rowIdx:number,type:string,incType:string)=>{
    setRowInclExcl(p=>{
      const state=p[rowIdx]??{types:[],data:{},viceVersa:{}};
      return{
        ...p,
        [rowIdx]:{
          ...state,
          viceVersa:{ ...state.viceVersa, [type]:{ ...(state.viceVersa[type]??{}), [incType]: !(state.viceVersa[type]?.[incType]) } },
        },
      };
    });
  },[]);

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

  const handleCopyInclExclToSelected=useCallback((sourceIdx:number)=>{
    setRowInclExcl(prev=>{
      const source=prev[sourceIdx];
      if(!source)return prev;
      const next={...prev};
      selectedRows.forEach(i=>{ if(i!==sourceIdx) next[i]=structuredClone(source); });
      return next;
    });
  },[selectedRows]);

  // ── Row incentive-data helpers ──────────────────────────────────────────────
  // Adapter over the row's existing flat "inc::{inc}::{field}" extra keys — the same
  // storage handleConfirm() already reads — so IncentiveTabContent (shared with the
  // manual form) gets a clean per-incentive-type Record<field,string> slice.
  const getRowIncentiveData=useCallback((idx:number,inc:string):Record<string,string>=>{
    const row=rows[idx]; if(!row)return{};
    const prefix=`inc::${inc}::`;
    const out:Record<string,string>={};
    for(const [k,v] of Object.entries(row.extra)) if(k.startsWith(prefix)) out[k.slice(prefix.length)]=v;
    return out;
  },[rows]);

  const handleIncentiveFieldChange=useCallback((idx:number,inc:string,field:string,value:string)=>{
    setRows(prev=>prev.map((r,i)=>i===idx?{...r,extra:{...r.extra,[`inc::${inc}::${field}`]:value}}:r));
  },[]);

  const handleCopyIncentiveDataToSelected=useCallback((sourceIdx:number)=>{
    setRows(prev=>{
      const sourceRow=prev[sourceIdx]; if(!sourceRow)return prev;
      const sourceIncExtra=Object.fromEntries(Object.entries(sourceRow.extra).filter(([k])=>k.startsWith("inc::")));
      return prev.map((r,i)=>{
        if(i===sourceIdx||!selectedRows.has(i))return r;
        const keptExtra=Object.fromEntries(Object.entries(r.extra).filter(([k])=>!k.startsWith("inc::")));
        return{...r,extra:{...keptExtra,...sourceIncExtra}};
      });
    });
  },[selectedRows]);

  // ── Table row helpers ──────────────────────────────────────────────────────
  // All suppliers: a row moved to another supplier drops the entity and credentials it
  // carried — they were the old supplier's, and would otherwise travel with its deal.
  const withVendorChange=(extra:Record<string,string>,id:string):Record<string,string>=>{
    if(id===(extra["c__vendor_agency_id"]??""))return extra;
    const entity=extra["c__entity"]??"";
    const keepEntity=!!entity&&(entitiesByAgency[Number(id)]??[]).includes(entity);
    return{...extra,c__vendor_agency_id:id,c__entity:keepEntity?entity:"",c__login_id:""};
  };
  // The row's Contract Valid From / To are its incentives' too: an edit carries into every
  // incentive the row has that still shows the old date (or none), and into Travel Date
  // Valid From wherever that was opening with the contract. Only incentives already on the
  // row — on a tabbed upload, writing a date into another would hand the row that incentive.
  const withContractDateChange=(extra:Record<string,string>,key:string,next:string):Record<string,string>=>{
    const prev=extra[key]??"";
    const field=key==="c__valid_from"?"validFrom":"validTo";
    const out={...extra,[key]:next};
    const incs=new Set(Object.keys(extra).filter(k=>k.startsWith("inc::")).map(k=>k.split("::")[1]));
    for(const inc of incs){
      const k=`inc::${inc}::${field}`;
      if(!out[k]||out[k]===prev) out[k]=next;
      const t=`inc::${inc}::travelValidFrom`;
      if(field==="validFrom"&&prev&&out[t]===prev) out[t]=next;
    }
    return out;
  };
  const handleRowChange=(idx:number,key:string,val:string)=>{
    setRows(prev=>prev.map((r,i)=>{
      if(i!==idx)return r;
      if(key==="c__valid_from"||key==="c__valid_to")return{...r,extra:withContractDateChange(r.extra,key,val)};
      if(key==="c__entity")return{...r,extra:withEntityChange(r.extra,val)};
      if(key==="c__vendor_agency_id")return{...r,extra:withVendorChange(r.extra,val)};
      if(key.startsWith("inc::"))return{...r,extra:withIncentiveCellChange(r.extra,key,val)};
      if(key.startsWith("ie::")||key.startsWith("c__"))
        return{...r,extra:{...r.extra,[key]:val}};
      return{...r,[key]:val};
    }));
  };
  // Removes rows and keeps everything keyed by row POSITION lined up with them — the
  // incl/excl rules and the selection. Filtering the rows alone handed every later row
  // the rules of the row in front of it.
  const removeRows=(drop:Set<number>)=>{
    if(!drop.size)return;
    const moved=new Map<number,number>();
    rows.forEach((_,i)=>{ if(!drop.has(i)) moved.set(i,moved.size); });
    setRows(prev=>prev.filter((_,i)=>!drop.has(i)).map((r,i)=>({...r,row_order:i})));
    setRowInclExcl(prev=>{
      const next:Record<number,RowInclExcl>={};
      for(const [k,v] of Object.entries(prev)){ const to=moved.get(Number(k)); if(to!==undefined) next[to]=v; }
      return next;
    });
    setSelectedRows(prev=>new Set([...prev].flatMap(i=>{ const to=moved.get(i); return to===undefined?[]:[to]; })));
    setIncentiveDataModal(null);setInclExclModal(null);setInclExclPopup(null);
  };
  const handleDeleteRow=(idx:number)=>removeRows(new Set([idx]));

  // All suppliers: every row of one Source at once.
  const assignSource=(group:string,id:string)=>{
    setRows(prev=>prev.map(r=>r.extra["__src_group"]===group?{...r,extra:withVendorChange(r.extra,id)}:r));
  };
  const removeSource=(group:string)=>{
    const drop=new Set<number>();
    rows.forEach((r,i)=>{ if(r.extra["__src_group"]===group) drop.add(i); });
    const src=sourceSummary.find(s=>s.group===group)?.source||"rows with no Source";
    if(!drop.size||!window.confirm(`Remove the ${drop.size} row${drop.size!==1?"s":""} from ${src}? They will not be saved — extract the file again to get them back.`))return;
    removeRows(drop);
    if(sourceFilter===group)setSourceFilter("");
  };
  // After onboarding an agency in another tab: offer it here without losing the review.
  const refreshAgencies=()=>{
    setRefreshingAgencies(true);
    Promise.all([loadVendorAgencies().then(setAgencies),loadAgencyEntities()])
      .catch(()=>{})
      .finally(()=>setRefreshingAgencies(false));
  };
  const handleAddRow=()=>{
    const newIdx=rows.length;
    setSourceFilter("");   // a new row belongs to no Source, so a Source filter would hide it
    setUnreadOnly(false);  // nor is it an unread row
    setRows(prev=>[...prev,{...EMPTY_ROW(),row_order:prev.length,extra:fillStepParty({c__deal_tag:dealTag==="adhoc"?"Adhoc":"Standard"})}]);
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
  const rowAirline=(r:ReviewRow)=>(r.extra["c__airline_name"]||r.airline_name||"").trim();
  // Rows the file could not be read for: how many, and how many are still blank. The
  // filter only bites while there are any — deleting the last one must not leave an
  // empty table behind a filter that is no longer offered.
  const inlineIncs=inlineIncentives(selectedIncentives);
  const unreadTotal=rows.filter(isUnreadRow).length;
  const unreadBlank=rows.filter(r=>unreadGaps(r,inlineIncs).length>0).length;
  const unreadActive=unreadOnly&&unreadTotal>0;
  // The toolbar filters narrow the table: Supplier (All suppliers — the sheet's Source,
  // the same filter as "Show rows"), Rows not read, then Airline. The airline picker
  // offers the airlines of the rows the other two leave, with their counts.
  const rowPassesFilters=(r:ReviewRow)=>
    (!sourceFilter||r.extra["__src_group"]===sourceFilter)&&(!unreadActive||isUnreadRow(r));
  const filterAirlines=useMemo(()=>{
    const counts=new Map<string,number>();
    rows.forEach(r=>{
      if(sourceFilter&&r.extra["__src_group"]!==sourceFilter) return;
      if(unreadActive&&!isUnreadRow(r)) return;
      const n=rowAirline(r); if(n) counts.set(n,(counts.get(n)??0)+1);
    });
    return [...counts.entries()].sort((a,b)=>a[0].localeCompare(b[0]));
  },[rows,sourceFilter,unreadActive]);
  // A picked airline the other filters no longer leave falls back to "all".
  const activeBulkAirline=filterAirlines.some(([a])=>a===bulkAirline)?bulkAirline:"";
  // Same test as ReviewTable's filteredIndices, so "visible" means the same thing here.
  const rowVisible=(r:ReviewRow)=>
    (!activeBulkAirline||rowAirline(r)===activeBulkAirline)&&rowPassesFilters(r);
  const visibleCount=rows.filter(rowVisible).length;
  // What a bulk edit touches: the ticked rows the filters still show — a ticked row
  // hidden by a filter is left alone, so what you see ticked is what gets edited.
  const bulkTargets=new Set<number>();
  selectedRows.forEach(i=>{ const r=rows[i]; if(r&&rowVisible(r)) bulkTargets.add(i); });
  const hiddenSelected=selectedRows.size-bulkTargets.size;

  const openBulkIncentive=()=>{
    setBulkIncDraft({});setBulkIeDraft({});setBulkVvDraft({});setBulkIncOpen(true);
  };
  const applyBulkIncentive=()=>{
    const targets=bulkTargets;
    if(!targets.size)return;
    setRows(prev=>prev.map((r,i)=>{
      if(!targets.has(i))return r;
      const extra={...r.extra};
      for(const [inc,fields] of Object.entries(bulkIncDraft))
        for(const [f,v] of Object.entries(fields)) extra[`inc::${inc}::${f}`]=v;
      return{...r,extra};
    }));
    const ruleTypes=new Set([...Object.keys(bulkIeDraft),...Object.keys(bulkVvDraft)]);
    if(ruleTypes.size){
      setRowInclExcl(prev=>{
        const next={...prev};
        targets.forEach(i=>{
          const state=prev[i]??{types:[],data:{},viceVersa:{}};
          const types=[...state.types];
          const data={...state.data};
          const viceVersa={...state.viceVersa};
          ruleTypes.forEach(rt=>{
            if(!types.includes(rt)) types.push(rt);
            const perInc={...(data[rt]??{})};
            for(const [inc,vals] of Object.entries(bulkIeDraft[rt]??{})) perInc[inc]={...(perInc[inc]??{}),...vals};
            data[rt]=perInc;
            if(bulkVvDraft[rt]) viceVersa[rt]={...(viceVersa[rt]??{}),...bulkVvDraft[rt]};
          });
          next[i]={types,data,viceVersa};
        });
        return next;
      });
    }
  };

  // The Entity a bulk edit may set. On All suppliers only a name EVERY target row's own
  // supplier has — one vendor's entity is not another's.
  const bulkEntityOptions=(()=>{
    if(!multiVendor)return stepEntityOptions;
    let common:string[]|null=null;
    for(const i of bulkTargets){
      const own=rows[i]?rowEntityOptions(rows[i]):[];
      common=common===null?[...own]:common.filter(e=>own.includes(e));
    }
    return common??[];
  })();

  const handleBulkApply=()=>{
    if(!bulkColKey||bulkColValue==="")return;
    // The supplier is picked by its label and stored by its id.
    const vendorId=bulkColKey==="c__vendor_agency_id"?String(vendorOptions.byLabel.get(bulkColValue)?.id??""):"";
    setRows(prev=>prev.map((r,i)=>{
      if(!bulkTargets.has(i))return r;
      if(bulkColKey==="c__valid_from"||bulkColKey==="c__valid_to")return{...r,extra:withContractDateChange(r.extra,bulkColKey,bulkColValue)};
      if(bulkColKey==="c__entity")return{...r,extra:withEntityChange(r.extra,bulkColValue)};
      if(bulkColKey==="c__vendor_agency_id")return vendorId?{...r,extra:withVendorChange(r.extra,vendorId)}:r;
      if(bulkColKey.startsWith("inc::"))return{...r,extra:withIncentiveCellChange(r.extra,bulkColKey,bulkColValue)};
      if(bulkColKey.startsWith("ie::")||bulkColKey.startsWith("c__"))
        return{...r,extra:{...r.extra,[bulkColKey]:bulkColValue}};
      return{...r,[bulkColKey]:bulkColValue};
    }));
    setBulkColValue("");
  };

  // A verdict is about ONE file against ONE supplier; changing either voids it.
  useEffect(()=>{ setSupplierCheck(null); setSupplierOverride(false); },
    [file,vendorAgencyId,allSuppliers,dealType,scopeKind,scopeSel.agencyId,scopeSel.corporateId]);
  // An "Upload anyway" re-runs the extract once the override is in state.
  const [extractAgain, setExtractAgain] = useState(false);

  // A PDF defaults to AI extraction and a spreadsheet to column mapping — except on All
  // suppliers, which only the AI reader can split by Source.
  const pickFile=(f:File)=>{
    if(!UPLOAD_FILE_RE.test(f.name)){ setUploadError(UPLOAD_FILE_ERROR); return; }
    setUploadError("");
    setFile(f);
    if(/\.pdf$/i.test(f.name)||multiVendor)setAiMode(true);
    else if(/\.xlsx?$/i.test(f.name))setAiMode(false);
  };

  // ── Step 1 → 2/3: Extract ───────────────────────────────────────────────────
  const handleExtract=async()=>{
    // Inline message AND a side notification: the inline one persists while the
    // user fixes it, the toast is what they actually notice on a long form.
    const missing=missingFields([
      {label:"Contract File",value:file},
      {label:"Deal Type",value:dealType},
      {label:"Supplier Name",value:multiVendor?ALL_SUPPLIERS_LABEL:supplierName,when:!outbound&&dealType==="b2b"},
      // Outgoing names its counterparty through the scope. A Common deal has none,
      // which is why this checks scopeComplete rather than a party id.
      {label:scopeType==="corporate"?"Corporate":"Agency",value:scopeComplete?"set":"",when:outbound},
    ]);
    if(outbound) setScopeTouched(true);
    if(missing.length||!file){
      const msg=missingMessage(missing.length?missing:["Contract File"]);
      setUploadError(msg);
      notifyRequired(msg);
      return;
    }
    // A file loaded from an email skips pickFile, so the type is checked here too.
    if(!UPLOAD_FILE_RE.test(file.name)){ setUploadError(UPLOAD_FILE_ERROR); return; }
    setUploading(true);setUploadError("");setIsMultiTab(false);setAiWarning("");setAirlineSummary({});
    setSourceSummary([]);setSourceFilter("");setUnreadOnly(false);
    try{
      // All suppliers splits a sheet by its Source column — which only the AI reader
      // finds. Column mapping and the tabbed template cannot say whose each row is.
      if(multiVendor&&!AI_READABLE_RE.test(file.name)){
        setUploadError("All suppliers reads an Excel or PDF deal sheet with a Source / Supplier column. Pick one supplier to upload this file.");
        return;
      }
      // Incoming B2B: is this file really the picked supplier's? Before extraction, so a
      // wrong sheet costs a second, not a minute of AI reading and a review of 300 rows.
      if(!outbound&&dealType==="b2b"&&vendorAgencyId!=null&&!supplierOverride){
        const cf=new FormData();cf.append("file",file);cf.append("agency_id",String(vendorAgencyId));
        try{
          const {data:chk}=await api.post<SupplierCheck>("/deals/upload/check-supplier",cf,{headers:{"Content-Type":"multipart/form-data"}});
          setSupplierCheck(chk);
          // Stop on a mismatch AND on a file that names nobody: an unconfirmed sheet
          // must be a deliberate choice ("upload anyway"), never a silent default.
          if(chk.status==="mismatch"||chk.status==="unknown") return;
        }catch{ setSupplierCheck(null); }   // a failed check must not block the upload
      }
      // Outgoing: the same check pointed at the deal's customer — its code when the sheet
      // carries one, otherwise names. Another party named, or this customer not named at
      // all, stops here exactly as an incoming upload does.
      if(outbound&&!supplierOverride&&(
        (scopeKind==="b2b"&&scopeSel.agencyId!=null)||(scopeKind==="corporate"&&scopeSel.corporateId!=null))){
        const cf=new FormData();cf.append("file",file);
        if(scopeKind==="b2b") cf.append("agency_id",String(scopeSel.agencyId));
        else cf.append("corporate_id",String(scopeSel.corporateId));
        try{
          const {data:chk}=await api.post<SupplierCheck>("/deals/upload/check-scope",cf,{headers:{"Content-Type":"multipart/form-data"}});
          setSupplierCheck(chk);
          if(chk.status==="mismatch"||chk.status==="unknown") return;
        }catch{ setSupplierCheck(null); }
      }
      const form=new FormData();form.append("file",file);
      if((aiMode||multiVendor)&&AI_READABLE_RE.test(file.name)){
        if(multiVendor) setAiMode(true);
        if(validFromDate) form.append("valid_from",validFromDate);
        // All suppliers: every row is kept and says whose it is. Otherwise the picked
        // supplier: a multi-supplier spreadsheet keeps only its rows.
        if(multiVendor) form.append("all_suppliers","true");
        else if(!outbound&&dealType==="b2b"&&vendorAgencyId!=null) form.append("agency_id",String(vendorAgencyId));
        // Per-call only — a global axios timeout would also apply to
        // /upload/confirm, which is slower still on a large sheet.
        const {data}=await api.post<AIExtractResponse>("/deals/upload/ai-extract",form,
          {headers:{"Content-Type":"multipart/form-data"},timeout:300_000});
        if(!data.deals.length&&data.warning){
          setUploadError(data.warning);
          return;
        }
        const converted=convertAIDealsToRows(data.deals);
        converted.forEach(r=>{
          // AI returns data for one incentive (PLB) — replicate it across every
          // incentive type the user selected (e.g. Super PLB), so all are pre-filled.
          const srcFields:Record<string,string>={}; let srcInc="";
          for(const [k,v] of Object.entries(r.extra)){
            if(!k.startsWith("inc::")) continue;
            const parts=k.split("::"); // ["inc", incType, field]
            if(!srcInc) srcInc=parts[1];
            if(parts[1]===srcInc) srcFields[parts[2]]=v;
          }
          if(Object.keys(srcFields).length){
            selectedIncentives.forEach(incType=>{
              for(const [field,v] of Object.entries(srcFields)){
                const key=`inc::${incType}::${field}`;
                if(!r.extra[key]) r.extra[key]=v;
              }
            });
          }
          if(!r.extra["c__valid_from"] && validFromDate) r.extra["c__valid_from"] = validFromDate;
          // Each incentive's contract window is the row's own, and its travel window
          // opens with the contract unless the sheet named a start ("01JAN'27 Onwards").
          selectedIncentives.forEach(incType=>{
            const k=(f:string)=>`inc::${incType}::${f}`;
            if(!r.extra[k("validFrom")] && r.extra["c__valid_from"]) r.extra[k("validFrom")] = r.extra["c__valid_from"];
            if(!r.extra[k("validTo")] && r.extra["c__valid_to"]) r.extra[k("validTo")] = r.extra["c__valid_to"];
            if(!r.extra[k("travelValidFrom")] && r.extra[k("travelValidTo")] && r.extra[k("validFrom")])
              r.extra[k("travelValidFrom")] = r.extra[k("validFrom")];
          });
          if(!r.extra["c__business_type"] && dealType==="b2b") r.extra["c__business_type"] = "B2B";
          r.extra["c__deal_tag"] = dealTag==="adhoc"?"Adhoc":"Standard";
          r.extra = fillStepParty(r.extra);
        });
        setRows(converted);
        if(selectedInclExcl.length>0){
          const initRIE:Record<number,RowInclExcl>={};
          converted.forEach((_,i)=>{initRIE[i]={types:selectedInclExcl,data:{},viceVersa:{}};});
          setRowInclExcl(initRIE);
        }
        setAiFileName(data.file_name);
        setAiConfidence(data.confidence);
        setAiWarning(data.warning??"");
        setAirlineSummary(data.airline_summary??{});
        setSourceSummary(multiVendor?(data.supplier_summary??[]):[]);
        setBulkAirline("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
        setStep(3);
      }else{
        // Multi-tab workbook? Parse all sheets in-browser (join by Deal No), then show
        // the column-mapping step for the contract sheet before Review — like flat XLS.
        if(/\.xlsx?$/i.test(file.name)){
          const wb=XLSX.read(new Uint8Array(await file.arrayBuffer()),{type:"array"});
          if(wb.SheetNames.includes(MT_CONTRACT_SHEET)){
            const parsed=parseMultiTabWorkbook(wb, dealType);
            if(parsed.rows.length===0){
              setUploadError(`No deals found — fill the "Deal No" column on the "${MT_CONTRACT_SHEET}" sheet.`);
              return;
            }
            // Pre-fill Contract Valid From from the Step-1 date when a row left it blank
            if(validFromDate){
              parsed.rows.forEach(r=>{ if(!r.extra["c__valid_from"]) r.extra["c__valid_from"]=validFromDate; });
            }
            // Build a contract-sheet preview for the mapping UI: one raw row per Deal No,
            // in the same order as parsed.rows so they merge back by index.
            const sheet=wb.Sheets[MT_CONTRACT_SHEET];
            const headerRow=(XLSX.utils.sheet_to_json<string[]>(sheet,{header:1})[0]??[]).map(h=>String(h)).filter(Boolean);
            const seenDeal=new Set<string>();
            const contractRawRows=XLSX.utils.sheet_to_json<Record<string,string>>(sheet,{defval:"",raw:false}).filter(rw=>{
              const dn=String(rw["Deal No"]??"").trim();
              if(!dn||seenDeal.has(dn))return false; seenDeal.add(dn); return true;
            });
            const mtPreview:ExtractionPreview={
              source_type:"excel", file_name:file.name, confidence:0.95,
              rows:parsed.rows.map(r=>({row_order:r.row_order,airline_name:r.airline_name,iata_code:r.iata_code,eco_commission:r.eco_commission,peco_commission:r.peco_commission,bus_commission:r.bus_commission,valid_on:r.valid_on,validity_raw:r.validity_raw,remarks:r.remarks})),
              doc_columns:headerRow, raw_rows:contractRawRows,
            };
            setIsMultiTab(true);
            setMtParsed({rows:parsed.rows,rowInclExcl:parsed.rowInclExcl});
            // Keep the Step-1 selection visible in review, plus anything found in the file.
            setSelectedIncentives(prev=>[...new Set([...prev, ...parsed.incentiveUnion])]);
            setSelectedInclExcl(prev=>[...new Set([...prev, ...parsed.inclExclUnion])]);
            initColumnMap(mtPreview);
            setBulkAirline("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
            setStep(2);
            return;
          }
        }
        const {data}=await api.post<ExtractionPreview>("/deals/upload/extract",form,{headers:{"Content-Type":"multipart/form-data"}});
        initColumnMap(data);
        setStep(2);
      }
    }catch(err:unknown){
      const msg=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
      setUploadError(msg??"Extraction failed. Please check the file and try again.");
    }finally{setUploading(false);}
  };

  // "Upload anyway": run the extract again now that the override is in state.
  useEffect(()=>{
    if(!extractAgain) return;
    setExtractAgain(false);
    handleExtract();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[extractAgain]);

  // ── Step 2 → 3: Apply mapping ────────────────────────────────────────────────
  const handleMappingConfirm=(contract:Record<string,string>,mappedRows:ReviewRow[],prePopulatedInclExcl:Record<number,RowInclExcl>)=>{
    // Multi-tab: keep the in-browser-parsed incentive / incl-excl data; only the
    // contract columns come from the (possibly adjusted) mapping. Merge by row index.
    if(isMultiTab && mtParsed){
      const merged=mtParsed.rows.map((pr,i)=>({
        ...pr,
        row_order:i,
        extra:fillStepParty({...pr.extra, ...(mappedRows[i]?.extra??{}), c__deal_tag:dealTag==="adhoc"?"Adhoc":"Standard"}),
      }));
      setRows(merged);
      setRowInclExcl(mtParsed.rowInclExcl);
      setMtParsed(null);
      setBulkAirline("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
      setStep(3);
      return;
    }
    const fallbackContract: Record<string, string> = {
      c__airline_type:  contract.c__airline_type  || "GDS",
      c__trigger_type:  contract.c__trigger_type  || "Sales",
      c__payout_type:   contract.c__payout_type   || "Sales",
      // Like the AI and tabbed paths: a B2B sheet with no Business Type column is B2B.
      ...(dealType==="b2b" && !contract.c__business_type ? { c__business_type: "B2B" } : {}),
    };
    // IATA Commission is per row: a row whose own cell is blank has none. Spread with the
    // other sheet-wide values it handed the first row's % to every such row.
    const sheetWide={...contract};
    delete sheetWide.c__iata_commission;
    const rowsWithContract=mappedRows.map(r=>({
      ...r,
      extra:{
        ...fallbackContract,
        ...sheetWide,
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
    setRows(rowsWithContract.map(r=>({...r,extra:fillStepParty({...r.extra,c__deal_tag:dealTag==="adhoc"?"Adhoc":"Standard"})})));
    setRowInclExcl(finalRowInclExcl);
    setBulkAirline("");setSelectedRows(new Set());setBulkColKey("");setBulkColValue("");
    setStep(3);
  };

  // ── Step 3 → 4: Save ────────────────────────────────────────────────────────
  const handleConfirm=async()=>{
    if(rows.length===0){
      const msg="Add at least one commission row before saving.";
      setSaveError(msg);notifyRequired(msg);return;
    }

    // All suppliers: a B2B deal naming no supplier would match EVERY vendor's statements,
    // so a row without one is not saved (the server refuses it too). Name the Sources
    // still open — that is where they are fixed — not just a count.
    if(multiVendor){
      const open=rows.filter(r=>!r.extra["c__vendor_agency_id"]);
      if(open.length){
        const srcs=[...new Set(open.map(r=>r.extra["c__supplier_cell"]||"(no Source)"))];
        const msg=`${open.length} row${open.length!==1?"s have":" has"} no supplier — ${srcs.slice(0,4).join(", ")}${srcs.length>4?` and ${srcs.length-4} more`:""}. `
          +`Pick the agency for ${srcs.length>1?"each":"it"} under "Suppliers in this sheet", or remove those rows.`;
        setSaveError(msg);notifyRequired(msg);setSourceFilter("");setBulkAirline("");setUnreadOnly(false);return;
      }
    }

    // Rows the file could not be read for are NOT a reason to refuse the save (the user's
    // call): they stay marked red and filterable under "Rows not read", and save as they
    // stand — the deal is kept, to be completed from the repository later.

    // Every review row becomes its own deal, so the header fields the deal API
    // needs have to be present on each one. Nothing checked this before: the
    // confirm payload declares all of them Optional, so a row with no airline or
    // no contract dates saved as NULL and still reported "Deal Saved
    // Successfully". Validate here, name the row, and refuse.
    const rowValue=(r:ReviewRow,key:string)=>
      key==="c__airline_name" ? (r.extra[key]||r.airline_name||"") : (r.extra[key]||"");
    const badRows:{row:number;missing:string[]}[]=[];
    rows.forEach((r,i)=>{
      const missing=missingFields(
        REQUIRED_ROW_COLUMNS
          .filter(c=>c.dealTypes.includes(dealType||"airline"))
          .map(c=>({label:c.label,value:rowValue(r,c.key)}))
      );
      if(missing.length) badRows.push({row:i+1,missing});
    });
    if(badRows.length){
      const cols=[...new Set(badRows.flatMap(b=>b.missing))];
      const msg=badRows.length===1
        ? `Row ${badRows[0].row}: ${missingMessage(badRows[0].missing)}`
        : `${badRows.length} rows are missing required fields (${cols.join(", ")}). First problem is row ${badRows[0].row}.`;
      setSaveError(msg);notifyRequired(msg);
      setSourceFilter("");setBulkAirline("");setUnreadOnly(false);   // clear any filter hiding the bad row
      return;
    }

    // An inverted contract range produces incentives that can never trigger.
    const badRange=rows.findIndex(r=>{
      const f=rowValue(r,"c__valid_from"),t=rowValue(r,"c__valid_to");
      return f&&t&&t<f;
    });
    if(badRange>=0){
      const msg=`Row ${badRange+1}: Contract Valid To must be on or after Contract Valid From.`;
      setSaveError(msg);notifyRequired(msg);return;
    }

    setSaving(true);setSaveError("");
    const ext=file?.name.split(".").pop()?.toLowerCase()??"unknown";
    const fileType=ext==="pdf"?"pdf":["xls","xlsx"].includes(ext)?"excel":["doc","docx"].includes(ext)?"word":["png","jpg","jpeg"].includes(ext)?"image":"unknown";
    // An outgoing deal's counterparty comes from the scope, not from a typed
    // supplier name. The server re-derives the authoritative label from the
    // resolved party (the agency's own name, or "All Agencies" for a common
    // deal); this is only the fallback it starts from.
    const sourceAgent=outbound
      ?scopeLabel(scopeType)
      :dealType==="b2b"?(multiVendor?"Multiple suppliers":supplierName):(file?.name.replace(/\.[^/.]+$/,"")??"upload");

    const getContractVal=(key:string)=>{for(const r of rows){if(r.extra[key])return r.extra[key];}return "";};

    try{
      const {data:confirmData}=await api.post<{created_count:number;created_ids:number[];batch_id?:string}>(
        `/deals/upload/confirm?file_name=${encodeURIComponent(file?.name??"")}&file_type=${fileType}&supplier_name=${encodeURIComponent(supplierName||sourceAgent)}`,
        {
          source_agent:    sourceAgent,
          source_type:     "upload",
          // Incoming B2B only. The server resolves it (ownership-checked) and derives the
          // supplier name and supplier-master id from it; null everywhere else, where
          // ck_deals_vendor_agency would refuse it anyway.
          vendor_agency_id: !outbound&&dealType==="b2b"&&!multiVendor?vendorAgencyId:null,
          // All suppliers: each row carries its own agency instead (rows[].vendor_agency_id).
          multi_vendor:    multiVendor,
          deal_tag:        dealTag,
          direction:       direction,
          airline_type:    getContractVal("c__airline_type")||null,
          airline_name:    getContractVal("c__airline_name")||null,
          contract_year:   dealType==="airline"?(getContractVal("c__contract_year")||null):null,
          valid_from:      getContractVal("c__valid_from")||null,
          valid_to:        getContractVal("c__valid_to")||null,
          trigger_type:    dealType==="airline"?(getContractVal("c__trigger_type")||null):null,
          payout_type:     dealType==="airline"?(getContractVal("c__payout_type")||null):null,
          // Outgoing takes the entity and credentials from the scoped AGENCY;
          // incoming keeps `entity` meaning your own filing entity from My Profile.
          // All suppliers has no upload-wide entity or credentials: they are per row,
          // and a deal-level value would be some other row's — another vendor's.
          entity:          multiVendor?null:((outbound?scopeSel.entity:entity)||null),
          // Retired, as on Create Deal — the Entity column is a per-row `entity` now.
          entity_lcc:      null,
          business_type:   (outbound?(getContractVal("c__business_type")||KIND_BUSINESS_TYPE[scopeKind]):(getContractVal("c__business_type")||(dealType==="b2b"?"B2B":"")))||null,
          deal_type:       dealType||null,
          // Outgoing: the scoped agency's credentials. Incoming B2B: the picked
          // supplier's credentials from Agency Master — the server puts them only on rows
          // attributed to that supplier. Otherwise: the sheet's own Login ID, as before.
          login_id:        multiVendor?null
                            :(outbound?scopeSel.loginIds.join(", ")
                            :agencyParty&&loginIds.length?loginIds.join(", ")
                            :getContractVal("c__login_id"))||null,
          login_ids:       multiVendor?null
                            :outbound&&scopeSel.loginIds.length?scopeSel.loginIds
                            :agencyParty&&loginIds.length?loginIds
                            :null,
          // Never upload-wide: each row sends its own (rows[].iata_commission). The first
          // row's value sent here was saved on every row that had none.
          iata_commission: null,
          // Mirrors the server's own re-derivation, so a stale id left by a scope
          // change can never travel attached to the wrong scope.
          ...(outbound?buildScopePayload(scopeType,scopeSel.agencyId,scopeSel.corporateId,scopeSel.agencyEntityId):{}),
          incentive_types: selectedIncentives,
          incentive_data:  {},
          incl_excl_types: selectedInclExcl,
          incl_excl_data:  {},
          vice_versa:      {},
          copy_prev_incl_excl: copyPrevInclExcl,
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
              // Carrier designator — resolves the airline master and, when the
              // airline is missing, creates it. Distinct from `iata_code` below,
              // which the backend maps onto the deal's AGENCY IATA number.
              airline_code:r.extra["c__airline_code"]||null,
              // Per-deal header fields — used by multi-tab uploads; for the single-sheet
              // path these equal the deal-level values (the backend falls back on null).
              airline_type:   r.extra["c__airline_type"]||null,
              business_type:  r.extra["c__business_type"]||null,
              entity:         r.extra["c__entity"]||null,
              // The step-1 credentials left as filled are sent as no row value, so the
              // server applies the picked `login_ids` list rather than a joined string.
              login_id:       (stepLoginValue&&r.extra["c__login_id"]===stepLoginValue?null:r.extra["c__login_id"])||null,
              iata_commission:r.extra["c__iata_commission"]||null,
              deal_maker_name:r.extra["c__deal_maker_name"]||null,
              supplier_name:  r.extra["c__supplier_name"]||null,
              // All suppliers: this row's agency, and the Source it was read from —
              // remembered against that agency for the next upload of the sheet.
              vendor_agency_id: multiVendor?(Number(r.extra["c__vendor_agency_id"])||null):null,
              supplier_cell:    multiVendor?(r.extra["c__supplier_cell"]??null):null,
              contract_year:  r.extra["c__contract_year"]||null,
              trigger_type:   r.extra["c__trigger_type"]||null,
              payout_type:    r.extra["c__payout_type"]||null,
              valid_from:  r.extra["c__valid_from"]||null,
              valid_to:    r.extra["c__valid_to"]||null,
              iata_code:r.iata_code,
              eco_commission:r.eco_commission,
              peco_commission:r.peco_commission,
              bus_commission:r.bus_commission,
              valid_on:r.valid_on,
              validity_raw:r.validity_raw,
              remarks:r.remarks,
              // Multi-tab: each deal keeps only the incentives it actually filled.
              incentive_types: isMultiTab ? Object.keys(rowIncData) : [],
              incentive_data:  rowIncData,
              incl_excl_types: ie.types,
              incl_excl_data:  ie.data,
              vice_versa:      ie.viceVersa,
            };
          }),
        }
      );
      setSavedBatchId(confirmData.batch_id ?? null);
      setFileStoreError("");
      if (file && confirmData.batch_id) {
        console.log("[GCS] Uploading deal file to bucket | batch_id=", confirmData.batch_id, "| file=", file.name, "| size=", file.size);
        try {
          const fd = new FormData();
          fd.append("file", file);
          const res = await api.post(`/deals/batches/${confirmData.batch_id}/file`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          console.log("[GCS] Deal file upload SUCCESS | response=", res.data);
        } catch (uploadErr) {
          // The deals themselves are saved — only the source contract failed to
          // store. Previously this went to the console alone, so the user got an
          // unqualified "Deal Saved Successfully" for a batch with no attachment
          // and no way to know it had to be re-attached.
          console.error("[GCS] Deal file upload FAILED:", uploadErr);
          const detail = (uploadErr as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
          setFileStoreError(detail ?? "The contract file could not be stored.");
          notifyRequired(`Deals saved, but the contract file "${file.name}" was not attached. Re-upload it from the batch page.`);
        }
      } else {
        console.warn("[GCS] Skipping file upload | file=", file, "| batch_id=", confirmData.batch_id);
      }
      setStep(4);
    }catch(err:unknown){
      const msg=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
      setSaveError(msg??"Failed to save. Please try again.");
    }finally{setSaving(false);}
  };

  // ── Step 4: Success ──────────────────────────────────────────────────────────
  if(step===4)return(
    <div className="max-w-lg mx-auto mt-16 text-center space-y-4">
      <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto"><Check className="w-8 h-8 text-green-500"/></div>
      <h2 className="text-xl font-bold text-gray-900">Deal Saved Successfully</h2>
      <p className="text-sm text-gray-500">
        <span className="font-medium">{rows.length} row{rows.length!==1?"s":""}</span> saved
        {multiVendor&&(()=>{const n=new Set(rows.map(r=>r.extra["c__vendor_agency_id"])).size;return <> across <span className="font-medium">{n} supplier{n!==1?"s":""}</span></>;})()}
        {" "}and submitted for approval.
        {selectedIncentives.length>0&&<> Incentives: <span className="font-medium">{selectedIncentives.join(", ")}</span>.</>}
      </p>
      {fileStoreError&&(
        <div className="flex items-start gap-2 text-left bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5"/>
          <p className="text-xs text-amber-700">
            <span className="font-semibold">The contract file was not attached.</span>{" "}
            {fileStoreError} The deals above are saved — re-upload the file from the batch page.
          </p>
        </div>
      )}
      <div className="flex gap-3 justify-center pt-2 flex-wrap">
        {savedBatchId&&(
          <button onClick={()=>router.push(`/deals/${savedBatchId}`)} className="bg-[#1e3a5f] text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-[#16304f]">View Batch</button>
        )}
        <button onClick={()=>router.push(dealsHref(direction))} className="border border-[#1e3a5f] text-[#1e3a5f] px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-50">View All Deals</button>
        <button onClick={()=>{setStep(1);setFile(null);setPreview(null);setRows([]);setDealType(outbound?"b2b":"");setSupplierName("");setVendorAgencyId(null);setAllSuppliers(false);setSourceSummary([]);setSourceFilter("");setUnreadOnly(false);setEntity("");setLoginIds([]);setValidFromDate("");setColumnMap({});setSelectedIncentives([]);setSelectedInclExcl([]);setRowInclExcl({});setAiMode(false);setAiFileName("");setAiConfidence(0);setSavedBatchId(null);setFileStoreError("");setCopyPrevInclExcl(true);setIsMultiTab(false);
          // The scope is Step-1 state too — leaving it set would silently float the
          // next upload to the previous upload's agency. dealType stays "b2b" on an
          // outgoing upload, since the query param effect only runs on mount.
          setScopeKind("b2b");setScopeTouched(false);setScopeSel({agencyId:null,corporateId:null,agencyEntityId:null,entity:"",loginIds:[]});
          // The email this page was opened from is done; the next upload is not from it,
          // and must not re-tag that email with its own batch id.
          setFromMail(null);setMailNote("");}}
          className="border border-gray-200 text-gray-700 px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-50">Upload Another</button>
      </div>
    </div>
  );

  return(
    <div className="space-y-4">
      {/* Incentive & Rules Modal — incentive fields + incl/excl rules per incentive type */}
      {incentiveDataModal!==null&&(
        <IncentiveDataRowModal
          rowIdx={incentiveDataModal}
          incentiveTypes={selectedIncentives}
          selectedRows={selectedRows}
          getData={(inc)=>getRowIncentiveData(incentiveDataModal,inc)}
          onFieldChange={(inc,field,value)=>handleIncentiveFieldChange(incentiveDataModal,inc,field,value)}
          getInclExclData={(inc,rt)=>(rowInclExcl[incentiveDataModal]?.data?.[rt]?.[inc]??{})}
          onInclExclChange={(inc,rt,k,v)=>handleInclExclFieldChange(incentiveDataModal,rt,inc,k,v)}
          getInclExclViceVersa={(inc,rt)=>!!rowInclExcl[incentiveDataModal]?.viceVersa?.[rt]?.[inc]}
          onInclExclViceVersa={(inc,rt)=>handleInclExclViceVersaToggle(incentiveDataModal,rt,inc)}
          onCopyToSelected={()=>{handleCopyIncentiveDataToSelected(incentiveDataModal);handleCopyInclExclToSelected(incentiveDataModal);}}
          onClose={()=>setIncentiveDataModal(null)}
        />
      )}

      {/* Bulk Incentive & Rules — the same modal over a blank draft (see applyBulkIncentive) */}
      {bulkIncOpen&&(
        <IncentiveDataRowModal
          rowIdx={-1}
          incentiveTypes={selectedIncentives}
          selectedRows={new Set()}
          bulk={{count:bulkTargets.size,airline:activeBulkAirline,onApply:applyBulkIncentive}}
          getData={(inc)=>bulkIncDraft[inc]??{}}
          onFieldChange={(inc,field,value)=>setBulkIncDraft(p=>({...p,[inc]:{...(p[inc]??{}),[field]:value}}))}
          getInclExclData={(inc,rt)=>bulkIeDraft[rt]?.[inc]??{}}
          onInclExclChange={(inc,rt,k,v)=>setBulkIeDraft(p=>({...p,[rt]:{...(p[rt]??{}),[inc]:{...(p[rt]?.[inc]??{}),[k]:v}}}))}
          getInclExclViceVersa={(inc,rt)=>!!bulkVvDraft[rt]?.[inc]}
          onInclExclViceVersa={(inc,rt)=>setBulkVvDraft(p=>({...p,[rt]:{...(p[rt]??{}),[inc]:!p[rt]?.[inc]}}))}
          onCopyToSelected={()=>{}}
          onClose={()=>setBulkIncOpen(false)}
        />
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          {/* Back to the repository this upload belongs to — the outgoing repo is
              the same page behind ?direction=outbound, so the link has to carry
              the direction or an Outgoing upload would land in Incoming. */}
          <Link
            href={outbound?"/deals?direction=outbound":"/deals"}
            title={outbound?"Back to Outgoing deals":"Back to Incoming deals"}
            className="mt-1 p-1.5 rounded-lg border border-gray-200 bg-white text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition-colors shrink-0"
          >
            <ArrowLeft className="w-4 h-4"/>
            <span className="sr-only">{outbound?"Back to Outgoing deals":"Back to Incoming deals"}</span>
          </Link>
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">
              Deals · {outbound?"Outgoing":"Incoming"}
            </p>
            <h1 className="text-xl font-bold text-gray-900">Upload Deal File</h1>
          </div>
        </div>
        <StepBar step={step}/>
      </div>

      {/* A file that names no supplier at all was let through — say so where the rows are reviewed. */}
      {step>1&&step<4&&supplierCheck?.status==="unknown"&&(
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0"/>
          <p className="text-xs text-amber-700">{supplierCheck.message}</p>
        </div>
      )}

      {/* ══ STEP 1 ══ */}
      {step===1&&(
        <div className="grid grid-cols-5 gap-4">
          {/* LEFT: deal info */}
          <div className="col-span-2 space-y-3">
            <SectionCard title="Deal Details">
              <div className="px-4 py-3 space-y-3">
                {/* Direction is fixed by the entry point (Incoming vs Outgoing repo) — read-only */}
                <div>
                  <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Deal Direction</label>
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium border ${
                    direction==="outbound"
                      ? "border-amber-200 bg-amber-50 text-amber-700"
                      : "border-emerald-200 bg-emerald-50 text-emerald-700"
                  }`}>
                    {direction==="outbound"?"Outgoing":"Incoming"}
                  </span>
                </div>

                {outbound ? (
                  <>
                    {/* Deal Type here is the SCOPE — who the deal is floated to.
                        `dealType` stays pinned "b2b" behind it, because that value
                        drives the required-row-column set, the contract columns and
                        the XLS template; writing a scope into it would disable all
                        three and let blank airline names save silently. */}
                    <SelectField
                      label="Deal Type"
                      required
                      placeholder="Select deal type…"
                      options={OUTGOING_DEAL_KINDS.map(k=>k.label)}
                      value={OUTGOING_DEAL_KINDS.find(k=>k.key===scopeKind)?.label ?? ""}
                      onChange={v=>{
                        const k=OUTGOING_DEAL_KINDS.find(x=>x.label===v)?.key ?? "b2b";
                        setScopeKind(k);
                        setScopeSel({agencyId:null,corporateId:null,agencyEntityId:null,entity:"",loginIds:[]});
                      }}
                    />
                    <OutgoingScopeFields
                      scope={scopeType}
                      value={scopeSel}
                      onChange={setScopeSel}
                      touched={scopeTouched}
                    />
                  </>
                ) : (
                  <>
                    <SelectField
                      label="Deal Type"
                      required
                      placeholder="Select deal type…"
                      options={["Airline","B2B"]}
                      value={dealType==="airline"?"Airline":dealType==="b2b"?"B2B":""}
                      onChange={v=>{ setDealType(v==="Airline"?"airline":v==="B2B"?"b2b":""); setSupplierName(""); setVendorAgencyId(null); setAllSuppliers(false); }}
                    />
                    {dealType==="b2b"&&(
                      <div>
                        {/* From the user's own Agency Master, labelled by branch AND channel
                            — one vendor is onboarded once per each, and the pick has to say
                            which. Still MATCHED on the supplier-master row the agency was
                            copied from; see lib/vendorAgency.ts. */}
                        {/* "All suppliers" heads the list: a vendor-comparison sheet carries
                            every supplier's deals at once, each row naming its own. */}
                        <SearchSelectField
                          label="Supplier Name *"
                          placeholder={agencies.length?"Search agency…":"No agencies in your Agency Master yet"}
                          options={vendorOptions.labels.length?[ALL_SUPPLIERS_LABEL,...vendorOptions.labels]:[]}
                          value={allSuppliers?ALL_SUPPLIERS_LABEL:vendorOptions.labelOf(vendorAgencyId)}
                          onChange={v=>{
                            if(v===ALL_SUPPLIERS_LABEL){
                              setAllSuppliers(true);setVendorAgencyId(null);setSupplierName("");setAiMode(true);
                              return;
                            }
                            setAllSuppliers(false);
                            const picked=vendorOptions.byLabel.get(v)??null;
                            setVendorAgencyId(picked?.id??null);
                            setSupplierName(picked?.name??"");
                          }}
                        />
                        {allSuppliers&&(
                          <p className="text-[10px] text-[#9a3412] bg-orange-50 border border-orange-200 rounded-md px-2 py-1.5 mt-1.5 leading-relaxed">
                            Each row&apos;s supplier is read from the sheet&apos;s <span className="font-semibold">Source</span> column
                            and matched to your Agency Master. Sources you haven&apos;t onboarded, or that fit more than one
                            branch, are flagged in Review &amp; Edit — map each once for all its rows, or remove them.
                            Entity and Login ID are set per row there.
                          </p>
                        )}
                        {agencies.length===0&&(
                          <p className="text-[10px] text-gray-400 mt-1">
                            Onboard the agencies you buy from in{" "}
                            <Link href="/user-master/agency-master" className="font-semibold text-sky-600 hover:underline">User master → Agency Master</Link>
                            {" "}and they appear here.
                          </p>
                        )}
                        {vendorAgency&&vendorAgency.supplier_id==null&&(
                          <p className="text-[10px] text-amber-600 mt-1">
                            Not in the supplier master yet — statements will match these deals by name until
                            the platform admin approves it, then by its supplier record automatically.
                          </p>
                        )}
                      </div>
                    )}
                  </>
                )}
                <MultiSelectDropdown
                  label="Incentive Types"
                  options={INCENTIVE_TYPES}
                  selected={selectedIncentives}
                  onChange={setSelectedIncentives}
                />
                {selectedIncentives.length>0&&(
                  <p className="text-[10px] text-blue-600">
                    {selectedIncentives.join(", ")} — one sheet each in the tabbed template, editable in Review.
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
                    {selectedInclExcl.join(", ")} — columns inside every incentive sheet, editable in Review.
                  </p>
                )}
                {/* Incoming field order: Deal Type, Supplier, Incentive Types, Inclusions &
                    Exclusions, Entity, Login ID, Deal Tag, Valid From. */}
                {/* The picked supplier's own Entity and Login ID / IATA Number, from
                    User master → Agency Master — the same two fields and source as
                    Create Deal for an incoming B2B deal. Only what that agency actually
                    has is offered; login IDs follow the entity, because a credential
                    belongs to one. */}
                {/* One supplier's entity and credentials — none to pick for all suppliers. */}
                {agencyParty&&!multiVendor&&(
                  <>
                    <SearchSelectField
                      label="Entity"
                      placeholder={agencyEntityPlaceholder}
                      options={agencyEntityNames}
                      value={entity}
                      onChange={setEntity}
                    />
                    <MultiSelectDropdown
                      label="Login ID / IATA Number"
                      options={agencyLoginIdOptions}
                      selected={loginIds}
                      onChange={setLoginIds}
                    />
                    {/* MultiSelectDropdown has no placeholder of its own, so the
                        reason the list is empty is said underneath instead. */}
                    {agencyLoginIdOptions.length===0&&(
                      <p className="text-[10px] text-gray-400 -mt-2">{agencyLoginPlaceholder}</p>
                    )}
                    {loginIds.length>0&&(
                      <p className="text-[10px] text-blue-600 -mt-2">
                        Applied to every row of this supplier; a Login ID in the sheet still wins on its own row.
                      </p>
                    )}
                  </>
                )}
                {/* Incoming deals only. On an outgoing deal OutgoingScopeFields
                    already asked for Agency Entity above, and that is what fills
                    Deal.entity (see the payload: outbound reads scopeSel.entity).
                    Showing this too offers a second control over the same column
                    that the save silently ignores. Mirrors /deals/new, which
                    hides it on `outboundScoped` for the same reason. */}
                {/* Also hidden on an incoming B2B deal, whose Entity is the supplier
                    agency's (the block above). */}
                {!outbound&&!agencyParty&&(
                  <>
                    <SearchSelectField
                      label="Entity"
                      placeholder={entityOptions.length?"Search entity…":"No entities in your profile"}
                      options={entityOptions}
                      value={entity}
                      onChange={setEntity}
                    />
                    {entityOptions.length===0&&(
                      <p className="text-[10px] text-gray-400">
                        Add entities under{" "}
                        <Link href="/profile" className="text-blue-600 hover:underline">My Profile → Entities</Link>
                        {" "}to file deals against one.
                      </p>
                    )}
                  </>
                )}
                <SelectField
                  label="Deal Tag"
                  options={DEAL_TAG_OPTIONS}
                  value={dealTag==="adhoc"?"Adhoc":"Standard"}
                  onChange={v=>setDealTag(v.toLowerCase())}
                />
                <div>
                  <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Valid From Date</label>
                  <input
                    type="date"
                    value={validFromDate}
                    onClick={e=>{ try{ e.currentTarget.showPicker?.(); }catch{ /* unsupported — ignore */ } }}
                    onChange={e=>setValidFromDate(e.target.value)}
                    className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-800 cursor-pointer"
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
                  <span className="text-[11px] text-gray-400">{multiVendor?"Excel · PDF — with a Source column":"PDF · Excel"}</span>
                  {/* The tabbed template is one supplier's (its code is pre-filled), and
                      All suppliers reads only sheets the AI can split by Source. */}
                  {!multiVendor&&<button
                    type="button"
                    onClick={async()=>{
                      // The filled sheet says whose it is: the supplier's code on an incoming B2B
                      // deal, the customer's on an outgoing one (fetched — the scope picker
                      // holds only ids).
                      if(!outbound){
                        downloadMultiTabTemplate(dealType,selectedIncentives,selectedInclExcl,
                          dealType==="b2b"?{key:"__supplier_code",value:vendorAgency?.agency_code??""}:null);
                        return;
                      }
                      let code:{key:MtCodeKey;value:string}|null=null;
                      try{
                        if(scopeKind==="b2b"&&scopeSel.agencyId!=null){
                          const {data}=await api.get<{agency_code:string|null}>(`/agencies/${scopeSel.agencyId}`);
                          code={key:"__agency_code",value:data.agency_code??""};
                        }else if(scopeKind==="corporate"&&scopeSel.corporateId!=null){
                          const {data}=await api.get<{corporate_code?:string|null}>(`/corporates/${scopeSel.corporateId}`);
                          code={key:"__corporate_code",value:data.corporate_code??""};
                        }
                      }catch{ /* the column still goes in, just blank */ }
                      downloadMultiTabTemplate(dealType,selectedIncentives,selectedInclExcl,code);
                    }}
                    className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 hover:underline font-medium"
                  >
                    <FileSpreadsheet className="w-3 h-3"/>Download Tabbed Template
                  </button>}
                </div>
              </div>
              <div
                onDragOver={e=>{e.preventDefault();setDragging(true);}}
                onDragLeave={()=>setDragging(false)}
                onDrop={e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)pickFile(f);}}
                onClick={()=>fileRef.current?.click()}
                className={`border-2 border-dashed rounded-xl flex flex-col items-center justify-center py-16 gap-3 cursor-pointer transition-all ${dragging?"border-[#1e3a5f] bg-blue-50/40":file?"border-green-400 bg-green-50/30":"border-gray-200 hover:border-blue-300 hover:bg-blue-50/20"}`}
              >
                <input ref={fileRef} type="file" accept=".pdf,.xls,.xlsx" className="hidden"
                  onChange={e=>{const f=e.target.files?.[0];if(f)pickFile(f);}}/>
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
                      {[["PDF","text-red-500 bg-red-50"],["Excel","text-green-600 bg-green-50"]].map(([l,c])=>(
                        <span key={l} className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${c}`}>{l}</span>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {mailNote&&!uploadError&&(
                <p className="text-xs text-sky-700 bg-sky-50 border border-sky-100 rounded-lg px-3 py-2">{mailNote}</p>
              )}
              {uploadError&&(
                <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0"/>
                  <p className="text-xs text-red-600">{uploadError}</p>
                </div>
              )}
              {(supplierCheck?.status==="mismatch"||supplierCheck?.status==="unknown")&&!supplierOverride&&(()=>{
                const unknown=supplierCheck.status==="unknown";
                // Offer a one-click switch only when the file names exactly one active
                // row of the user's own Agency Master — otherwise they pick it themselves.
                const switchTo=outbound?[]:supplierCheck.found_agency_ids
                  .map(id=>agencies.find(a=>a.id===id&&a.is_active))
                  .filter((a):a is VendorAgency=>!!a);
                return(
                <div className={`rounded-lg border px-3 py-2.5 space-y-2 ${unknown?"border-amber-200 bg-amber-50":"border-red-200 bg-red-50"}`}>
                  <div className="flex items-start gap-2">
                    <AlertTriangle className={`w-4 h-4 mt-0.5 flex-shrink-0 ${unknown?"text-amber-500":"text-red-500"}`}/>
                    <div>
                      <p className={`text-xs font-semibold ${unknown?"text-amber-800":"text-red-700"}`}>
                        {unknown
                          ?(outbound?"The selected customer is not named in this file":`${supplierName||"The selected supplier"} is not named in this file`)
                          :outbound?"This file is for a different customer":"This file is not from the selected supplier"}
                      </p>
                      <p className={`text-xs mt-0.5 ${unknown?"text-amber-700":"text-red-600"}`}>
                        {unknown
                          ?(outbound?supplierCheck.message:`Nothing in the file name, title or text says it is ${supplierName||"theirs"}'s deal sheet. Check you attached the right file before extracting.`)
                          :supplierCheck.message}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 pl-6">
                    {switchTo.length===1&&(
                      <button type="button"
                        onClick={()=>{setVendorAgencyId(switchTo[0].id);setSupplierName(switchTo[0].name);}}
                        className="text-[11px] font-semibold px-2.5 py-1 rounded-md bg-white border border-red-200 text-red-700 hover:bg-red-100">
                        Switch supplier to {vendorOptions.labelOf(switchTo[0].id)||switchTo[0].name}
                      </button>
                    )}
                    {switchTo.length>1&&(
                      <span className="text-[11px] text-red-600">Pick the right {supplierCheck.found} branch / channel in Supplier Name.</span>
                    )}
                    <button type="button" onClick={()=>{setFile(null);setSupplierCheck(null);}}
                      className="text-[11px] font-semibold px-2.5 py-1 rounded-md bg-white border border-red-200 text-red-700 hover:bg-red-100">
                      Choose another file
                    </button>
                    <button type="button" onClick={()=>{setSupplierOverride(true);setExtractAgain(true);}}
                      className="text-[11px] font-semibold px-2.5 py-1 rounded-md text-red-500 hover:underline">
                      It&apos;s correct — upload anyway
                    </button>
                  </div>
                </div>);
              })()}

              {/* AI Mode toggle — turned on by itself for a PDF (pickFile), optional for
                  Excel, where leaving it off goes to column mapping. A PDF can still be
                  switched off: column mapping is the fallback when its table can't be read. */}
              {(()=>{const aiBlocked=!AI_READABLE_RE.test(file?.name??"");const isSheet=/\.(xlsx|xlsm|xls|csv)$/i.test(file?.name??"");return(
              <label className={`flex items-center gap-2.5 select-none py-1 ${aiBlocked?"opacity-40 cursor-not-allowed":multiVendor?"cursor-default":"cursor-pointer"}`}>
                <div
                  onClick={()=>{if(!aiBlocked&&!multiVendor)setAiMode(m=>!m);}}
                  className={`relative w-10 h-5 rounded-full transition-colors duration-200 flex-shrink-0 ${aiMode&&!aiBlocked?"bg-[#1e3a5f]":"bg-gray-200"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${aiMode&&!aiBlocked?"translate-x-5":"translate-x-0"}`}/>
                </div>
                <span className="text-xs font-medium text-gray-700">
                  Use AI Extraction
                  <span className="ml-1.5 text-[11px] text-gray-400 font-normal">
                    {multiVendor
                      ?(aiBlocked?"All suppliers reads a PDF or Excel deal sheet":"Always on for All suppliers — it reads each row's Source")
                      :aiBlocked
                      ?"On automatically for a PDF · optional for Excel"
                      :aiMode
                        ?(isSheet?"Reads the sheet as a table — no column mapping":"Reads the PDF's table — no column mapping")
                        :(isSheet?"Off — column mapping. Turn on for sheets too free-form to map":"Standard extraction with column mapping")}
                  </span>
                </span>
              </label>
              );})()}

              {/* Copy Incl/Excl from Previous Deal toggle */}
              <label className="flex items-center gap-2.5 select-none py-1 cursor-pointer">
                <div
                  onClick={()=>setCopyPrevInclExcl(v=>!v)}
                  className={`relative w-10 h-5 rounded-full transition-colors duration-200 flex-shrink-0 ${copyPrevInclExcl?"bg-[#1e3a5f]":"bg-gray-200"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${copyPrevInclExcl?"translate-x-5":"translate-x-0"}`}/>
                </div>
                <span className="text-xs font-medium text-gray-700">
                  Copy Incl/Excl from Previous Deal
                  <span className="ml-1.5 text-[11px] text-gray-400 font-normal">
                    {copyPrevInclExcl?"Auto-copies from matching deal if incl/excl not set":"Will not auto-copy — set incl/excl manually"}
                  </span>
                </span>
              </label>

              <button onClick={handleExtract} disabled={!file||!dealType||(outbound?!scopeComplete:(dealType==="b2b"&&!supplierName&&!multiVendor))||uploading}
                className="w-full bg-[#1e3a5f] text-white rounded-xl py-3 text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                {uploading
                  ?<><RefreshCw className="w-4 h-4 animate-spin"/>{aiMode
                      ?`Reading every row… ${uploadSecs}s`
                      :"Extracting columns…"}</>
                  :aiMode
                    ?<><Settings2 className="w-4 h-4"/>Extract &amp; Structure with AI</>
                    :<><Upload className="w-4 h-4"/>Extract &amp; Map Columns</>
                }
              </button>

              <div className={`rounded-lg px-3 py-2.5 text-[11px] ${aiMode?"bg-purple-50 border border-purple-200 text-purple-700":"bg-blue-50 border border-blue-200 text-blue-700"}`}>
                {aiMode
                  ?(uploading&&uploadSecs>=20
                    ?"Reading the whole sheet — a 4-page contract takes about a minute and produces 300+ rows. Please keep this tab open."
                    :multiVendor
                      ?"AI will read every supplier's rows — each airline split into Economy / Premium / Business — and match each row's Source to your Agency Master. You review the suppliers before anything is saved."
                    :/\.(xlsx|xlsm|xls|csv)$/i.test(file?.name??"")
                      ?"AI will read the sheet as a table — every row, split into Economy / Premium / Business — and skip column mapping. A sheet listing several suppliers keeps only the selected supplier's rows."
                      :"AI will read every row of the PDF, split each airline's deal into Economy / Premium / Business rows, and skip column mapping.")
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
          contractOnly={isMultiTab}
        />
      )}

      {/* ══ STEP 3 ══ */}
      {step===3&&(preview||aiMode||isMultiTab)&&(
        <div className="space-y-3">
          {/* Summary — what was read (file, how, for whom), the key numbers, and one
              list of everything that still needs a look before saving. */}
          {(()=>{
            const fileName=aiMode?(aiFileName||file?.name||""):(preview?.file_name??file?.name??"");
            const conf=aiMode?aiConfidence:(preview?.confidence??0);
            const party=outbound?"Outgoing"
              :dealType==="b2b"?(multiVendor?"All suppliers":(supplierName||"B2B"))
              :"Airline deal";
            const meta=[aiMode?"AI extraction":isMultiTab?"Tabbed template":"Column mapping",party,
              dealTag==="adhoc"?"Adhoc":"Standard",selectedIncentives.join(", ")].filter(Boolean);
            // Airline-master counts are DISTINCT airlines, not rows — one airline
            // routinely occupies 3 rows (Economy / Premium / Business).
            const n=(k:string)=>airlineSummary[k]??0;
            const airlinesTotal=Object.values(airlineSummary).reduce((a,b)=>a+b,0);
            const needLook=n("conflict")+n("ambiguous")+n("multi_carrier");
            const unassigned=multiVendor?rows.filter(r=>!r.extra["c__vendor_agency_id"]).length:0;
            const warning=aiMode?aiWarning:preview?.warning;
            const pl=(c:number,one:string,many:string)=>`${c} ${c===1?one:many}`;
            // Rows the file could not be read for are not listed here — the toolbar's
            // "Rows not read" filter and the red rows say it where they are fixed.
            const notes:{tone:"red"|"amber"|"sky";text:string}[]=[];
            if(unassigned) notes.push({tone:"red",text:`${pl(unassigned,"row still needs","rows still need")} a supplier — pick it under Suppliers in this sheet.`});
            if(needLook)   notes.push({tone:"red",text:`${pl(needLook,"airline needs","airlines need")} a look — check the Master column.`});
            if(warning)    notes.push({tone:"amber",text:warning});
            if(n("unresolved")) notes.push({tone:"amber",text:n("unresolved")===1
              ?"1 airline is not in the airline master and has no code — fill in its Code to add it."
              :`${n("unresolved")} airlines are not in the airline master and have no code — fill in their Code to add them.`});
            if(n("new"))   notes.push({tone:"sky",text:`${pl(n("new"),"airline","airlines")} will be added to the airline master when you save.`});
            const TONE={red:"text-red-700",amber:"text-amber-700",sky:"text-sky-700"};
            const stat=(label:string,value:React.ReactNode,cls="text-gray-800")=>(
              <div key={label} className="px-4 text-right">
                <p className="text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
                <p className={`text-sm font-semibold tabular-nums ${cls}`}>{value}</p>
              </div>
            );
            return(
              <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
                  <FileIcon name={fileName}/>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-800 truncate">{fileName}</p>
                    <p className="text-[11px] text-gray-500">{meta.join(" · ")}</p>
                  </div>
                  <div className="ml-auto flex items-center divide-x divide-gray-100">
                    {stat("Rows",rows.length)}
                    {!isMultiTab&&stat("Confidence",`${Math.round(conf*100)}%`,
                      conf>=0.8?"text-emerald-600":conf>=0.5?"text-amber-600":"text-red-600")}
                    {aiMode&&airlinesTotal>0&&stat("Airlines matched",`${n("resolved")} / ${airlinesTotal}`)}
                    {multiVendor&&stat("Suppliers",sourceSummary.length)}
                  </div>
                </div>
                {notes.length>0&&(
                  <ul className="border-t border-gray-100 bg-gray-50/60 px-4 py-2 space-y-1">
                    {notes.map(nt=>(
                      <li key={nt.text} className={`flex items-start gap-1.5 text-[11px] ${TONE[nt.tone]}`}>
                        {nt.tone==="sky"
                          ?<Info className="w-3.5 h-3.5 mt-px flex-shrink-0"/>
                          :<AlertTriangle className="w-3.5 h-3.5 mt-px flex-shrink-0"/>}
                        {nt.text}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })()}

          {/* All suppliers: whose deal every row is — settled here before anything saves. */}
          {multiVendor&&sourceSummary.length>0&&(
            <SupplierSourcesPanel
              summary={sourceSummary}
              rows={rows}
              vendorChoices={vendorChoices}
              filter={sourceFilter}
              onFilter={setSourceFilter}
              onAssign={assignSource}
              onRemove={removeSource}
              onRefresh={refreshAgencies}
              refreshing={refreshingAgencies}
            />
          )}

          {/* Review & Edit — one card: the filter + bulk-edit line, then the table. */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {/* Filter + Bulk Edit Toolbar — always shown, on ONE line (the user's ask): pick
                Supplier / Airline, tick rows in the table, then edit them here. Labels are kept
                short so it fits; a narrow window scrolls it sideways rather than wrapping. */}
            <div className="px-4 py-2">
              <div className="flex items-center gap-1.5 flex-nowrap overflow-x-auto py-0.5 *:shrink-0">
                {/* All suppliers: one Source's rows — the same filter as the panel's "Show rows". */}
                {multiVendor&&sourceSummary.length>0&&(
                  <select
                    value={sourceFilter}
                    onChange={e=>setSourceFilter(e.target.value)}
                    title="Show one supplier's rows"
                    className={`border rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 max-w-40 ${
                      sourceFilter?"border-orange-300 bg-orange-50 text-[#9a3412] font-semibold":"border-gray-200 text-gray-700"}`}
                  >
                    <option value="">All suppliers ({rows.length})</option>
                    {sourceSummary.map(s=>{
                      const n=rows.filter(r=>r.extra["__src_group"]===s.group).length;
                      if(!n)return null;
                      return <option key={s.group} value={s.group}>{s.source||"No Source"}{s.channel?` · ${s.channel}`:""} ({n})</option>;
                    })}
                  </select>
                )}
                {/* Only the rows the file could not be read for — red while any is still blank. */}
                {unreadTotal>0&&(
                  <button
                    type="button"
                    onClick={()=>setUnreadOnly(v=>!v)}
                    aria-pressed={unreadActive}
                    title={unreadActive?"Show every row again"
                      :"Show only the rows the file could not be read for — they need filling in by hand"}
                    className={`inline-flex items-center gap-1.5 border rounded-lg px-2 py-1.5 text-xs font-semibold whitespace-nowrap transition-colors ${
                      unreadBlank
                        ?(unreadActive?"bg-red-600 border-red-600 text-white hover:bg-red-700":"border-red-300 bg-red-50 text-red-700 hover:bg-red-100")
                        :(unreadActive?"bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700":"border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100")}`}
                  >
                    {unreadBlank?<AlertTriangle className="w-3.5 h-3.5"/>:<Check className="w-3.5 h-3.5"/>}
                    Rows not read ({unreadTotal})
                    {unreadBlank>0&&unreadBlank<unreadTotal&&<span className="font-normal">· {unreadBlank} left</span>}
                  </button>
                )}
                <select
                  value={activeBulkAirline}
                  onChange={e=>setBulkAirline(e.target.value)}
                  title="Show one airline's rows"
                  className={`border rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 max-w-40 ${
                    activeBulkAirline?"border-blue-300 bg-blue-50 text-blue-800 font-semibold":"border-gray-200 text-gray-700"}`}
                >
                  <option value="">All airlines ({filterAirlines.length})</option>
                  {filterAirlines.map(([a,n])=><option key={a} value={a}>{a} ({n})</option>)}
                </select>
                {(activeBulkAirline||sourceFilter||unreadActive)&&(
                  <button onClick={()=>{setBulkAirline("");setSourceFilter("");setUnreadOnly(false);}} title="Clear filters"
                    className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg px-1.5 py-1 whitespace-nowrap">
                    {visibleCount} of {rows.length} <X className="w-3.5 h-3.5"/>
                  </button>
                )}
                <span className="w-px h-5 bg-gray-200 mx-0.5" aria-hidden/>
                {/* Bulk edit — on the ticked rows the filters show */}
                {bulkTargets.size>0?(
                  <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-[11px] font-semibold px-2 py-1 rounded-full whitespace-nowrap">
                    ● {bulkTargets.size} selected
                  </span>
                ):(
                  <span className="text-[11px] text-gray-400 whitespace-nowrap">No rows ticked</span>
                )}
                {hiddenSelected>0&&(
                  <span className="text-[10px] text-gray-400 whitespace-nowrap"
                    title={`${hiddenSelected} more ticked row${hiddenSelected!==1?"s are":" is"} hidden by the filters — not edited`}>
                    +{hiddenSelected} hidden
                  </span>
                )}
                <select
                  value={bulkColKey}
                  onChange={e=>{setBulkColKey(e.target.value);setBulkColValue("");}}
                  className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-700 max-w-36"
                >
                  <option value="">Column to edit…</option>
                  {/* Editable columns only — read-only and popup columns are left out, and
                      so is any group left with nothing (Incentive & Rules has its own button). */}
                  {colGroups
                    .map(g=>({label:g.label,cols:g.cols.filter(c=>!BULK_SKIP_COLS.has(c.key)&&!lockedPartyCols.includes(c.key))}))
                    .filter(g=>g.cols.length>0)
                    .map(g=>(
                      <optgroup key={g.label} label={g.label}>
                        {g.cols.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}
                      </optgroup>
                    ))}
                </select>
                {bulkColKey&&(()=>{
                  const meta=getColMeta(bulkColKey,bulkEntityOptions,vendorOptions.labels);
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
                  disabled={bulkTargets.size===0||!bulkColKey||bulkColValue===""}
                  title={`Apply to the ${bulkTargets.size} ticked row${bulkTargets.size!==1?"s":""}`}
                  className="px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  Apply
                </button>
                <button
                  onClick={openBulkIncentive}
                  disabled={bulkTargets.size===0||selectedIncentives.length===0}
                  title={selectedIncentives.length===0?"Pick an incentive type in step 1 first":"Edit incentive fields and rules on the ticked rows"}
                  className="px-2.5 py-1.5 border border-blue-200 text-blue-700 bg-white text-xs font-semibold rounded-lg hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  Incentive &amp; Rules
                </button>
                {/* Clears the ticks only — the Supplier / Airline filters stay as picked. */}
                <button
                  onClick={()=>setSelectedRows(new Set())}
                  disabled={selectedRows.size===0}
                  className="px-2.5 py-1.5 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  Deselect All
                </button>
              </div>
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
              selectedIncentives={selectedIncentives}
              onOpenIncentiveData={setIncentiveDataModal}
              airlineFilter={activeBulkAirline}
              selectedRows={selectedRows}
              onToggleRow={handleToggleRow}
              onToggleAllFiltered={handleToggleAllFiltered}
              entityOptions={stepEntityOptions}
              lockedCols={lockedPartyCols}
              vendorChoices={multiVendor?vendorChoices:undefined}
              entityOptionsFor={multiVendor?rowEntityOptions:undefined}
              rowFilter={sourceFilter||unreadActive?rowPassesFilters:undefined}
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
