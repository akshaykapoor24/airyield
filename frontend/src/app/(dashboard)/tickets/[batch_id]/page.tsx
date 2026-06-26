"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ChevronLeft, Search, RefreshCw, FileSpreadsheet, Calculator,
  CheckCircle2, Pencil, Trash2, X, Save, AlertTriangle,
  FileSearch, ChevronDown, ChevronRight, Building2, Calendar, Hash, FileText,
  AlertCircle, TrendingUp,
} from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";

// ── Types ──────────────────────────────────────────────────────────────────

type TicketStatement = {
  batch_id:       string;
  statement_name: string | null;
  statement_type: "B2B" | "AIRLINE";
  agency:         string;
  valid_from:     string;
  valid_to:       string;
  file_name:      string;
  file_url:       string | null;
  ticket_count:   number;
  created_at:     string;
};

type UploadedTicket = {
  id: number;
  batch_id: string;
  file_name: string;
  ticket_number: string | null;
  booking_ref: string | null;
  segment_type: string | null;
  invoice_type: string | null;
  invoice_no: string | null;
  ticket_date: string | null;
  last_name: string | null;
  first_name: string | null;
  sector: string | null;
  booking_class: string | null;
  departure_datetime: string | null;
  gds_pnr: string | null;
  airlines_code: string | null;
  airline_name: string | null;
  sell_fare: number | null;
  sell_tax: number | null;
  sell_tax_yq: number | null;
  sale_yr: number | null;
  sale_k3: number | null;
  rei_sell: number | null;
  seat_selection: number | null;
  excess_baggage: number | null;
  meals: number | null;
  rfd_sell: number | null;
  can_charge: number | null;
  booking_fee_sell: number | null;
  cgst_sell: number | null;
  sgst_sell: number | null;
  igst_sell: number | null;
  comm_sell: number | null;
  adm: number | null;
  incentive_sell: number | null;
  dis_sell: number | null;
  tds_sell: number | null;
  total_amt: number | null;
  paid_by_credit_card: number | null;
  net_amt: number | null;
  cc: string | null;
  acc_code: string | null;
  sold_to: string | null;
  customer_name: string | null;
  matched_deal_id: number | null;
  matched_deal_type: string | null;
  matched_deal_name: string | null;
  calculated_incentive: number | null;
  incentive_breakdown: Record<string, number> | null;
  ticket_status: string;
  split_type: string | null;
  exclusion_reason: string | null;
  adm_acm_ra: string | null;
  created_at: string;
  created_by_id: number;
  // Airline-specific
  statement_type: string | null;
  pax_name: string | null;
  air_pnr: string | null;
  pcc: string | null;
  transaction_type: string | null;
  fare_basis: string | null;
  fop: string | null;
  fop_details: string | null;
  flight_no: string | null;
  travel_dt: string | null;
  wo_tax: number | null;
  other_tax: number | null;
  comm_percent: number | null;
  net_fare: number | null;
  invoice_fare: number | null;
  roe: number | null;
  nuc: number | null;
  gstn: string | null;
  business_phone: string | null;
  business_email: string | null;
  tax_breakup: Record<string, number> | null;
};

const INCENTIVE_TYPE_COLS = [
  { key: "PLB",                    label: "PLB Inc."       },
  { key: "Super PLB",              label: "Super PLB"      },
  { key: "Transaction Fee",        label: "Trans. Fee"     },
  { key: "Deposit Incentive (DI)", label: "DI Inc."        },
  { key: "Marketing Fund",         label: "Mktg Fund"      },
  { key: "Ancillary",              label: "Ancillary Inc." },
  { key: "Frontend",               label: "Frontend Inc."  },
  { key: "Backend",                label: "Backend Inc."   },
  { key: "Cashback",               label: "Cashback"       },
  { key: "Segment Incentive",      label: "Seg. Inc."      },
  { key: "Push Action",            label: "Push Act."      },
] as const;

type RunCalcResult = {
  ticket_id: number;
  matched: boolean;
  excluded: boolean;
  cancelled: boolean;
  included: boolean;
  matched_deal_id: number | null;
  matched_deal_type: string | null;
  matched_deal_name: string | null;
  calculated_incentive: number | null;
  incentive_breakdown: Record<string, number> | null;
  message: string;
};

type BatchRunCalcResult = { processed: number; matched: number; unmatched: number; errors: number; excluded: number; cancelled: number };

type DealMatchSummary = {
  deal_id: number;
  deal_type: string;
  deal_name: string;
  deal_no: string;
  calculated_incentive: number | null;
  valid_from: string | null;
  valid_to: string | null;
  deal_maker_name: string | null;
  is_best: boolean;
};

type MatchStep = { step: string; passed: boolean; ticket_value: string; deal_value: string; detail: string };
type IncentiveBreakdown = {
  incentive_type: string;
  target_based: string;
  targetCalcCols: string;
  sell_fare: number | null;
  sell_tax_yq_added: boolean;
  sell_tax_yq_value: number | null;
  sale_yr_added: boolean;
  sale_yr_value: number | null;
  base_total: number;
  incentiveAmtPct: number | null;
  incentive_num_pct: string;
  formula: string;
  result: number | null;
  // slab-specific (present when target_based === "Slab Based")
  is_slab?: boolean;
  slab_period?: string | null;
  slab_period_range?: string | null;
  slab_achieved?: number | null;
  slab_target?: number | null;
  slab_cell?: string | null;
};
type PLBDiagnostic = { plb_key: string; raw_plb: Record<string, unknown>; steps: MatchStep[]; incentive_breakdown: IncentiveBreakdown | null; plb_overall_match: boolean };
type ExclusionRuleStep = { field: string; rule_value: string; ticket_value: string; matched: boolean };
type ExclusionRuleDiagnostic = { rule_name: string; is_excluded: boolean; reason: string; steps: ExclusionRuleStep[] };
type DealDiagnosticItem = {
  deal_id: number; deal_type: string; deal_name: string; deal_no: string;
  valid_from: string | null; valid_to: string | null; trigger_type: string | null;
  supplier_name: string | null;
  deal_validity_step: MatchStep; plbs: PLBDiagnostic[];
  overall_match: boolean; best_incentive: number | null; deal_lifecycle_status: string | null;
  exclusion_diagnostic: ExclusionRuleDiagnostic | null;
  inclusion_diagnostic: ExclusionRuleDiagnostic | null;
};
type MatchDiagnosis = {
  ticket_id: number; raw_airline_code: string; normalized_codes: string[];
  airline_resolved: string | null; airline_resolution_detail: string;
  raw_departure: string | null; raw_ticket_date: string | null;
  travel_date: string | null; travel_date_detail: string;
  segment_type: string | null; booking_class: string | null;
  cabin_groups_resolved: string[]; cabin_resolution_detail: string;
  invoice_type: string | null;
  sell_fare: number | null; sell_tax_yq: number | null; sale_yr: number | null;
  total_deals_checked: number; matched_count: number; deals: DealDiagnosticItem[];
};

// ── Constants ──────────────────────────────────────────────────────────────

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

const EXCL_FIELD_LABELS: Record<string, string> = {
  validFrom:          "Valid From",
  validTo:            "Valid To",
  originAirport:      "Origin Airport",
  destAirport:        "Dest Airport",
  originContinents:   "Origin Continent",
  destContinents:     "Dest Continent",
  continents:         "Continent",
  originCountry:      "Origin Country",
  destCountry:        "Dest Country",
  originCountryGroup: "Origin Country Group",
  destCountryGroup:   "Dest Country Group",
  countryGroup:       "Country Group",
  city:               "City",
  class:              "Booking Class",
};

const TICKET_STATUS_STYLE: Record<string, string> = {
  draft:      "bg-gray-100 text-gray-500",
  calculated: "bg-emerald-50 text-emerald-600",
  included:   "bg-teal-50 text-teal-600 border border-teal-200",
  reviewed:   "bg-blue-50 text-blue-600",
  excluded:   "bg-red-50 text-red-600 border border-red-200",
  cancelled:  "bg-orange-50 text-orange-600 border border-orange-200",
  reversed:   "bg-purple-50 text-purple-600 border border-purple-200",
};
const TICKET_STATUS_LABEL: Record<string, string> = {
  draft: "Draft", calculated: "Calculated", included: "Included",
  reviewed: "Reviewed", excluded: "Excluded", cancelled: "Cancelled",
  reversed: "Reversed",
};

function getStatusDisplay(status: string, exclusionReason: string | null): { style: string; label: string } {
  if (status === "excluded") {
    if (exclusionReason?.startsWith("Not included:"))
      return { style: "bg-amber-50 text-amber-700 border border-amber-200", label: "Incl. Failed" };
    if (exclusionReason?.startsWith("Excluded by Exclusion"))
      return { style: "bg-red-50 text-red-600 border border-red-200", label: "Excl. Rule" };
    return { style: "bg-red-50 text-red-600 border border-red-200", label: "Excluded" };
  }
  return {
    style: TICKET_STATUS_STYLE[status] ?? "bg-gray-100 text-gray-400",
    label: TICKET_STATUS_LABEL[status] ?? status,
  };
}

const TEXT_HEADERS: { key: keyof UploadedTicket; label: string }[] = [
  { key: "ticket_number",      label: "Ticket #"      },
  { key: "booking_ref",        label: "Booking Ref"   },
  { key: "segment_type",       label: "Segment"       },
  { key: "invoice_type",       label: "Inv. Type"     },
  { key: "adm_acm_ra",         label: "ADM/ACM/RA"    },
  { key: "invoice_no",         label: "Inv. No"       },
  { key: "last_name",          label: "Last Name"     },
  { key: "first_name",         label: "First Name"    },
  { key: "ticket_date",        label: "Ticket Date"   },
  { key: "sector",             label: "Sector"        },
  { key: "booking_class",      label: "Class"         },
  { key: "departure_datetime", label: "Departure"     },
  { key: "gds_pnr",            label: "GDS PNR"       },
  { key: "airlines_code",      label: "Airline Code"  },
  { key: "airline_name",       label: "Airline"       },
];
const NUM_HEADERS: { key: keyof UploadedTicket; label: string }[] = [
  { key: "sell_fare",           label: "Sell Fare"   },
  { key: "sell_tax",            label: "Sell Tax"    },
  { key: "sell_tax_yq",         label: "Tax YQ"      },
  { key: "sale_yr",             label: "Sale YR"     },
  { key: "sale_k3",             label: "Sale K3"     },
  { key: "rei_sell",            label: "REI"         },
  { key: "seat_selection",      label: "Seat Sel."   },
  { key: "excess_baggage",      label: "Exc. Bag."   },
  { key: "meals",               label: "Meals"       },
  { key: "rfd_sell",            label: "RFD"         },
  { key: "can_charge",          label: "CAN"         },
  { key: "booking_fee_sell",    label: "Book. Fee"   },
  { key: "cgst_sell",           label: "CGST"        },
  { key: "sgst_sell",           label: "SGST"        },
  { key: "igst_sell",           label: "IGST"        },
  { key: "comm_sell",           label: "Comm"        },
  { key: "adm",                 label: "ADM"         },
  { key: "incentive_sell",      label: "Incentive"   },
  { key: "dis_sell",            label: "Dis"         },
  { key: "tds_sell",            label: "TDS"         },
  { key: "total_amt",           label: "Total Amt"   },
  { key: "paid_by_credit_card", label: "Paid CC"     },
  { key: "net_amt",             label: "Net AMT"     },
];

const EXTRA_TEXT_HEADERS: { key: keyof UploadedTicket; label: string }[] = [
  { key: "cc",            label: "CC"       },
  { key: "acc_code",      label: "Acc Code" },
  { key: "sold_to",       label: "Sold To"  },
  { key: "customer_name", label: "Name"     },
];

const AIRLINE_TEXT_HEADERS: { key: keyof UploadedTicket; label: string }[] = [
  { key: "pax_name",        label: "Pax Name"     },
  { key: "air_pnr",         label: "Air PNR"      },
  { key: "pcc",             label: "PCC"          },
  { key: "transaction_type",label: "Txn Type"     },
  { key: "fare_basis",      label: "Fare Basis"   },
  { key: "fop",             label: "FOP"          },
  { key: "fop_details",     label: "FOP Details"  },
  { key: "flight_no",       label: "Flight No"    },
  { key: "travel_dt",       label: "Travel Dt"    },
  { key: "gstn",            label: "GSTN"         },
];

const AIRLINE_NUM_HEADERS: { key: keyof UploadedTicket; label: string }[] = [
  { key: "wo_tax",      label: "WO Tax"    },
  { key: "other_tax",   label: "Other Tax" },
  { key: "comm_percent",label: "Comm %"    },
  { key: "net_fare",    label: "Net Fare"  },
  { key: "invoice_fare",label: "Inv Fare"  },
  { key: "roe",         label: "ROE"       },
  { key: "nuc",         label: "NUC"       },
];

const EDITABLE_FIELDS: { key: keyof UploadedTicket; label: string; type: "text"|"date"|"number"|"select"; options?: string[] }[] = [
  { key: "ticket_number",      label: "Ticket Number",       type: "text"   },
  { key: "booking_ref",        label: "Booking Ref",         type: "text"   },
  { key: "last_name",          label: "Last Name",           type: "text"   },
  { key: "first_name",         label: "First Name",          type: "text"   },
  { key: "sector",             label: "Sector",              type: "text"   },
  { key: "booking_class",      label: "Booking Class",       type: "text"   },
  { key: "airline_name",       label: "Airline Name",        type: "text"   },
  { key: "airlines_code",      label: "Airline Code",        type: "text"   },
  { key: "gds_pnr",            label: "GDS PNR",             type: "text"   },
  { key: "ticket_date",        label: "Ticket Date",         type: "date"   },
  { key: "departure_datetime", label: "Departure",           type: "date"   },
  { key: "segment_type",       label: "Segment Type",        type: "text"   },
  { key: "invoice_type",       label: "Invoice Type",        type: "text"   },
  { key: "invoice_no",         label: "Invoice No",          type: "text"   },
  { key: "sell_fare",          label: "Sell Fare",           type: "number" },
  { key: "sell_tax",           label: "Sell Tax",            type: "number" },
  { key: "sell_tax_yq",        label: "Sell Tax YQ",         type: "number" },
  { key: "sale_yr",            label: "Sale YR",             type: "number" },
  { key: "sale_k3",            label: "Sale K3",             type: "number" },
  { key: "rei_sell",           label: "REI Sell",            type: "number" },
  { key: "seat_selection",     label: "Seat Selection",      type: "number" },
  { key: "excess_baggage",     label: "Excess Baggage",      type: "number" },
  { key: "meals",              label: "Meals",               type: "number" },
  { key: "rfd_sell",           label: "RFD Sell",            type: "number" },
  { key: "can_charge",         label: "CAN Charge",          type: "number" },
  { key: "booking_fee_sell",   label: "Booking Fee",         type: "number" },
  { key: "cgst_sell",          label: "CGST",                type: "number" },
  { key: "sgst_sell",          label: "SGST",                type: "number" },
  { key: "igst_sell",          label: "IGST",                type: "number" },
  { key: "comm_sell",          label: "Comm Sell",           type: "number" },
  { key: "adm",                label: "ADM",                 type: "number" },
  { key: "incentive_sell",     label: "Incentive Sell",      type: "number" },
  { key: "dis_sell",           label: "Dis Sell",            type: "number" },
  { key: "tds_sell",           label: "TDS Sell",            type: "number" },
  { key: "total_amt",          label: "Total Amt",           type: "number" },
  { key: "paid_by_credit_card",label: "Paid By CC",          type: "number" },
  { key: "net_amt",            label: "Net AMT",             type: "number" },
  { key: "cc",                 label: "CC",                  type: "text"   },
  { key: "acc_code",           label: "Acc Code",            type: "text"   },
  { key: "sold_to",            label: "Sold To",             type: "select", options: ["customer", "agency"] },
  { key: "customer_name",      label: "Customer Name",       type: "text"   },
  { key: "ticket_status",      label: "Status",              type: "text"   },
];

const EDIT_GROUPS = [
  { label: "Passenger & Trip", keys: ["ticket_number","booking_ref","last_name","first_name","sector","booking_class","ticket_date","departure_datetime","segment_type","invoice_type","invoice_no"] },
  { label: "Flight Info",      keys: ["airline_name","airlines_code","gds_pnr"] },
  { label: "Financial",        keys: ["sell_fare","sell_tax","sell_tax_yq","sale_yr","sale_k3","rei_sell","seat_selection","excess_baggage","meals","rfd_sell","can_charge","booking_fee_sell","cgst_sell","sgst_sell","igst_sell","comm_sell","adm","incentive_sell","dis_sell","tds_sell","total_amt","paid_by_credit_card","net_amt"] },
  { label: "Account / Other",  keys: ["cc","acc_code","sold_to","customer_name","ticket_status"] },
];

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined) {
  if (v == null) return <span className="text-gray-300">—</span>;
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

// ── Component ──────────────────────────────────────────────────────────────

export default function StatementDetailPage() {
  const params  = useParams();
  const router  = useRouter();
  const batchId = params.batch_id as string;

  const [statement,  setStatement]  = useState<TicketStatement | null>(null);
  const [tickets,    setTickets]    = useState<UploadedTicket[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);

  // ── Pagination / filter ────────────────────────────────────────────────
  const [search,     setSearch]     = useState("");
  const [dateFrom,   setDateFrom]   = useState("");
  const [dateTo,     setDateTo]     = useState("");

  const [filterAirlineCode, setFilterAirlineCode] = useState("");
  const [filterAirline,     setFilterAirline]     = useState("");
  const [filterSegment,     setFilterSegment]     = useState("");
  const [filterInvType,     setFilterInvType]     = useState("");
  const [filterClass,       setFilterClass]       = useState("");

  const filterOptions = useMemo(() => {
    const uniq = <T,>(arr: (T | null | undefined)[]): T[] =>
      [...new Set(arr.filter(Boolean) as T[])].sort();
    return {
      airlineCodes: uniq(tickets.map(t => t.airlines_code)),
      airlines:     uniq(tickets.map(t => t.airline_name)),
      segments:     uniq(tickets.map(t => t.segment_type)),
      invTypes:     uniq(tickets.map(t => t.invoice_type)),
      classes:      uniq(tickets.map(t => t.booking_class)),
    };
  }, [tickets]);
  const [page,       setPage]       = useState(1);
  const [pageSize,   setPageSize]   = useState<25|50|100>(25);

  // ── Selection ──────────────────────────────────────────────────────────
  const [selected,   setSelected]   = useState<Set<number>>(new Set());

  // ── Calculation state ──────────────────────────────────────────────────
  const [calcLoading,   setCalcLoading]   = useState<Set<number>>(new Set());
  const [batchCalcing,  setBatchCalcing]  = useState(false);
  const [batchResult,   setBatchResult]   = useState<BatchRunCalcResult | null>(null);

  // ── Save income summary modal ──────────────────────────────────────────
  const [showSaveSummary, setShowSaveSummary] = useState(false);
  const [summaryName,     setSummaryName]     = useState("");
  const [savingSummary,   setSavingSummary]   = useState(false);
  const [saveSummaryDone, setSaveSummaryDone] = useState(false);
  const [saveSummaryError,setSaveSummaryError]= useState<string | null>(null);

  // ── Edit modal ─────────────────────────────────────────────────────────
  const [editTicket,    setEditTicket]    = useState<UploadedTicket | null>(null);
  const [editDraft,     setEditDraft]     = useState<Partial<UploadedTicket>>({});
  const [saving,        setSaving]        = useState(false);

  // ── Delete modal ───────────────────────────────────────────────────────
  const [deleteTarget,  setDeleteTarget]  = useState<UploadedTicket | null>(null);
  const [deleting,      setDeleting]      = useState(false);

  // ── Matched deals modal ────────────────────────────────────────────────
  const [matchedDeals,  setMatchedDeals]  = useState<DealMatchSummary[] | null>(null);
  const [dealsLoading,  setDealsLoading]  = useState(false);

  // ── Diagnosis modal ────────────────────────────────────────────────────
  const [diagnosis,     setDiagnosis]     = useState<MatchDiagnosis | null>(null);
  const [diagTicket,    setDiagTicket]    = useState<UploadedTicket | null>(null);
  const [diagLoading,   setDiagLoading]   = useState(false);
  const [diagTab,       setDiagTab]       = useState<"all"|"matched"|"not_matched">("all");
  const [expandedDeals, setExpandedDeals] = useState<Set<number>>(new Set());
  const [rawPLBVisible, setRawPLBVisible] = useState<Set<string>>(new Set());

  // ── Data fetching ──────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stmtRes, ticketsRes] = await Promise.all([
        api.get<TicketStatement>(`/tickets/statements/${batchId}`),
        api.get<UploadedTicket[]>("/tickets/uploads", { params: { batch_id: batchId, limit: 2000 } }),
      ]);
      setStatement(stmtRes.data);
      setTickets(ticketsRes.data);
    } catch {
      setError("Failed to load statement data.");
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  // Silent refresh — used after batch operations so the table never flickers
  const refreshData = useCallback(async () => {
    try {
      const [stmtRes, ticketsRes] = await Promise.all([
        api.get<TicketStatement>(`/tickets/statements/${batchId}`),
        api.get<UploadedTicket[]>("/tickets/uploads", { params: { batch_id: batchId, limit: 2000 } }),
      ]);
      setStatement(stmtRes.data);
      setTickets(ticketsRes.data);
    } catch { /* silent */ }
  }, [batchId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Filtered + paginated tickets ───────────────────────────────────────
  const filtered = tickets.filter(t => {
    const q = search.toLowerCase();
    if (q) {
      const hay = [t.ticket_number, t.booking_ref, t.gds_pnr, t.last_name, t.first_name,
                   t.airlines_code, t.airline_name, t.sector, t.segment_type].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (dateFrom && t.ticket_date && t.ticket_date < dateFrom) return false;
    if (dateTo   && t.ticket_date && t.ticket_date > dateTo)   return false;
    if (filterAirlineCode && t.airlines_code  !== filterAirlineCode) return false;
    if (filterAirline     && t.airline_name   !== filterAirline)     return false;
    if (filterSegment     && t.segment_type   !== filterSegment)     return false;
    if (filterInvType     && t.invoice_type   !== filterInvType)     return false;
    if (filterClass       && t.booking_class  !== filterClass)       return false;
    return true;
  });
  const totalPages = Math.ceil(filtered.length / pageSize);
  const pageTickets = filtered.slice((page - 1) * pageSize, page * pageSize);

  // ── Selection helpers ──────────────────────────────────────────────────
  const toggleRow = (id: number) => setSelected(prev => {
    const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next;
  });
  const pageIds = pageTickets.map(t => t.id);
  const allPageSelected = pageIds.length > 0 && pageIds.every(id => selected.has(id));
  const somePageSelected = pageIds.some(id => selected.has(id));
  const togglePage = () => {
    setSelected(prev => {
      const next = new Set(prev);
      if (allPageSelected) pageIds.forEach(id => next.delete(id));
      else pageIds.forEach(id => next.add(id));
      return next;
    });
  };

  // ── Run single calculation ─────────────────────────────────────────────
  const runCalc = async (t: UploadedTicket) => {
    setCalcLoading(prev => new Set(prev).add(t.id));
    try {
      const { data } = await api.patch<RunCalcResult>(`/tickets/uploads/${t.id}/run-calculation`);
      setTickets(prev => prev.map(x => x.id !== t.id ? x : {
        ...x,
        matched_deal_id:      data.matched_deal_id,
        matched_deal_type:    data.matched_deal_type,
        matched_deal_name:    data.matched_deal_name,
        calculated_incentive: data.calculated_incentive,
        incentive_breakdown:  data.incentive_breakdown ?? null,
        ticket_status: data.cancelled ? "cancelled" : data.excluded ? "excluded" : data.included ? "included" : "calculated",
        exclusion_reason: data.excluded ? (data.message || null) : null,
      }));
    } catch { /* silent */ } finally {
      setCalcLoading(prev => { const n = new Set(prev); n.delete(t.id); return n; });
    }
  };

  // ── Batch run calculation ──────────────────────────────────────────────
  const runBatch = async () => {
    setBatchCalcing(true);
    setBatchResult(null);
    try {
      const ids = selected.size > 0 ? [...selected] : undefined;
      let res: BatchRunCalcResult;
      if (ids) {
        // Process in chunks of 10 to avoid overwhelming the server
        let matched = 0, unmatched = 0, errors = 0, excluded = 0, cancelled = 0;
        const results = new Map<number, RunCalcResult>();
        const CHUNK = 10;
        for (let i = 0; i < ids.length; i += CHUNK) {
          await Promise.all(ids.slice(i, i + CHUNK).map(async id => {
            try {
              const r = await api.patch<RunCalcResult>(`/tickets/uploads/${id}/run-calculation`);
              results.set(id, r.data);
              if (r.data.cancelled) cancelled++;
              else if (r.data.excluded) excluded++;
              else if (r.data.matched) matched++;
              else unmatched++;
            } catch { errors++; }
          }));
        }
        // Apply API response directly — no refreshData() here so we never overwrite correct state
        setTickets(prev => prev.map(t => {
          const r = results.get(t.id);
          if (!r) return t;
          return {
            ...t,
            matched_deal_id:      r.matched_deal_id,
            matched_deal_type:    r.matched_deal_type,
            matched_deal_name:    r.matched_deal_name,
            calculated_incentive: r.calculated_incentive,
            incentive_breakdown:  r.incentive_breakdown ?? null,
            ticket_status:        r.cancelled ? "cancelled" : r.excluded ? "excluded" : "calculated",
            exclusion_reason:     r.excluded ? (r.message || null) : null,
          };
        }));
        res = { processed: ids.length, matched, unmatched, errors, excluded, cancelled };
      } else {
        // True "Run All" — server processes every ticket; re-fetch is the only way to get statuses
        const { data } = await api.patch<BatchRunCalcResult>("/tickets/uploads/run-all-calculation", null, {
          params: { batch_id: batchId },
        });
        res = data;
        // Await so no background request races with other local state updates
        await refreshData();
      }
      setBatchResult(res);
    } catch { /* silent */ } finally {
      setBatchCalcing(false);
    }
  };

  // ── Edit handlers ──────────────────────────────────────────────────────
  const openEdit = (t: UploadedTicket) => { setEditTicket(t); setEditDraft({ ...t }); };
  const saveEdit = async () => {
    if (!editTicket) return;
    setSaving(true);
    try {
      const { data } = await api.patch<UploadedTicket>(`/tickets/uploads/${editTicket.id}`, editDraft);
      setTickets(prev => prev.map(x => x.id === editTicket.id ? data : x));
      setEditTicket(null);
    } catch { /* silent */ } finally { setSaving(false); }
  };

  // ── Delete handlers ────────────────────────────────────────────────────
  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/tickets/uploads/${deleteTarget.id}`);
      setTickets(prev => prev.filter(x => x.id !== deleteTarget.id));
      setDeleteTarget(null);
      if (statement) setStatement({ ...statement, ticket_count: Math.max(0, statement.ticket_count - 1) });
    } catch { /* silent */ } finally { setDeleting(false); }
  };

  // ── Matched deals ──────────────────────────────────────────────────────
  const openMatchedDeals = async (t: UploadedTicket) => {
    setMatchedDeals([]);
    setDealsLoading(true);
    try {
      const { data } = await api.get<DealMatchSummary[]>(`/tickets/uploads/${t.id}/matched-deals`);
      setMatchedDeals(data);
    } catch { setMatchedDeals([]); } finally { setDealsLoading(false); }
  };

  // ── Diagnosis ──────────────────────────────────────────────────────────
  const openDiagnosis = async (t: UploadedTicket) => {
    setDiagnosis(null);
    setDiagTicket(t);
    setDiagTab("matched");
    setDiagLoading(true);
    setExpandedDeals(new Set());
    setRawPLBVisible(new Set());
    try {
      const { data } = await api.get<MatchDiagnosis>(`/tickets/uploads/${t.id}/match-diagnosis`);
      setDiagnosis(data);
    } catch { /* silent */ } finally { setDiagLoading(false); }
  };

  const closeDiagnosis = () => {
    setDiagnosis(null);
    setDiagLoading(false);
    setDiagTicket(null);
  };

  const markAsReviewed = async () => {
    if (!diagTicket) return;
    const id = diagTicket.id; // capture before closing clears diagTicket
    try {
      const { data } = await api.patch<UploadedTicket>(`/tickets/uploads/${id}`, { ticket_status: "reviewed" });
      setTickets(prev => prev.map(t => t.id === id ? data : t));
      closeDiagnosis();
    } catch { /* silent */ }
  };

  // ── Diagnosis helpers ─────────────────────────────────────────────────
  const bestDealId = diagnosis
    ? (diagnosis.deals.filter(d => d.overall_match && d.best_incentive != null)
        .sort((a, b) => (b.best_incentive ?? 0) - (a.best_incentive ?? 0))[0]?.deal_id ?? null)
    : null;

  // ── Stats (derived from fetched tickets) ──────────────────────────────
  const statTotalTickets  = tickets.length;
  const statBatches       = new Set(tickets.map(t => t.ticket_date).filter(Boolean)).size;
  const statTotalSellFare = tickets.reduce((s, t) => s + (t.sell_fare ?? 0), 0);
  const statNetAmt        = tickets.reduce((s, t) => s + (t.net_amt   ?? 0), 0);

  // ── Income summary preview (client-side; backend recomputes authoritatively) ──
  const anyCalculated = tickets.some(t => t.calculated_incentive != null);
  const summaryTotals = INCENTIVE_TYPE_COLS.map(({ key, label }) => ({
    key, label,
    value: tickets.reduce((s, t) => s + (t.incentive_breakdown?.[key] ?? 0), 0),
  }));
  const summaryGrandTotal = tickets.reduce((s, t) => s + (t.calculated_incentive ?? 0), 0);

  const saveIncomeSummary = async () => {
    setSavingSummary(true);
    setSaveSummaryError(null);
    try {
      await api.post(`/tickets/statements/${batchId}/income-summary`, { name: summaryName.trim() || null });
      setSaveSummaryDone(true);
      setTimeout(() => setShowSaveSummary(false), 900);
    } catch {
      setSaveSummaryError("Failed to save income summary.");
    } finally {
      setSavingSummary(false);
    }
  };

  // ── Loading / error states ─────────────────────────────────────────────
  if (loading) return (
    <div className="flex items-center justify-center py-24">
      <RefreshCw className="w-7 h-7 text-blue-400 animate-spin" />
    </div>
  );

  if (error || !statement) return (
    <div className="space-y-4">
      <Link href="/tickets" className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-800">
        <ChevronLeft className="w-4 h-4" /> Back to Repository
      </Link>
      <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
        <AlertCircle className="w-4 h-4 shrink-0" /> {error ?? "Statement not found."}
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {/* breadcrumb + back */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/tickets" className="flex items-center gap-1.5 hover:text-gray-800 transition-colors">
          <ChevronLeft className="w-4 h-4" /> Ticket Repository
        </Link>
        <ChevronRight className="w-3.5 h-3.5 text-gray-300" />
        <span className="text-gray-700 font-medium truncate max-w-xs">
          {statement.statement_name ?? `${statement.statement_type} · ${statement.agency}`}
        </span>
      </div>

      {/* Statement metadata card */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 flex items-start justify-between gap-4 flex-wrap" style={{background:"#1e3a5f"}}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center">
              <FileSpreadsheet className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-white">
                  {statement.statement_name ?? `${statement.statement_type} · ${statement.agency}`}
                </h1>
                <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                  (statement.statement_type ?? "B2B") === "AIRLINE"
                    ? "bg-blue-400/30 text-blue-100"
                    : "bg-purple-400/30 text-purple-100"
                }`}>
                  {statement.statement_type ?? "B2B"}
                </span>
              </div>
              <p className="text-xs text-white/60 mt-0.5 font-mono">{statement.batch_id}</p>
            </div>
          </div>
          <div className="flex items-center gap-6 flex-wrap">
            <div className="text-center">
              <p className="text-[11px] text-white/50 uppercase tracking-wide mb-0.5">Agency</p>
              <span className="flex items-center gap-1.5 text-sm font-semibold text-white">
                <Building2 className="w-4 h-4 text-white/70" /> {statement.agency}
              </span>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-white/50 uppercase tracking-wide mb-0.5">Valid Period</p>
              <span className="flex items-center gap-1.5 text-sm font-semibold text-white">
                <Calendar className="w-4 h-4 text-white/70" />
                {formatDate(statement.valid_from)} – {formatDate(statement.valid_to)}
              </span>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-white/50 uppercase tracking-wide mb-0.5">Tickets</p>
              <span className="flex items-center gap-1.5 text-sm font-semibold text-white">
                <Hash className="w-4 h-4 text-white/70" /> {statement.ticket_count.toLocaleString()}
              </span>
            </div>
            <div className="text-center">
              <p className="text-[11px] text-white/50 uppercase tracking-wide mb-0.5">File</p>
              {statement.file_url ? (
                <button
                  onClick={async () => {
                    try {
                      const { data } = await api.get<{ url: string; file_type: string }>(`/tickets/statements/${statement.batch_id}/file-url`);
                      window.open(`https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`, "_blank");
                    } catch { /* silent */ }
                  }}
                  className="text-sm font-semibold text-white truncate max-w-40 block hover:underline text-left"
                  title={statement.file_name}
                >
                  {statement.file_name}
                </button>
              ) : (
                <span className="text-sm font-semibold text-white truncate max-w-40 block">{statement.file_name}</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Stats cards ──────────────────────────────────────────────────── */}
      {tickets.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: "Total Tickets",   value: statTotalTickets.toLocaleString(),                                                                     icon: Hash,        color: "text-blue-600",   bg: "bg-blue-50"   },
            { label: "Batches",         value: statBatches.toString(),                                                                                icon: FileSpreadsheet, color: "text-indigo-600", bg: "bg-indigo-50" },
            { label: "Total Sell Fare", value: `₹ ${statTotalSellFare.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, icon: TrendingUp,  color: "text-emerald-600", bg: "bg-emerald-50" },
            { label: "Net Amount",      value: `₹ ${statNetAmt.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,       icon: TrendingUp,  color: "text-amber-600",  bg: "bg-amber-50"  },
          ].map(({ label, value, icon: Icon, color, bg }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-200 px-5 py-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-lg ${bg} flex items-center justify-center shrink-0`}>
                <Icon className={`w-5 h-5 ${color}`} />
              </div>
              <div>
                <p className="text-[11px] text-gray-400 uppercase tracking-wide font-semibold">{label}</p>
                <p className="text-sm font-bold text-gray-900 mt-0.5">{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            type="text" placeholder="Search tickets…"
            value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-52"
          />
        </div>
        <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPage(1); }}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        <span className="text-xs text-gray-400">to</span>
        <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPage(1); }}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        {(search || dateFrom || dateTo || filterAirlineCode || filterAirline || filterSegment || filterInvType || filterClass) && (
          <button
            onClick={() => { setSearch(""); setDateFrom(""); setDateTo(""); setFilterAirlineCode(""); setFilterAirline(""); setFilterSegment(""); setFilterInvType(""); setFilterClass(""); setPage(1); }}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-red-500 hover:bg-red-50 border border-red-200 rounded-lg"
          >
            <X className="w-3 h-3" /> Clear All
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <select
            value={pageSize}
            onChange={e => { setPageSize(Number(e.target.value) as 25|50|100); setPage(1); }}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white text-gray-600"
          >
            {PAGE_SIZE_OPTIONS.map(n => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
          {selected.size > 0 && (
            <span className="text-xs text-gray-500">{selected.size} selected</span>
          )}
          <button
            onClick={runBatch}
            disabled={batchCalcing}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-60"
          >
            {batchCalcing
              ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Running…</>
              : <><Calculator className="w-3.5 h-3.5" /> {selected.size > 0 ? `Run (${selected.size})` : "Run All"}</>}
          </button>
          <button
            onClick={() => { setSummaryName(statement?.statement_name ?? ""); setSaveSummaryDone(false); setSaveSummaryError(null); setShowSaveSummary(true); }}
            disabled={!anyCalculated}
            title={anyCalculated ? "Save income summary for this statement" : "Run the calculation first"}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-700 disabled:opacity-50"
          >
            <TrendingUp className="w-3.5 h-3.5" /> Save Income Summary
          </button>
        </div>
      </div>

      {/* ── Filter bar ───────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Airline Code */}
        <select
          value={filterAirlineCode}
          onChange={e => { setFilterAirlineCode(e.target.value); setPage(1); }}
          className={`py-1.5 px-2.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${filterAirlineCode ? "border-blue-400 ring-1 ring-blue-400" : "border-gray-200"}`}
        >
          <option value="">All Airline Codes</option>
          {filterOptions.airlineCodes.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        {/* Airline */}
        <select
          value={filterAirline}
          onChange={e => { setFilterAirline(e.target.value); setPage(1); }}
          className={`py-1.5 px-2.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${filterAirline ? "border-blue-400 ring-1 ring-blue-400" : "border-gray-200"}`}
        >
          <option value="">All Airlines</option>
          {filterOptions.airlines.map(a => <option key={a} value={a}>{a}</option>)}
        </select>

        {/* Segment */}
        {filterOptions.segments.length > 0 && (
          <select
            value={filterSegment}
            onChange={e => { setFilterSegment(e.target.value); setPage(1); }}
            className={`py-1.5 px-2.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${filterSegment ? "border-blue-400 ring-1 ring-blue-400" : "border-gray-200"}`}
          >
            <option value="">All Segments</option>
            {filterOptions.segments.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}

        {/* Inv. Type */}
        {filterOptions.invTypes.length > 0 && (
          <select
            value={filterInvType}
            onChange={e => { setFilterInvType(e.target.value); setPage(1); }}
            className={`py-1.5 px-2.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${filterInvType ? "border-blue-400 ring-1 ring-blue-400" : "border-gray-200"}`}
          >
            <option value="">All Inv. Types</option>
            {filterOptions.invTypes.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        )}

        {/* Class */}
        {filterOptions.classes.length > 0 && (
          <select
            value={filterClass}
            onChange={e => { setFilterClass(e.target.value); setPage(1); }}
            className={`py-1.5 px-2.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${filterClass ? "border-blue-400 ring-1 ring-blue-400" : "border-gray-200"}`}
          >
            <option value="">All Classes</option>
            {filterOptions.classes.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
      </div>

      {/* batch result */}
      {batchResult && (
        <div className="flex items-center gap-4 px-4 py-3 bg-blue-50 border border-blue-200 rounded-xl text-xs">
          <span className="font-semibold text-blue-700">Batch complete:</span>
          <span className="text-gray-600">Processed <b>{batchResult.processed}</b></span>
          <span className="text-emerald-600">Matched <b>{batchResult.matched}</b></span>
          <span className="text-amber-600">Unmatched <b>{batchResult.unmatched}</b></span>
          {(batchResult.excluded ?? 0) > 0 && <span className="text-red-600">Excluded <b>{batchResult.excluded}</b></span>}
          {batchResult.errors > 0 && <span className="text-red-600">Errors <b>{batchResult.errors}</b></span>}
          <button onClick={() => setBatchResult(null)} className="ml-auto"><X className="w-3.5 h-3.5 text-blue-400" /></button>
        </div>
      )}

      {/* ── Ticket table ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
            {filtered.length} Ticket{filtered.length !== 1 ? "s" : ""}
          </p>
          {filtered.length !== tickets.length && (
            <span className="text-xs text-gray-400">(filtered from {tickets.length})</span>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-max border-collapse">
            <thead>
              <tr>
                {/* sticky select + actions */}
                <th className="px-2 py-2.5 sticky left-0 z-20" style={{background:"#1e3a5f"}}>
                  <input type="checkbox" checked={allPageSelected}
                    ref={el => { if (el) el.indeterminate = !allPageSelected && somePageSelected; }}
                    onChange={togglePage}
                    className="accent-blue-400 cursor-pointer" />
                </th>
                <th colSpan={TEXT_HEADERS.length} className="px-3 py-2.5 text-[10px] font-bold text-white uppercase tracking-wider text-left border-l border-white/20" style={{background:"#1e3a5f"}}>
                  Ticket Info
                </th>
                <th colSpan={NUM_HEADERS.length} className="px-3 py-2.5 text-[10px] font-bold text-white uppercase tracking-wider text-left border-l border-white/20" style={{background:"#334d6e"}}>
                  Financial
                </th>
                <th colSpan={EXTRA_TEXT_HEADERS.length + INCENTIVE_TYPE_COLS.length + 5} className="px-3 py-2.5 text-[10px] font-bold text-white uppercase tracking-wider text-left border-l border-white/20 whitespace-nowrap" style={{background:"#1e3a5f"}}>
                  Additional
                </th>
                {statement.statement_type === "AIRLINE" && (
                  <th colSpan={AIRLINE_TEXT_HEADERS.length + AIRLINE_NUM_HEADERS.length + 1} className="px-3 py-2.5 text-[10px] font-bold text-white uppercase tracking-wider text-left border-l border-white/20 whitespace-nowrap" style={{background:"#1a4070"}}>
                    BSP / Airline
                  </th>
                )}
                <th className="px-3 py-2.5 sticky right-0 z-20" style={{background:"#1e3a5f"}} />
              </tr>
              <tr style={{background:"#2d4f7c"}}>
                <th className="px-2 py-2 sticky left-0 z-20" style={{background:"#2d4f7c"}} />
                {TEXT_HEADERS.map(h => (
                  <th key={h.key} className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{h.label}</th>
                ))}
                {NUM_HEADERS.map(h => (
                  <th key={h.key} className="px-2.5 py-2 text-right text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{h.label}</th>
                ))}
                {EXTRA_TEXT_HEADERS.map(h => (
                  <th key={h.key} className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{h.label}</th>
                ))}
                {INCENTIVE_TYPE_COLS.map(col => (
                  <th key={col.key} className="px-2.5 py-2 text-right text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{col.label}</th>
                ))}
                <th className="px-2.5 py-2 text-right text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Delta Comm</th>
                <th className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Status</th>
                <th className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Type</th>
                <th className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Matched Deal</th>
                <th className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Uploaded At</th>
                {statement.statement_type === "AIRLINE" && (<>
                  {AIRLINE_TEXT_HEADERS.map(h => (
                    <th key={h.key} className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{h.label}</th>
                  ))}
                  {AIRLINE_NUM_HEADERS.map(h => (
                    <th key={h.key} className="px-2.5 py-2 text-right text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{h.label}</th>
                  ))}
                  <th className="px-2.5 py-2 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">Tax Breakup</th>
                </>)}
                <th className="px-2 py-2 sticky right-0 z-20" style={{background:"#2d4f7c"}} />
              </tr>
            </thead>
            <tbody>
              {pageTickets.length === 0 ? (
                <tr>
                  <td colSpan={99} className="px-4 py-12 text-center text-xs text-gray-400">
                    {tickets.length === 0 ? "No tickets in this statement." : "No tickets match the filter."}
                  </td>
                </tr>
              ) : pageTickets.map(t => {
                const isCalcing = calcLoading.has(t.id);
                const isSel = selected.has(t.id);
                return (
                  <tr key={t.id} className={`border-b border-gray-100 group ${isSel ? "bg-blue-50" : "hover:bg-gray-50/60"}`}>
                    <td className={`px-2 py-2 sticky left-0 ${isSel ? "bg-blue-50" : "bg-white group-hover:bg-gray-50/60"}`}>
                      <input type="checkbox" checked={isSel} onChange={() => toggleRow(t.id)} className="accent-blue-500 cursor-pointer" />
                    </td>

                    {/* Text columns */}
                    {TEXT_HEADERS.map(h => (
                      <td key={h.key} className="px-2.5 py-2 text-xs text-gray-700 whitespace-nowrap border-l border-gray-100">
                        {String(t[h.key] ?? "—")}
                      </td>
                    ))}

                    {/* Numeric columns */}
                    {NUM_HEADERS.map(h => (
                      <td key={h.key} className="px-2.5 py-2 text-xs text-right text-gray-700 whitespace-nowrap border-l border-gray-100 font-mono">
                        {fmt(t[h.key] as number | null)}
                      </td>
                    ))}

                    {/* Extra text columns: CC, Acc Code, Sold To, Name */}
                    {EXTRA_TEXT_HEADERS.map(h => (
                      <td key={h.key} className="px-2.5 py-2 text-xs text-gray-700 whitespace-nowrap border-l border-gray-100">
                        {String(t[h.key] ?? "—")}
                      </td>
                    ))}

                    {/* Per-incentive-type columns */}
                    {INCENTIVE_TYPE_COLS.map(col => {
                      const val = t.incentive_breakdown?.[col.key] ?? null;
                      return (
                        <td key={col.key} className="px-2.5 py-2 text-xs text-right font-mono whitespace-nowrap border-l border-gray-100">
                          {val != null
                            ? <span className="text-amber-600 font-semibold">₹{val.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                            : <span className="text-gray-300">—</span>}
                        </td>
                      );
                    })}

                    {/* Delta Comm = comm_sell - calculated_incentive */}
                    <td className="px-2.5 py-2 text-xs text-right font-mono whitespace-nowrap border-l border-gray-100">
                      {(() => {
                        const delta = (t.comm_sell ?? 0) - (t.calculated_incentive ?? 0);
                        if (t.calculated_incentive == null) return <span className="text-gray-300">—</span>;
                        return <span className={delta >= 0 ? "text-orange-500 font-semibold" : "text-red-600 font-semibold"}>
                          {delta >= 0 ? "+" : ""}₹{delta.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </span>;
                      })()}
                    </td>

                    {/* Status */}
                    <td className="px-2.5 py-2 border-l border-gray-100 whitespace-nowrap">
                      {(() => {
                        const { style, label } = getStatusDisplay(t.ticket_status, t.exclusion_reason);
                        return (
                          <span
                            className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold ${style}`}
                            title={t.exclusion_reason ?? undefined}
                          >
                            {label}
                          </span>
                        );
                      })()}
                    </td>

                    {/* Split Type */}
                    <td className="px-2.5 py-2 border-l border-gray-100 whitespace-nowrap">
                      {t.split_type === "split"
                        ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-600 border border-amber-200">Split</span>
                        : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-500">Normal</span>}
                    </td>

                    {/* Matched Deal */}
                    <td className="px-2.5 py-2 border-l border-gray-100 whitespace-nowrap">
                      {t.matched_deal_name ? (
                        <button onClick={() => openMatchedDeals(t)}>
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            t.matched_deal_type === "b2b"
                              ? "bg-violet-50 text-violet-600 hover:bg-violet-100"
                              : "bg-sky-50 text-sky-600 hover:bg-sky-100"
                          }`}>
                            <CheckCircle2 className="w-2.5 h-2.5" />
                            {t.matched_deal_type?.toUpperCase()} · {t.matched_deal_name}
                          </span>
                        </button>
                      ) : <span className="text-gray-300 text-xs">—</span>}
                    </td>

                    {/* Uploaded At */}
                    <td className="px-2.5 py-2 text-xs text-gray-500 whitespace-nowrap border-l border-gray-100">
                      {formatDate(t.created_at)}
                    </td>

                    {/* Airline-specific columns */}
                    {statement.statement_type === "AIRLINE" && (<>
                      {AIRLINE_TEXT_HEADERS.map(h => (
                        <td key={h.key} className="px-2.5 py-2 text-xs text-gray-700 whitespace-nowrap border-l border-gray-100">
                          {String(t[h.key] ?? "—")}
                        </td>
                      ))}
                      {AIRLINE_NUM_HEADERS.map(h => (
                        <td key={h.key} className="px-2.5 py-2 text-xs text-right text-gray-700 whitespace-nowrap border-l border-gray-100 font-mono">
                          {fmt(t[h.key] as number | null)}
                        </td>
                      ))}
                      {/* Tax Breakup */}
                      <td className="px-2.5 py-2 border-l border-gray-100 min-w-[160px]">
                        {t.tax_breakup && Object.keys(t.tax_breakup).length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(t.tax_breakup).map(([k, v]) => (
                              <span key={k} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px] font-mono whitespace-nowrap">
                                {k}:<b>{v.toLocaleString("en-IN")}</b>
                              </span>
                            ))}
                          </div>
                        ) : <span className="text-gray-300 text-xs">—</span>}
                      </td>
                    </>)}

                    {/* Actions */}
                    <td className={`px-2 py-2 sticky right-0 ${isSel ? "bg-blue-50" : "bg-white group-hover:bg-gray-50/60"}`}>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => runCalc(t)}
                          disabled={isCalcing}
                          className="flex items-center gap-1 px-2 py-1 rounded border border-[#1e3a5f] text-[#1e3a5f] text-[10px] font-semibold hover:bg-[#1e3a5f] hover:text-white disabled:opacity-40 transition-colors"
                        >
                          {isCalcing ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Calculator className="w-3 h-3" />}
                          Run
                        </button>
                        <button
                          onClick={() => openDiagnosis(t)}
                          className="p-1.5 rounded border border-violet-300 text-violet-600 hover:bg-violet-600 hover:text-white transition-colors"
                          title="Diagnose"
                        >
                          <FileSearch className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => openEdit(t)}
                          className="p-1.5 rounded border border-blue-300 text-blue-600 hover:bg-blue-600 hover:text-white transition-colors"
                          title="Edit"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(t)}
                          className="p-1.5 rounded border border-red-300 text-red-500 hover:bg-red-500 hover:text-white transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* pagination — always visible when there are tickets */}
        {filtered.length > 0 && (
          <Pagination page={page} pageSize={pageSize} total={filtered.length} onPageChange={setPage} />
        )}
      </div>

      {/* ── Edit Modal ───────────────────────────────────────────────────── */}
      {editTicket && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">Edit Ticket #{editTicket.ticket_number ?? editTicket.id}</h2>
              <button onClick={() => setEditTicket(null)} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
            </div>
            <div className="overflow-y-auto flex-1 px-6 py-4 space-y-6">
              {EDIT_GROUPS.map(group => (
                <div key={group.label}>
                  <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-3">{group.label}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {group.keys.map(k => {
                      const f = EDITABLE_FIELDS.find(ef => ef.key === k);
                      if (!f) return null;
                      const val = editDraft[f.key as keyof UploadedTicket];
                      return (
                        <div key={f.key}>
                          <label className="block text-[10px] font-semibold text-gray-500 mb-1">{f.label}</label>
                          {f.type === "select" ? (
                            <select
                              value={val == null ? "" : String(val)}
                              onChange={e => setEditDraft(prev => ({ ...prev, [f.key]: e.target.value || null }))}
                              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                            >
                              <option value="">— select —</option>
                              {f.options?.map(o => <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>)}
                            </select>
                          ) : (
                            <input
                              type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
                              value={val == null ? "" : String(val)}
                              onChange={e => setEditDraft(prev => ({
                                ...prev,
                                [f.key]: f.type === "number"
                                  ? (e.target.value === "" ? null : parseFloat(e.target.value))
                                  : (e.target.value || null),
                              }))}
                              onClick={f.type === "date" ? e => { try { (e.target as HTMLInputElement).showPicker(); } catch {} } : undefined}
                              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-2">
              <button onClick={() => setEditTicket(null)} className="px-4 py-2 border border-gray-200 text-xs rounded-lg text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={saveEdit}
                disabled={saving}
                className="flex items-center gap-1.5 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-60"
              >
                {saving ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Saving…</> : <><Save className="w-3.5 h-3.5" /> Save Changes</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Save Income Summary Modal ────────────────────────────────────── */}
      {showSaveSummary && statement && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">Save Income Summary</h2>
              <button onClick={() => setShowSaveSummary(false)} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
            </div>

            {/* Body */}
            <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
              {/* Statement metadata */}
              <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-xs">
                <div><p className="text-gray-400">Statement</p><p className="font-medium text-gray-800">{statement.statement_name ?? `${statement.statement_type ?? "B2B"} · ${statement.agency}`}</p></div>
                <div><p className="text-gray-400">Agency</p><p className="font-medium text-gray-800">{statement.agency}</p></div>
                <div><p className="text-gray-400">Valid Period</p><p className="font-medium text-gray-800">{formatDate(statement.valid_from)} → {formatDate(statement.valid_to)}</p></div>
                <div><p className="text-gray-400">Tickets</p><p className="font-medium text-gray-800">{statement.ticket_count.toLocaleString()}</p></div>
              </div>

              {/* Editable name */}
              <div>
                <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Income Summary Name</label>
                <input
                  value={summaryName}
                  onChange={e => setSummaryName(e.target.value)}
                  placeholder={statement.statement_name ?? "Income summary name"}
                  className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>

              {/* Incentive totals preview */}
              <div className="border border-gray-100 rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <tbody className="divide-y divide-gray-100">
                    {summaryTotals.map(r => (
                      <tr key={r.key}>
                        <td className="px-3 py-1.5 text-gray-600">{r.label}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-gray-700">
                          {r.value ? `₹${r.value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : <span className="text-gray-300">—</span>}
                        </td>
                      </tr>
                    ))}
                    <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold">
                      <td className="px-3 py-2 text-gray-900">Total Income</td>
                      <td className="px-3 py-2 text-right font-mono text-emerald-700">
                        ₹{summaryGrandTotal.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {saveSummaryError && <p className="text-xs text-red-600">{saveSummaryError}</p>}
              {saveSummaryDone && <p className="text-xs text-emerald-600">Income summary saved.</p>}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-2">
              <button onClick={() => setShowSaveSummary(false)} className="px-4 py-2 border border-gray-200 text-xs rounded-lg text-gray-600 hover:bg-gray-50">Close</button>
              <button
                onClick={saveIncomeSummary}
                disabled={savingSummary}
                className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-700 disabled:opacity-60"
              >
                {savingSummary ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Saving…</> : <><Save className="w-3.5 h-3.5" /> Confirm &amp; Save</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Modal ─────────────────────────────────────────────────── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 text-center space-y-4">
            <div className="w-12 h-12 bg-red-50 rounded-full flex items-center justify-center mx-auto">
              <AlertTriangle className="w-6 h-6 text-red-500" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">Delete Ticket?</h2>
              <p className="text-xs text-gray-500 mt-1">
                Ticket <b>{deleteTarget.ticket_number ?? deleteTarget.id}</b> will be permanently removed.
              </p>
            </div>
            <div className="flex gap-3">
              <button onClick={() => setDeleteTarget(null)} className="flex-1 px-4 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 bg-red-600 text-white rounded-lg text-xs font-semibold hover:bg-red-700 disabled:opacity-60"
              >
                {deleting ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Deleting…</> : <><Trash2 className="w-3.5 h-3.5" /> Delete</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Matched Deals Modal ───────────────────────────────────────────── */}
      {matchedDeals !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">All Matching Deals</h2>
              <button onClick={() => setMatchedDeals(null)} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
            </div>
            <div className="overflow-y-auto flex-1 px-6 py-4">
              {dealsLoading ? (
                <div className="flex justify-center py-8"><RefreshCw className="w-5 h-5 text-blue-400 animate-spin" /></div>
              ) : matchedDeals.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-8">No matching deals found.</p>
              ) : (
                <div className="space-y-2">
                  {matchedDeals.map(d => (
                    <div key={d.deal_id} className={`border rounded-xl px-4 py-3 ${d.is_best ? "border-emerald-300 bg-emerald-50" : "border-gray-200"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-xs font-semibold text-gray-800">{d.deal_name}</p>
                          <p className="text-[11px] text-gray-500 mt-0.5">{d.deal_no} · {d.deal_type?.toUpperCase()}</p>
                          {(d.valid_from || d.valid_to) && (
                            <p className="text-[11px] text-gray-400 mt-0.5">{d.valid_from} – {d.valid_to}</p>
                          )}
                        </div>
                        <div className="text-right shrink-0">
                          {d.is_best && <span className="text-[10px] font-bold text-emerald-600 bg-emerald-100 px-2 py-0.5 rounded-full block mb-1">Best Match</span>}
                          {d.calculated_incentive != null && (
                            <p className="text-sm font-bold text-emerald-700">₹{d.calculated_incentive.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Match Diagnosis Modal ─────────────────────────────────────────── */}
      {(diagLoading || diagnosis) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">

            {/* Header */}
            <div className="px-6 pt-5 pb-0">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <FileSearch className="w-4 h-4 text-[#1e3a5f]" />
                    <h2 className="text-sm font-bold text-gray-900">Match Diagnosis</h2>
                  </div>
                  {diagnosis && diagTicket && (
                    <p className="text-xs text-gray-500 mt-1 pl-6">
                      Ticket {diagTicket.ticket_number}
                      <span className="mx-1.5 text-gray-300">·</span>
                      {diagnosis.total_deals_checked} deals checked
                      <span className="mx-1.5 text-gray-300">·</span>
                      <span className="text-emerald-600 font-semibold">{diagnosis.matched_count} matched</span>
                    </p>
                  )}
                </div>
                <button onClick={closeDiagnosis} className="p-1 hover:bg-gray-100 rounded-lg">
                  <X className="w-4 h-4 text-gray-500" />
                </button>
              </div>
              {/* Tabs — pill style */}
              {diagnosis && (
                <div className="flex gap-2 mb-4">
                  {(["all", "matched", "not_matched"] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => setDiagTab(tab)}
                      className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                        diagTab === tab
                          ? "bg-violet-600 text-white"
                          : "border border-gray-300 text-gray-600 hover:border-gray-400"
                      }`}
                    >
                      {tab === "all"         && `All (${diagnosis.total_deals_checked})`}
                      {tab === "matched"     && `Matched (${diagnosis.matched_count})`}
                      {tab === "not_matched" && `Not Matched (${diagnosis.total_deals_checked - diagnosis.matched_count})`}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Content */}
            <div className="overflow-y-auto flex-1 px-6 pb-4">
              {diagLoading ? (
                <div className="flex justify-center py-12"><RefreshCw className="w-6 h-6 text-blue-400 animate-spin" /></div>
              ) : diagnosis && (
                <div className="space-y-3 text-xs">

                  {/* ── Ticket Trace ── */}
                  <div className="border border-gray-200 rounded-xl overflow-hidden">
                    <p className="px-4 py-2.5 text-[10px] font-bold text-violet-600 uppercase tracking-widest bg-gray-50 border-b border-gray-100">Ticket Trace</p>
                    <div className="px-4 py-3">
                      {/* Airline group */}
                      {[
                        { label: "Airline Code (raw)", value: diagnosis.raw_airline_code,            green: false },
                        { label: "Normalized codes",   value: diagnosis.normalized_codes.join(", "), green: false },
                        { label: "Airline resolved",   value: diagnosis.airline_resolved ?? "Not found", green: !!diagnosis.airline_resolved },
                      ].map(r => (
                        <div key={r.label} className="flex items-baseline justify-between py-1.5 gap-4">
                          <span className="text-gray-500 shrink-0">{r.label}</span>
                          <span className={`font-semibold text-right ${r.green ? "text-emerald-600" : "text-gray-800"}`}>{r.value}</span>
                        </div>
                      ))}
                      {diagnosis.airline_resolution_detail && <p className="text-[10px] text-gray-400 italic pb-2 leading-relaxed">{diagnosis.airline_resolution_detail}</p>}
                      <div className="border-t border-gray-100 my-1.5" />

                      {/* Date group */}
                      {[
                        { label: "Departure Date",       value: diagnosis.raw_departure ?? "—",      green: !!diagnosis.raw_departure },
                        { label: "Ticket Date",          value: diagnosis.raw_ticket_date ?? "—",    green: false },
                        { label: "Travel date (used)",   value: diagnosis.travel_date ?? "—",         green: !!diagnosis.travel_date },
                      ].map(r => (
                        <div key={r.label} className="flex items-baseline justify-between py-1.5 gap-4">
                          <span className="text-gray-500 shrink-0">{r.label}</span>
                          <span className={`font-semibold text-right ${r.green ? "text-emerald-600" : "text-gray-800"}`}>{r.value}</span>
                        </div>
                      ))}
                      {diagnosis.travel_date_detail && <p className="text-[10px] text-gray-400 italic pb-2 leading-relaxed">{diagnosis.travel_date_detail}</p>}
                      <div className="border-t border-gray-100 my-1.5" />

                      {/* Type + financial group */}
                      {[
                        { label: "Segment Type",         value: diagnosis.segment_type ?? "—" },
                        { label: "Invoice Type",          value: diagnosis.invoice_type ?? "—" },
                        { label: "Booking Class",         value: diagnosis.booking_class ?? "—" },
                        { label: "Cabin groups resolved", value: diagnosis.cabin_groups_resolved.join(", ") || "—" },
                        { label: "Sell Fare",             value: `₹ ${(diagnosis.sell_fare ?? 0).toLocaleString("en-IN")}` },
                        { label: "Sell Tax YQ",           value: `₹ ${(diagnosis.sell_tax_yq ?? 0).toLocaleString("en-IN")}` },
                        { label: "Sale YR",               value: `₹ ${(diagnosis.sale_yr ?? 0).toLocaleString("en-IN")}` },
                      ].map(r => (
                        <div key={r.label} className="flex items-baseline justify-between py-1.5 gap-4">
                          <span className="text-gray-500 shrink-0">{r.label}</span>
                          <span className="font-semibold text-gray-800 text-right">{r.value}</span>
                        </div>
                      ))}
                      {diagnosis.cabin_resolution_detail && <p className="text-[10px] text-gray-400 italic pt-0.5 leading-relaxed">{diagnosis.cabin_resolution_detail}</p>}
                    </div>
                  </div>

                  {/* ── Deal list ── */}
                  {diagnosis.deals
                    .filter(d => diagTab === "all" || (diagTab === "matched" ? d.overall_match : !d.overall_match))
                    .map(d => {
                      const isExpanded = expandedDeals.has(d.deal_id);
                      const isBest = d.deal_id === bestDealId;
                      return (
                        <div key={d.deal_id} className={`border rounded-xl overflow-hidden ${d.overall_match ? "border-emerald-200" : "border-red-100"}`}>
                          {/* Collapsed row */}
                          <button
                            onClick={() => setExpandedDeals(prev => { const n = new Set(prev); n.has(d.deal_id) ? n.delete(d.deal_id) : n.add(d.deal_id); return n; })}
                            className="w-full flex items-center gap-2 px-3 py-3 text-left"
                          >
                            <span className={`font-bold text-sm shrink-0 ${d.overall_match ? "text-emerald-500" : "text-red-500"}`}>{d.overall_match ? "✓" : "✗"}</span>
                            {isBest ? (
                              <span className="px-2 py-0.5 rounded-full bg-amber-400 text-white text-[10px] font-bold uppercase shrink-0">BEST DEAL</span>
                            ) : d.overall_match ? (
                              <span className="px-2 py-0.5 rounded-full bg-emerald-500 text-white text-[10px] font-bold uppercase shrink-0">MATCHED</span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full bg-red-500 text-white text-[10px] font-bold uppercase shrink-0">NOT MATCHED</span>
                            )}
                            <span className="px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[11px] font-mono shrink-0">{d.deal_no}</span>
                            <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold shrink-0 ${d.deal_type === "b2b" ? "border-violet-300 text-violet-600" : "border-sky-300 text-sky-600"}`}>{d.deal_type?.toUpperCase()}</span>
                            {d.supplier_name && (
                              <span className="px-2 py-0.5 rounded bg-violet-50 text-violet-600 text-[10px] border border-violet-200 shrink-0 max-w-32 truncate" title={d.supplier_name}>{d.supplier_name}</span>
                            )}
                            <span className="text-gray-700 text-[11px] truncate flex-1 min-w-0 text-left">{d.deal_name}</span>
                            {(d.valid_from || d.valid_to) && <span className="text-[10px] text-gray-400 shrink-0">{d.valid_from} → {d.valid_to}</span>}
                            {d.deal_lifecycle_status && <span className="px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 text-[10px] font-semibold uppercase shrink-0">{d.deal_lifecycle_status}</span>}
                            {d.best_incentive != null && <span className="text-emerald-600 font-mono font-semibold text-[11px] shrink-0">₹ {d.best_incentive.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>}
                            {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
                          </button>

                          {/* Expanded body */}
                          {isExpanded && (
                            <div className="border-t border-gray-100 px-3 py-3 space-y-2">
                              {/* Deal Validity step */}
                              {(() => {
                                const s = d.deal_validity_step;
                                return (
                                  <div className={`flex items-center gap-2 px-3 py-2.5 rounded-lg ${s.passed ? "bg-emerald-50" : "bg-gray-50"}`}>
                                    <span className={`font-bold text-sm shrink-0 ${s.passed ? "text-emerald-500" : "text-red-500"}`}>{s.passed ? "✓" : "✗"}</span>
                                    <span className="font-semibold text-gray-700 flex-1 text-[11px]">{s.step}</span>
                                    {s.ticket_value && <span className="px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[11px] font-mono shrink-0">{s.ticket_value}</span>}
                                    {s.deal_value   && <><span className="text-gray-400 shrink-0">→</span><span className="px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[11px] font-mono shrink-0 max-w-40 truncate" title={s.deal_value}>{s.deal_value}</span></>}
                                    <ChevronRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                                  </div>
                                );
                              })()}

                              {/* Incentive config rows (PLB, Super PLB, Trans Fee, etc.) */}
                              {d.plbs.map(plb => {
                                const plbKey = `${d.deal_id}-${plb.plb_key}`;
                                const rawVisible = rawPLBVisible.has(plbKey);
                                const ib = plb.incentive_breakdown;
                                const isPercentage = ib ? !ib.incentive_num_pct?.toLowerCase().includes("number") : true;
                                return (
                                  <div key={plb.plb_key} className="border border-gray-100 rounded-lg overflow-hidden">
                                    {/* Header: incentive type label + status */}
                                    <div className="flex items-center px-3 py-2.5 bg-gray-50 gap-2">
                                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold shrink-0 ${plb.plb_overall_match ? "bg-emerald-100 text-emerald-700" : "bg-gray-200 text-gray-600"}`}>
                                        {plb.plb_key}
                                      </span>
                                      <span className={`text-[11px] flex-1 ${plb.plb_overall_match ? "text-emerald-600 font-semibold" : "text-gray-500"}`}>
                                        {plb.plb_overall_match
                                          ? `All filters passed${ib?.result != null ? ` → ₹${ib.result.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : ""}`
                                          : "One or more filters failed"}
                                      </span>
                                      <button
                                        onClick={() => setRawPLBVisible(prev => { const n = new Set(prev); n.has(plbKey) ? n.delete(plbKey) : n.add(plbKey); return n; })}
                                        className="text-[10px] text-blue-500 hover:text-blue-700 shrink-0"
                                      >
                                        {rawVisible ? "Hide" : "View"} raw JSON
                                      </button>
                                    </div>
                                    {rawVisible && (
                                      <pre className="px-3 py-2 bg-gray-900 text-gray-100 text-[10px] overflow-auto max-h-36 font-mono leading-relaxed">
                                        {JSON.stringify(plb.raw_plb, null, 2)}
                                      </pre>
                                    )}
                                    {/* Filter steps */}
                                    <div className="px-3 py-2 space-y-1.5">
                                      {plb.steps.map((s, si) => (
                                        <div key={si} className={`flex items-center gap-2 px-2.5 py-2 rounded-lg ${s.passed ? "bg-emerald-50" : "bg-red-50"}`}>
                                          <span className={`font-bold text-sm shrink-0 ${s.passed ? "text-emerald-500" : "text-red-500"}`}>{s.passed ? "✓" : "✗"}</span>
                                          <span className="font-semibold text-gray-700 flex-1 text-[11px]">{s.step}</span>
                                          {s.ticket_value && <span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-36 truncate" title={s.ticket_value}>{s.ticket_value}</span>}
                                          {s.deal_value   && <><span className="text-gray-400 shrink-0">→</span><span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-36 truncate" title={s.deal_value}>{s.deal_value}</span></>}
                                          <ChevronRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                                        </div>
                                      ))}

                                      {/* Incentive Calculation */}
                                      {ib && (
                                        <div className="mt-2 pt-2.5 border-t border-gray-100 space-y-1.5">
                                          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                                            Incentive Calculation{!plb.plb_overall_match ? " (Hypothetical — Filters Did Not Pass)" : ""}
                                          </p>
                                          {/* Target / Mode row */}
                                          <div className="flex gap-2 flex-wrap pb-1">
                                            <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 text-[10px] font-semibold">{ib.target_based ?? "Fixed"}</span>
                                            <span className="px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 text-[10px] font-semibold">{ib.targetCalcCols}</span>
                                            {ib.incentive_num_pct && <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-600 text-[10px] font-semibold">{ib.incentive_num_pct}</span>}
                                          </div>
                                          {/* Base fare build-up */}
                                          {([
                                            ["Sell Fare",    `₹ ${(ib.sell_fare ?? 0).toLocaleString("en-IN")}`],
                                            ...(ib.sell_tax_yq_added ? [["+ YQ Tax", `₹ ${(ib.sell_tax_yq_value ?? 0).toLocaleString("en-IN")}`]] : []),
                                            ...(ib.sale_yr_added     ? [["+ YR",     `₹ ${(ib.sale_yr_value    ?? 0).toLocaleString("en-IN")}`]] : []),
                                            ["Base Total",  `₹ ${(ib.base_total ?? 0).toLocaleString("en-IN")}`],
                                            // Slab-based: show period, cumulative achieved, the band reached, and the cell
                                            ...(ib.is_slab ? [
                                              ["Period",            ib.slab_period_range ? `${ib.slab_period ?? ""} · ${ib.slab_period_range}` : (ib.slab_period ?? "—")],
                                              ["Achieved (period)", `₹ ${(ib.slab_achieved ?? 0).toLocaleString("en-IN")}`],
                                              ["Band Target ≥",     `₹ ${(ib.slab_target ?? 0).toLocaleString("en-IN")}`],
                                              ["Segment × Class",   ib.slab_cell ?? "—"],
                                            ] : []),
                                            ...(ib.incentiveAmtPct != null
                                              ? [[isPercentage ? "Rate" : "Amount", isPercentage ? `${ib.incentiveAmtPct}%` : `₹ ${ib.incentiveAmtPct}`]]
                                              : []),
                                          ] as [string, string][]).map(([k, v]) => (
                                            <div key={k} className="flex items-baseline justify-between gap-4">
                                              <span className={`text-[11px] ${k === "Base Total" ? "font-bold text-gray-700" : "text-gray-500"}`}>{k}</span>
                                              <span className={`text-[11px] font-mono ${k === "Base Total" ? "font-bold text-gray-700" : "text-gray-600"}`}>{v}</span>
                                            </div>
                                          ))}
                                          {/* Formula + result */}
                                          <div className="pt-1 flex items-center justify-between gap-2">
                                            <p className="text-[11px] text-gray-400 italic flex-1">{ib.formula}</p>
                                            {ib.result != null && (
                                              <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 text-[11px] font-bold font-mono shrink-0">
                                                ₹ {ib.result.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                                              </span>
                                            )}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                );
                              })}

                              {/* ── Inclusion For Payout diagnostic ── */}
                              {d.inclusion_diagnostic && d.inclusion_diagnostic.steps.length > 0 && (
                                <div className="border border-gray-100 rounded-lg overflow-hidden">
                                  <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 border-b border-gray-100">
                                    <span className="px-2 py-0.5 rounded bg-teal-100 text-teal-700 text-[10px] font-semibold shrink-0">INCL</span>
                                    <span className="text-[11px] font-semibold text-gray-700 flex-1">Inclusion For Payout</span>
                                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                      !d.inclusion_diagnostic.is_excluded
                                        ? "bg-teal-100 text-teal-600"
                                        : "bg-amber-100 text-amber-700"
                                    }`}>
                                      {!d.inclusion_diagnostic.is_excluded ? "Included" : "Not Included"}
                                    </span>
                                  </div>
                                  <div className="px-3 py-2 space-y-1.5">
                                    {d.inclusion_diagnostic.steps.map((s, si) => (
                                      <div key={si} className={`flex items-center gap-2 px-2.5 py-2 rounded-lg ${s.matched ? "bg-teal-50" : "bg-amber-50"}`}>
                                        <span className={`font-bold text-sm shrink-0 ${s.matched ? "text-teal-500" : "text-amber-500"}`}>{s.matched ? "✓" : "✗"}</span>
                                        <span className="font-semibold text-gray-700 flex-1 text-[11px]">
                                          {EXCL_FIELD_LABELS[s.field] ?? s.field}
                                        </span>
                                        <span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-32 truncate" title={s.ticket_value}>{s.ticket_value}</span>
                                        <span className="text-gray-400 shrink-0">→</span>
                                        <span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-32 truncate" title={s.rule_value}>{s.rule_value}</span>
                                        <ChevronRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                                      </div>
                                    ))}
                                    {d.inclusion_diagnostic.reason && (
                                      <p className="text-[10px] text-gray-400 italic pt-0.5 leading-relaxed">{d.inclusion_diagnostic.reason}</p>
                                    )}
                                  </div>
                                </div>
                              )}

                              {/* ── Exclusion For Payout diagnostic ── */}
                              {d.exclusion_diagnostic && d.exclusion_diagnostic.steps.length > 0 && (
                                <div className="border border-gray-100 rounded-lg overflow-hidden">
                                  <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 border-b border-gray-100">
                                    <span className="px-2 py-0.5 rounded bg-orange-100 text-orange-700 text-[10px] font-semibold shrink-0">EXCL</span>
                                    <span className="text-[11px] font-semibold text-gray-700 flex-1">Exclusion For Payout</span>
                                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                      d.exclusion_diagnostic.is_excluded
                                        ? "bg-red-100 text-red-600"
                                        : "bg-emerald-100 text-emerald-600"
                                    }`}>
                                      {d.exclusion_diagnostic.is_excluded ? "Excluded" : "Not Excluded"}
                                    </span>
                                  </div>
                                  <div className="px-3 py-2 space-y-1.5">
                                    {d.exclusion_diagnostic.steps.map((s, si) => (
                                      <div key={si} className={`flex items-center gap-2 px-2.5 py-2 rounded-lg ${s.matched ? "bg-red-50" : "bg-emerald-50"}`}>
                                        <span className={`font-bold text-sm shrink-0 ${s.matched ? "text-red-500" : "text-emerald-500"}`}>{s.matched ? "✓" : "✗"}</span>
                                        <span className="font-semibold text-gray-700 flex-1 text-[11px]">
                                          {EXCL_FIELD_LABELS[s.field] ?? s.field}
                                        </span>
                                        <span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-32 truncate" title={s.ticket_value}>{s.ticket_value}</span>
                                        <span className="text-gray-400 shrink-0">→</span>
                                        <span className="px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-700 text-[11px] font-mono shrink-0 max-w-32 truncate" title={s.rule_value}>{s.rule_value}</span>
                                        <ChevronRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                                      </div>
                                    ))}
                                    {d.exclusion_diagnostic.reason && (
                                      <p className="text-[10px] text-gray-400 italic pt-0.5 leading-relaxed">{d.exclusion_diagnostic.reason}</p>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between gap-3">
              {diagTicket && (
                <button
                  onClick={markAsReviewed}
                  className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-700 transition-colors"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> Mark as Reviewed
                </button>
              )}
              <button onClick={closeDiagnosis} className="ml-auto px-4 py-2 border border-gray-200 text-xs rounded-lg text-gray-600 hover:bg-gray-50">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
