"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, CheckCircle, AlertCircle, RefreshCw, ChevronLeft,
  FileSpreadsheet, X, Download, ArrowRight, ChevronDown, Trash2, Plus, Search,
  Building2, Calendar, FileText,
} from "lucide-react";
import api from "@/lib/api";
import { useRouter } from "next/navigation";
import Link from "next/link";

// ── types ──────────────────────────────────────────────────────────────────
type TicketRow = {
  row_order:            number;
  booking_ref?:         string | null;
  segment_type?:        string | null;
  invoice_type?:        string | null;
  invoice_no?:          string | null;
  ticket_date?:         string | null;
  last_name?:           string | null;
  first_name?:          string | null;
  sector?:              string | null;
  booking_class?:       string | null;
  departure_datetime?:  string | null;
  gds_pnr?:             string | null;
  airlines_code?:       string | null;
  ticket_number?:       string | null;
  sell_fare?:           number | null;
  sell_tax?:            number | null;
  sell_tax_yq?:         number | null;
  sale_yr?:             number | null;
  sale_k3?:             number | null;
  rei_sell?:            number | null;
  seat_selection?:      number | null;
  excess_baggage?:      number | null;
  meals?:               number | null;
  rfd_sell?:            number | null;
  can_charge?:          number | null;
  booking_fee_sell?:    number | null;
  cgst_sell?:           number | null;
  sgst_sell?:           number | null;
  igst_sell?:           number | null;
  comm_sell?:           number | null;
  adm?:                 number | null;
  incentive_sell?:      number | null;
  dis_sell?:            number | null;
  tds_sell?:            number | null;
  total_amt?:           number | null;
  paid_by_credit_card?: number | null;
  net_amt?:             number | null;
  cc?:                  string | null;
  acc_code?:            string | null;
  sold_to?:             string | null;
  customer_name?:       string | null;
  airline_name?:        string | null;
  split_type?:          string | null;
};

type ExtractionPreview = {
  file_name:         string;
  total_rows:        number;
  rows:              TicketRow[];
  warnings:          string[];
  xls_columns:       string[];
  suggested_mapping: Record<string, string>;
  is_template_match: boolean;
  sample_row:        Record<string, string>;
};

type FieldDef = { key: string; label: string; required: boolean };

const OUR_FIELDS: FieldDef[] = [
  { key: "booking_ref",        label: "Booking Ref",         required: true  },
  { key: "ticket_number",      label: "Ticket Number",       required: true  },
  { key: "airlines_code",      label: "Airline Code",        required: true  },
  { key: "sector",             label: "Sector",              required: true  },
  { key: "ticket_date",        label: "Ticket Date",         required: false },
  { key: "departure_datetime", label: "Departure Date/Time", required: false },
  { key: "last_name",          label: "Last Name",           required: false },
  { key: "first_name",         label: "First Name",          required: false },
  { key: "segment_type",       label: "Segment Type",        required: false },
  { key: "invoice_type",       label: "Invoice Type",        required: false },
  { key: "invoice_no",         label: "Invoice No",          required: false },
  { key: "booking_class",      label: "Booking Class",       required: false },
  { key: "gds_pnr",            label: "GDS PNR",             required: false },
  { key: "airline_name",       label: "Airline Name",        required: false },
  { key: "sold_to",            label: "Sold To",             required: false },
  { key: "customer_name",      label: "Customer Name",       required: false },
  { key: "cc",                 label: "CC",                  required: false },
  { key: "acc_code",           label: "Acc Code",            required: false },
  { key: "sell_fare",          label: "Sell Fare",           required: false },
  { key: "sell_tax",           label: "Sell Tax",            required: false },
  { key: "sell_tax_yq",        label: "Sell Tax YQ",         required: false },
  { key: "sale_yr",            label: "Sale YR",             required: false },
  { key: "sale_k3",            label: "Sale K3",             required: false },
  { key: "rei_sell",           label: "REI Sell",            required: false },
  { key: "seat_selection",     label: "Seat Selection",      required: false },
  { key: "excess_baggage",     label: "Excess Baggage",      required: false },
  { key: "meals",              label: "Meals",               required: false },
  { key: "rfd_sell",           label: "RFD Sell",            required: false },
  { key: "can_charge",         label: "CAN Charge",          required: false },
  { key: "booking_fee_sell",   label: "Booking Fee Sell",    required: false },
  { key: "cgst_sell",          label: "CGST Sell",           required: false },
  { key: "sgst_sell",          label: "SGST Sell",           required: false },
  { key: "igst_sell",          label: "IGST Sell",           required: false },
  { key: "comm_sell",          label: "Comm Sell",           required: false },
  { key: "adm",                label: "ADM",                 required: false },
  { key: "incentive_sell",     label: "Incentive Sell",      required: false },
  { key: "dis_sell",           label: "Dis Sell",            required: false },
  { key: "tds_sell",           label: "TDS Sell",            required: false },
  { key: "total_amt",          label: "Total Amt",           required: false },
  { key: "paid_by_credit_card",label: "Paid By Credit Card", required: false },
  { key: "net_amt",            label: "Net AMT",             required: false },
];

type TColDef   = { key: keyof TicketRow; label: string; type: "text"|"date"|"number" };
type TColGroup = { label: string; color: string; cols: TColDef[] };

const TICKET_COL_GROUPS: TColGroup[] = [
  { label:"Passenger & Booking", color:"#1e3a5f", cols:[
    { key:"booking_ref",         label:"Booking Ref",   type:"text"   },
    { key:"segment_type",        label:"Segment Type",  type:"text"   },
    { key:"invoice_type",        label:"Invoice Type",  type:"text"   },
    { key:"invoice_no",          label:"Invoice No",    type:"text"   },
    { key:"ticket_date",         label:"Ticket Date",   type:"date"   },
    { key:"last_name",           label:"Last Name",     type:"text"   },
    { key:"first_name",          label:"First Name",    type:"text"   },
  ]},
  { label:"Flight Info", color:"#4f46e5", cols:[
    { key:"sector",              label:"Sector",        type:"text"   },
    { key:"booking_class",       label:"Class",         type:"text"   },
    { key:"departure_datetime",  label:"Departure",     type:"text"   },
    { key:"gds_pnr",             label:"GDS PNR",       type:"text"   },
    { key:"airlines_code",       label:"Airline Code",  type:"text"   },
    { key:"airline_name",        label:"Airline Name",  type:"text"   },
    { key:"ticket_number",       label:"Ticket #",      type:"text"   },
  ]},
  { label:"Financial", color:"#059669", cols:[
    { key:"sell_fare",           label:"Sell Fare",     type:"number" },
    { key:"sell_tax",            label:"Sell Tax",      type:"number" },
    { key:"sell_tax_yq",         label:"Tax YQ",        type:"number" },
    { key:"sale_yr",             label:"Sale YR",       type:"number" },
    { key:"sale_k3",             label:"Sale K3",       type:"number" },
    { key:"rei_sell",            label:"REI Sell",      type:"number" },
    { key:"seat_selection",      label:"Seat Sel.",     type:"number" },
    { key:"excess_baggage",      label:"Excess Bag.",   type:"number" },
    { key:"meals",               label:"Meals",         type:"number" },
    { key:"rfd_sell",            label:"RFD Sell",      type:"number" },
    { key:"can_charge",          label:"CAN Charge",    type:"number" },
    { key:"booking_fee_sell",    label:"Booking Fee",   type:"number" },
    { key:"cgst_sell",           label:"CGST",          type:"number" },
    { key:"sgst_sell",           label:"SGST",          type:"number" },
    { key:"igst_sell",           label:"IGST",          type:"number" },
    { key:"comm_sell",           label:"Comm Sell",     type:"number" },
    { key:"adm",                 label:"ADM",           type:"number" },
    { key:"incentive_sell",      label:"Incentive",     type:"number" },
    { key:"dis_sell",            label:"Dis Sell",      type:"number" },
    { key:"tds_sell",            label:"TDS Sell",      type:"number" },
    { key:"total_amt",           label:"Total Amt",     type:"number" },
    { key:"paid_by_credit_card", label:"Paid CC",       type:"number" },
    { key:"net_amt",             label:"Net AMT",       type:"number" },
  ]},
  { label:"Account", color:"#9333ea", cols:[
    { key:"cc",                  label:"CC",            type:"text"   },
    { key:"acc_code",            label:"Acc Code",      type:"text"   },
    { key:"sold_to",             label:"Sold To",       type:"text"   },
    { key:"customer_name",       label:"Customer Name", type:"text"   },
  ]},
];

// Agency options are fetched live from the supplier master API

const SKIP = "__skip__";

// ── Editable review table ──────────────────────────────────────────────────
function TicketReviewTable({
  rows, colGroups, onChange, onDelete, onAdd,
  filterText, selectedRows, onToggleRow, onToggleAllFiltered,
}:{
  rows: TicketRow[];
  colGroups: TColGroup[];
  onChange: (idx: number, key: keyof TicketRow, val: string) => void;
  onDelete: (idx: number) => void;
  onAdd: () => void;
  filterText: string;
  selectedRows: Set<number>;
  onToggleRow: (idx: number) => void;
  onToggleAllFiltered: (filteredIndices: number[], allSelected: boolean) => void;
}) {
  const allCols = colGroups.flatMap(g => g.cols);
  const inp = "w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[72px]";

  const filteredIndices: number[] = rows.reduce<number[]>((acc, row, i) => {
    if (!filterText) { acc.push(i); return acc; }
    const haystack = Object.values(row).filter(v => v != null).join(" ").toLowerCase();
    if (haystack.includes(filterText.toLowerCase())) acc.push(i);
    return acc;
  }, []);
  const allFilteredSelected = filteredIndices.length > 0 && filteredIndices.every(i => selectedRows.has(i));
  const someFilteredSelected = filteredIndices.some(i => selectedRows.has(i));

  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="w-full min-w-max border-collapse">
        <thead>
          <tr>
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
            <th className="px-2 py-2 text-[10px] text-white font-bold sticky left-9 z-10 whitespace-nowrap" style={{background:"#1e3a5f"}}>#</th>
            <th rowSpan={2} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{background:"#1e3a5f"}}>Type</th>
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
            <tr><td colSpan={allCols.length+4} className="px-4 py-10 text-center text-xs text-gray-400">
              {rows.length===0?"No rows. Add a row manually.":"No rows match the filter."}
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
                <td className="px-2 py-1.5 border-l border-gray-100 whitespace-nowrap">
                  {row.split_type === "split"
                    ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-600 border border-amber-200">Split</span>
                    : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-500">Normal</span>}
                </td>
                {allCols.map(col=>{
                  const raw=row[col.key];
                  const val=raw==null?"":String(raw);
                  return(
                    <td key={col.key} className="px-1 py-1 border-l border-gray-100">
                      {col.type==="date"?(
                        <input type="date" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)}/>
                      ):col.type==="number"?(
                        <input type="number" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)} placeholder="—"/>
                      ):(
                        <input type="text" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)} placeholder="—"/>
                      )}
                    </td>
                  );
                })}
                <td className="px-2 py-1.5">
                  <button onClick={()=>onDelete(idx)} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded text-red-400">
                    <Trash2 className="w-3.5 h-3.5"/>
                  </button>
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

// ── Agency custom dropdown (always opens downward) ─────────────────────────
function AgencyDropdown({ agency, setAgency, agencyOptions, touched, fieldCls }: {
  agency: string; setAgency: (v: string) => void;
  agencyOptions: string[]; touched: boolean;
  fieldCls: (v: string) => string;
}) {
  const [open, setOpen]     = useState(false);
  const [query, setQuery]   = useState("");
  const ref                 = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = agencyOptions.filter(a => a.toLowerCase().includes(query.toLowerCase()));

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
          onClick={() => setOpen(o => !o)}
          className={`${fieldCls(agency)} w-full text-left flex items-center justify-between pr-8`}
        >
          <span className={agency ? "text-gray-800" : "text-gray-400"}>
            {agency || "— Select agency —"}
          </span>
          <ChevronDown className="w-4 h-4 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </button>

        {open && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
            <div className="p-2 border-b border-gray-100">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  autoFocus
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search Agency..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
                />
              </div>
            </div>
            <ul className="max-h-48 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-2 text-xs text-gray-400 italic">No agencies found</li>
              ) : filtered.map(a => (
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

// ── Statement form panel ───────────────────────────────────────────────────
function StatementFormPanel({
  statementName, setStatementName,
  agency, setAgency,
  agencyOptions,
  validFrom, setValidFrom,
  validTo, setValidTo,
  touched, isComplete,
}: {
  statementName: string; setStatementName: (v: string) => void;
  agency: string; setAgency: (v: string) => void;
  agencyOptions: string[];
  validFrom: string; setValidFrom: (v: string) => void;
  validTo: string; setValidTo: (v: string) => void;
  touched: boolean;
  isComplete: boolean;
}) {
  const fieldCls = (val: string) =>
    `w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
      touched && !val.trim()
        ? "border-red-300 bg-red-50"
        : "border-gray-200 bg-white"
    }`;
  const dateError = touched && validFrom && validTo && validTo < validFrom;

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden h-fit sticky top-4">
      {/* panel header */}
      <div className="px-5 py-4 border-b border-gray-100" style={{background:"#1e3a5f"}}>
        <div className="flex items-center gap-2.5">
          <FileText className="w-4 h-4 text-white/80" />
          <h2 className="text-sm font-semibold text-white">Statement Details</h2>
        </div>
        <p className="text-xs text-white/60 mt-1">Fill in the statement information before saving</p>
      </div>

      <div className="px-5 py-5 space-y-4">
        {/* Statement Name */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            Statement Name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            placeholder="e.g. May 2026 IndiGo Statement"
            value={statementName}
            onChange={e => setStatementName(e.target.value)}
            className={fieldCls(statementName)}
          />
          {touched && !statementName.trim() && (
            <p className="text-[11px] text-red-500 mt-1">Statement name is required</p>
          )}
        </div>

        {/* Agency */}
        <AgencyDropdown
          agency={agency}
          setAgency={setAgency}
          agencyOptions={agencyOptions}
          touched={touched}
          fieldCls={fieldCls}
        />

        {/* Valid From */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Calendar className="w-3.5 h-3.5 inline mr-1" />
            Statement Valid From <span className="text-red-500">*</span>
          </label>
          <input
            type="date"
            value={validFrom}
            onChange={e => setValidFrom(e.target.value)}
            className={fieldCls(validFrom)}
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
            onChange={e => setValidTo(e.target.value)}
            className={dateError ? "w-full border border-red-300 bg-red-50 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" : fieldCls(validTo)}
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

// ── component ──────────────────────────────────────────────────────────────
export default function UploadTicketsPage() {
  const router = useRouter();

  type Step = "drop" | "mapping" | "preview" | "saving" | "done";
  const [step,           setStep]           = useState<Step>("drop");
  const [preview,        setPreview]        = useState<ExtractionPreview | null>(null);
  const [storedFile,     setStoredFile]     = useState<File | null>(null);
  const [mapping,        setMapping]        = useState<Record<string, string>>({});
  const [applyingMap,    setApplyingMap]    = useState(false);
  const [parsing,        setParsing]        = useState(false);
  const [downloading,    setDownloading]    = useState(false);
  const [error,          setError]          = useState<string | null>(null);
  const [batchId,        setBatchId]        = useState<string | null>(null);
  const [rows,           setRows]           = useState<TicketRow[]>([]);
  const downloadLinkRef  = useRef<HTMLAnchorElement>(null);

  // ── Statement form state ───────────────────────────────────────────────────
  const [statementName, setStatementName]   = useState("");
  const [agency,        setAgency]          = useState("");
  const [agencyOptions, setAgencyOptions]   = useState<string[]>([]);

  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then(r => setAgencyOptions(r.data.map(s => s.name)))
      .catch(() => {});
  }, []);
  const [validFrom,     setValidFrom]     = useState("");
  const [validTo,       setValidTo]       = useState("");
  const [formTouched,   setFormTouched]   = useState(false);

  const isStatementComplete =
    statementName.trim() !== "" &&
    agency !== "" &&
    validFrom !== "" &&
    validTo !== "" &&
    validTo >= validFrom;

  // ── Editable row handlers ─────────────────────────────────────────────────
  const handleTicketRowChange = useCallback((idx: number, key: keyof TicketRow, val: string) => {
    setRows(prev => prev.map((r, i) => {
      if (i !== idx) return r;
      const col = TICKET_COL_GROUPS.flatMap(g => g.cols).find(c => c.key === key);
      return { ...r, [key]: col?.type === "number" ? (val === "" ? null : parseFloat(val)) : (val || null) };
    }));
  }, []);
  const handleDeleteTicketRow = useCallback((idx: number) =>
    setRows(prev => prev.filter((_, i) => i !== idx)), []);
  const handleAddTicketRow = () =>
    setRows(prev => [...prev, { row_order: prev.length } as TicketRow]);

  // ── Filter + bulk edit state & handlers ───────────────────────────────────
  const [filterText,   setFilterText]   = useState("");
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [bulkColKey,   setBulkColKey]   = useState("");
  const [bulkColValue, setBulkColValue] = useState("");

  const handleToggleRow = useCallback((idx: number) => {
    setSelectedRows(prev => { const next = new Set(prev); next.has(idx) ? next.delete(idx) : next.add(idx); return next; });
  }, []);
  const handleToggleAllFiltered = useCallback((filteredIndices: number[], allSelected: boolean) => {
    setSelectedRows(prev => { const next = new Set(prev); if (allSelected) filteredIndices.forEach(i => next.delete(i)); else filteredIndices.forEach(i => next.add(i)); return next; });
  }, []);
  const handleBulkApply = () => {
    if (!bulkColKey || bulkColValue === "") return;
    const col = TICKET_COL_GROUPS.flatMap(g => g.cols).find(c => c.key === bulkColKey);
    setRows(prev => prev.map((r, i) => {
      if (!selectedRows.has(i)) return r;
      return { ...r, [bulkColKey]: col?.type === "number" ? (bulkColValue === "" ? null : parseFloat(bulkColValue)) : (bulkColValue || null) };
    }));
    setBulkColValue("");
  };
  const resetFilter = () => { setFilterText(""); setSelectedRows(new Set()); setBulkColKey(""); setBulkColValue(""); };

  // ── Template download ────────────────────────────────────────────────────
  const handleDownloadTemplate = async () => {
    setDownloading(true);
    try {
      const resp = await api.get("/tickets/template/download", { responseType: "blob" });
      const url  = URL.createObjectURL(resp.data as Blob);
      const a    = downloadLinkRef.current!;
      a.href     = url;
      a.download = "ticket_template.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Failed to download template.");
    } finally {
      setDownloading(false);
    }
  };

  // ── Step 1: drag-drop → extract ──────────────────────────────────────────
  const onDrop = useCallback(async (files: File[]) => {
    if (!files[0]) return;
    setError(null);
    setParsing(true);
    setStoredFile(files[0]);
    try {
      const form = new FormData();
      form.append("file", files[0]);
      const { data } = await api.post<ExtractionPreview>("/tickets/upload/extract", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(data);
      setMapping(data.suggested_mapping ?? {});
      setStep("mapping");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to parse file. Please check the format.");
      setStoredFile(null);
    } finally {
      setParsing(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/vnd.ms-excel": [],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [],
    },
    maxFiles: 1,
    disabled: parsing,
  });

  // ── Step 2: apply user mapping → re-extract ──────────────────────────────
  const applyMapping = async () => {
    if (!storedFile || !preview) return;
    setApplyingMap(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", storedFile);
      form.append("column_mapping", JSON.stringify(mapping));
      const { data } = await api.post<ExtractionPreview>("/tickets/upload/extract", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(data);
      setRows(data.rows);
      resetFilter();
      setStep("preview");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to apply mapping.");
    } finally {
      setApplyingMap(false);
    }
  };

  const requiredKeys    = OUR_FIELDS.filter(f => f.required).map(f => f.key);
  const missingRequired = requiredKeys.filter(k => !mapping[k] || mapping[k] === SKIP);

  // ── Step 3: confirm → save ────────────────────────────────────────────────
  const confirmUpload = async () => {
    setFormTouched(true);
    if (!isStatementComplete || !preview) return;
    setStep("saving");
    setError(null);
    try {
      const { data } = await api.post<{ batch_id: string; created_count: number }>(
        "/tickets/upload/confirm",
        {
          file_name:      preview.file_name,
          rows,
          statement_name: statementName,
          agency,
          valid_from:     validFrom,
          valid_to:       validTo,
        },
      );
      setBatchId(data.batch_id);
      if (storedFile && data.batch_id) {
        console.log("[GCS] Uploading ticket file to bucket | batch_id=", data.batch_id, "| file=", storedFile.name, "| size=", storedFile.size);
        try {
          const fd = new FormData();
          fd.append("file", storedFile);
          const res = await api.post(`/tickets/statements/${data.batch_id}/file`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          console.log("[GCS] Ticket file upload SUCCESS | response=", res.data);
        } catch (uploadErr) {
          console.error("[GCS] Ticket file upload FAILED:", uploadErr);
        }
      } else {
        console.warn("[GCS] Skipping file upload | storedFile=", storedFile, "| batch_id=", data.batch_id);
      }
      setStep("done");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save tickets.");
      setStep("preview");
    }
  };

  const reset = () => {
    setStep("drop"); setPreview(null); setStoredFile(null);
    setMapping({}); setBatchId(null); setError(null); setRows([]); resetFilter();
    setStatementName(""); setAgency(""); setValidFrom(""); setValidTo(""); setFormTouched(false);
  };

  const isDone = step === "done";

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <a ref={downloadLinkRef} className="hidden" />

      {/* page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/tickets" className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Upload Tickets</h1>
            <p className="text-xs text-gray-500 mt-0.5">Create a new statement and import supplier XLS/XLSX</p>
          </div>
        </div>

        {/* Step indicator */}
        {!isDone && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            {(["drop", "mapping", "preview", "done"] as Step[]).map((s, i) => {
              const labels: Record<Step, string> = { drop: "Upload", mapping: "Map Columns", preview: "Preview", saving: "Saving", done: "Done" };
              const active  = step === s;
              const passed  = ["drop", "mapping", "preview", "saving", "done"].indexOf(step) > i;
              return (
                <div key={s} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-gray-300">›</span>}
                  <span className={`px-2.5 py-0.5 rounded-full font-medium ${
                    active  ? "bg-[#1e3a5f] text-white" :
                    passed  ? "bg-green-100 text-green-700" :
                              "bg-gray-100 text-gray-400"
                  }`}>
                    {labels[s as Step] ?? s}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
          <button onClick={() => setError(null)} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* ── Done screen (full width, no split) ─────────────────────────────── */}
      {isDone && batchId && preview && (
        <div className="max-w-md mx-auto text-center space-y-5 py-10">
          <div className="w-16 h-16 bg-green-50 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Statement Created</h2>
            <p className="text-sm font-medium text-gray-700 mt-1">{statementName}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {agency} · {validFrom} – {validTo}
            </p>
            <p className="text-sm text-gray-500 mt-2">
              {preview.total_rows} tickets saved from <span className="font-medium">{preview.file_name}</span>
            </p>
            <p className="text-xs text-gray-400 mt-0.5 font-mono">Batch: {batchId}</p>
          </div>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={reset}
              className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              Upload Another
            </button>
            <button
              onClick={() => router.push("/tickets")}
              className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#16304f]"
            >
              <FileSpreadsheet className="w-4 h-4" /> View Ticket Repository
            </button>
          </div>
        </div>
      )}

      {/* ── Saving screen ──────────────────────────────────────────────────── */}
      {step === "saving" && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mx-auto" />
            <p className="text-sm text-gray-600">Saving statement and tickets to database…</p>
          </div>
        </div>
      )}

      {/* ── Drop step — two-panel layout ──────────────────────────────────── */}
      {step === "drop" && (
        <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-6 items-start">
          {/* LEFT: Statement form */}
          <StatementFormPanel
            statementName={statementName} setStatementName={setStatementName}
            agency={agency}               setAgency={setAgency}
            agencyOptions={agencyOptions}
            validFrom={validFrom}         setValidFrom={setValidFrom}
            validTo={validTo}             setValidTo={setValidTo}
            touched={formTouched}
            isComplete={isStatementComplete}
          />
          {/* RIGHT: dropzone */}
          <div className="space-y-4 min-w-0">

            {/* drop content */}
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-start gap-4">
                <FileSpreadsheet className="w-8 h-8 text-blue-500 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-blue-800 mb-0.5">Download the ticket template</p>
                  <p className="text-xs text-blue-600 leading-relaxed">
                    Use our template for instant column auto-mapping. If you have your own format,
                    upload it and we&apos;ll guide you through column mapping.
                  </p>
                </div>
                <button
                  onClick={handleDownloadTemplate}
                  disabled={downloading}
                  className="flex items-center gap-1.5 shrink-0 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-xs font-semibold transition-colors"
                >
                  {downloading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                  {downloading ? "Downloading…" : "Download Template"}
                </button>
              </div>

              <div className="bg-white rounded-xl border border-gray-200 p-6">
                <div
                  {...getRootProps()}
                  className={`border-2 border-dashed rounded-xl p-14 text-center cursor-pointer transition-colors ${
                    isDragActive ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"
                  } ${parsing ? "opacity-60 cursor-not-allowed" : ""}`}
                >
                  <input {...getInputProps()} />
                  {parsing
                    ? <RefreshCw className="w-10 h-10 mx-auto text-blue-400 mb-3 animate-spin" />
                    : <Upload className="w-10 h-10 mx-auto text-gray-400 mb-3" />}
                  <p className="text-sm font-medium text-gray-700">
                    {parsing ? "Parsing file…" : isDragActive ? "Drop the file here" : "Drag & drop XLS / XLSX"}
                  </p>
                  {!parsing && <p className="text-xs text-gray-400 mt-1">or click to browse</p>}
                </div>
              </div>
            </div>
          </div>{/* /right panel */}
        </div>
      )}{/* /drop two-panel */}

      {/* ── Mapping step — full width ──────────────────────────────────────── */}
      {step === "mapping" && preview && (
        <div className="space-y-4">
          {/* statement summary bar */}
          <div className="bg-[#1e3a5f]/5 border border-[#1e3a5f]/20 rounded-xl px-5 py-3 flex items-center gap-4 flex-wrap">
            <FileText className="w-4 h-4 text-[#1e3a5f] shrink-0" />
            <span className="text-xs font-semibold text-[#1e3a5f]">{statementName || <span className="text-red-400 italic">Statement name missing</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{agency || <span className="text-red-400 italic">Agency missing</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{validFrom && validTo ? `${validFrom} – ${validTo}` : <span className="text-red-400 italic">Dates missing</span>}</span>
            {!isStatementComplete && (
              <button
                onClick={() => setStep("drop")}
                className="ml-auto text-xs text-amber-600 underline hover:text-amber-700"
              >
                ← Fill statement details
              </button>
            )}
          </div>

          <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-5 py-3">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="w-5 h-5 text-blue-600" />
              <div>
                <p className="text-sm font-semibold text-gray-800">{preview.file_name}</p>
                <p className="text-xs text-gray-500">{preview.total_rows} rows · {preview.xls_columns.length} columns detected</p>
              </div>
            </div>
            <button onClick={reset} className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50">
              Cancel
            </button>
          </div>

          {preview.is_template_match ? (
            <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4 flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-green-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-green-800">
                  All columns matched automatically ({Object.keys(preview.suggested_mapping).length} of {OUR_FIELDS.length} fields)
                </p>
                <p className="text-xs text-green-600 mt-0.5">
                  This looks like our template. You can review the mapping below or proceed directly.
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-800">
                  {Object.keys(preview.suggested_mapping).length} of {OUR_FIELDS.length} columns auto-matched
                </p>
                <p className="text-xs text-amber-600 mt-0.5">
                  Map the remaining columns below, then click &quot;Apply Mapping&quot;.
                  Required fields are marked with <span className="text-red-500 font-bold">*</span>.
                </p>
              </div>
            </div>
          )}

          {preview.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {preview.warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Column Mapping</p>
              <p className="text-xs text-gray-400">Select which column from your file maps to each field</p>
            </div>
            <div className="divide-y divide-gray-100 max-h-[460px] overflow-y-auto">
              {OUR_FIELDS.map(field => {
                const mapped    = mapping[field.key];
                const isSkipped = !mapped || mapped === SKIP;
                return (
                  <div key={field.key} className="flex items-center px-5 py-2.5 gap-4">
                    <div className="w-48 shrink-0">
                      <span className="text-xs font-medium text-gray-700">{field.label}</span>
                      {field.required && <span className="text-red-500 ml-0.5 text-xs">*</span>}
                    </div>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                    <div className="flex-1 relative">
                      <select
                        value={mapped ?? SKIP}
                        onChange={e => setMapping(prev => ({ ...prev, [field.key]: e.target.value }))}
                        className={`w-full appearance-none text-xs border rounded-lg px-3 py-1.5 pr-7 focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                          isSkipped
                            ? field.required
                              ? "border-red-300 bg-red-50 text-red-600"
                              : "border-gray-200 bg-gray-50 text-gray-400"
                            : "border-green-300 bg-green-50 text-green-800"
                        }`}
                      >
                        <option value={SKIP}>— Skip / Not in file —</option>
                        {preview.xls_columns.map(col => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                      <ChevronDown className="w-3 h-3 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                    <div className="w-36 shrink-0">
                      {!isSkipped ? (
                        (() => {
                          const sample = preview.sample_row?.[mapped!];
                          if (!sample) return <span className="text-[10px] text-gray-300 italic">empty</span>;
                          const display = sample.length > 20 ? sample.slice(0, 18) + "…" : sample;
                          return (
                            <span title={sample} className="inline-block px-2 py-0.5 rounded bg-blue-50 border border-blue-100 text-[10px] font-mono text-blue-700 truncate max-w-full">
                              {display}
                            </span>
                          );
                        })()
                      ) : (
                        <span className="text-[10px] text-gray-200">—</span>
                      )}
                    </div>
                    <div className="w-20 shrink-0 text-right">
                      {!isSkipped
                        ? <span className="inline-flex items-center gap-1 text-[10px] font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full"><CheckCircle className="w-2.5 h-2.5" /> Mapped</span>
                        : field.required
                          ? <span className="text-[10px] font-medium text-red-500">Required</span>
                          : <span className="text-[10px] text-gray-300">Optional</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-500">
              {missingRequired.length > 0 && !preview.is_template_match && (
                <span className="text-red-500">
                  Required fields not mapped: {missingRequired.map(k => OUR_FIELDS.find(f => f.key === k)?.label).join(", ")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {preview.is_template_match ? (
                <button
                  onClick={() => { setRows(preview.rows); resetFilter(); setStep("preview"); }}
                  className="flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f]"
                >
                  Proceed to Preview <ArrowRight className="w-3.5 h-3.5" />
                </button>
              ) : (
                <button
                  onClick={applyMapping}
                  disabled={applyingMap || missingRequired.length > 0}
                  className="flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {applyingMap
                    ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Applying…</>
                    : <>Apply Mapping <ArrowRight className="w-3.5 h-3.5" /></>}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Preview step — full width ──────────────────────────────────────── */}
      {step === "preview" && preview && (
        <div className="space-y-3">
          {/* statement summary bar */}
          <div className="bg-[#1e3a5f]/5 border border-[#1e3a5f]/20 rounded-xl px-5 py-3 flex items-center gap-4 flex-wrap">
            <FileText className="w-4 h-4 text-[#1e3a5f] shrink-0" />
            <span className="text-xs font-semibold text-[#1e3a5f]">{statementName || <span className="text-red-400 italic">Statement name missing</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{agency || <span className="text-red-400 italic">Agency missing</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{validFrom && validTo ? `${validFrom} – ${validTo}` : <span className="text-red-400 italic">Dates missing</span>}</span>
            {!isStatementComplete && (
              <button
                onClick={() => setStep("drop")}
                className="ml-auto text-xs text-amber-600 underline hover:text-amber-700"
              >
                ← Fill statement details
              </button>
            )}
          </div>

          <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-5 py-3">
            <div className="flex items-center gap-4">
              <FileSpreadsheet className="w-5 h-5 text-green-600" />
              <div>
                <p className="text-sm font-semibold text-gray-800">{preview.file_name}</p>
                <p className="text-xs text-gray-500">{preview.total_rows} rows parsed</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setStep("mapping")}
                className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50"
              >
                Back to Mapping
              </button>
              <button
                onClick={confirmUpload}
                disabled={!isStatementComplete}
                title={!isStatementComplete ? "Complete statement details first" : undefined}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <CheckCircle className="w-3.5 h-3.5" /> Confirm & Save {rows.length} Rows
              </button>
            </div>
          </div>

          {preview.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {preview.warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 px-4 py-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none"/>
                <input
                  type="text"
                  placeholder="Filter by ticket, sector, airline, or any value…"
                  value={filterText}
                  onChange={e=>setFilterText(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              {filterText&&(
                <>
                  <span className="text-[11px] text-gray-400 whitespace-nowrap">
                    {rows.filter(row=>Object.values(row).filter(v=>v!=null).join(" ").toLowerCase().includes(filterText.toLowerCase())).length} of {rows.length} rows
                  </span>
                  <button onClick={()=>setFilterText("")} title="Clear filter" className="p-1 hover:bg-gray-100 rounded-lg">
                    <X className="w-3.5 h-3.5 text-gray-500"/>
                  </button>
                </>
              )}
            </div>
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
                  {TICKET_COL_GROUPS.map(g=>(
                    <optgroup key={g.label} label={g.label}>
                      {g.cols.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}
                    </optgroup>
                  ))}
                </select>
                {bulkColKey&&(()=>{
                  const colType=TICKET_COL_GROUPS.flatMap(g=>g.cols).find(c=>c.key===bulkColKey)?.type??"text";
                  if(colType==="date")return(
                    <input type="date" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
                  );
                  if(colType==="number")return(
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
              <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Review &amp; Edit</h2>
              <span className="ml-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">{rows.length} rows</span>
              <span className="text-[10px] text-gray-400 ml-auto">Scroll horizontally · Click any cell to edit</span>
            </div>
            <TicketReviewTable
              rows={rows}
              colGroups={TICKET_COL_GROUPS}
              onChange={handleTicketRowChange}
              onDelete={handleDeleteTicketRow}
              onAdd={handleAddTicketRow}
              filterText={filterText}
              selectedRows={selectedRows}
              onToggleRow={handleToggleRow}
              onToggleAllFiltered={handleToggleAllFiltered}
            />
          </div>
        </div>
      )}
    </div>
  );
}
