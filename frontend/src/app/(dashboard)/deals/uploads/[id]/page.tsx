"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft, FileText, FileSpreadsheet, File, RefreshCw,
  Check, Clock, AlertTriangle, User, Calendar,
  Tag, ChevronDown, ChevronRight,
} from "lucide-react";
import api from "@/lib/api";

// ── types ──────────────────────────────────────────────────────────────────
type DealRow = {
  id:              number;
  deal_id:         number;
  row_order:       number;
  airline_name:    string | null;
  iata_code:       string | null;
  variant:         string | null;
  eco_commission:  string | null;
  peco_commission: string | null;
  bus_commission:  string | null;
  base_type:       string | null;
  valid_on:        string | null;
  valid_from:      string | null;
  valid_to:        string | null;
  validity_raw:    string | null;
  remarks:         string | null;
};

type UploadedDeal = {
  id:              number;
  source_type:     "upload" | "manual";
  source_agent:    string;
  issue_date:      string | null;
  file_name:       string;
  file_type:       string;
  status:          string;
  notes:           string | null;
  created_at:      string;
  // deal header
  airline_type:    string | null;
  airline_name:    string | null;
  contract_year:   string | null;
  valid_from:      string | null;
  valid_to:        string | null;
  trigger_type:    string | null;
  payout_type:     string | null;
  entity:          string | null;
  remark:          string | null;
  iata_number:     string | null;
  business_type:   string | null;
  entity_lcc:      string | null;
  login_id:        string | null;
  variant:         string | null;
  eco_commission:  string | null;
  peco_commission: string | null;
  bus_commission:  string | null;
  base_type:       string | null;
  valid_on:        string | null;
  validity_raw:    string | null;
  deal_maker_name: string | null;
  // JSON blobs
  incentive_types: string[] | null;
  incentive_data:  Record<string, Record<string, string>> | null;
  incl_excl_types: string[] | null;
  incl_excl_data:  Record<string, Record<string, string>> | null;
  vice_versa:      Record<string, boolean> | null;
};

// ── helpers ────────────────────────────────────────────────────────────────
function FileIcon({ type }: { type: string }) {
  if (type === "pdf")   return <FileText        className="w-5 h-5 text-red-500"   />;
  if (type === "excel") return <FileSpreadsheet  className="w-5 h-5 text-green-600" />;
  return                       <File             className="w-5 h-5 text-blue-500"  />;
}

function fmt(d: string | null) {
  if (!d) return "—";
  try { return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return d; }
}

const LABEL = "text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5";
const VALUE = "text-[12px] font-medium text-gray-800";

// Collapsible section
function Section({ title, children, defaultOpen = true }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 border-b border-gray-100 hover:bg-gray-50/60 transition-colors"
      >
        <h2 className="text-[11px] font-bold text-[#1e3a5f] uppercase tracking-wider">{title}</h2>
        {open
          ? <ChevronDown className="w-4 h-4 text-gray-400" />
          : <ChevronRight className="w-4 h-4 text-gray-400" />}
      </button>
      {open && <div className="px-4 py-3">{children}</div>}
    </div>
  );
}

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  confirmed: { color: "bg-green-100 text-green-700 border-green-200",  icon: <Check         className="w-3.5 h-3.5" />, label: "Confirmed"     },
  extracted: { color: "bg-yellow-100 text-yellow-700 border-yellow-200", icon: <Clock       className="w-3.5 h-3.5" />, label: "Pending Review" },
  rejected:  { color: "bg-red-100 text-red-600 border-red-200",         icon: <AlertTriangle className="w-3.5 h-3.5" />, label: "Rejected"      },
};

// ── page ───────────────────────────────────────────────────────────────────
export default function UploadedDealDetailPage() {
  const params  = useParams<{ id: string }>();
  const router  = useRouter();
  const [deal,    setDeal]    = useState<UploadedDeal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get<UploadedDeal>(`/deals/uploads/${params.id}`);
        setDeal(data);
      } catch {
        setError("Deal not found or you do not have access.");
      } finally {
        setLoading(false);
      }
    })();
  }, [params.id]);

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <RefreshCw className="w-5 h-5 animate-spin text-gray-400" />
    </div>
  );

  if (error || !deal) return (
    <div className="flex flex-col items-center justify-center py-20 gap-3">
      <AlertTriangle className="w-8 h-8 text-red-400" />
      <p className="text-sm text-red-500">{error || "Something went wrong."}</p>
      <button onClick={() => router.back()} className="text-xs text-[#1e3a5f] underline">Go back</button>
    </div>
  );

  const statusCfg = STATUS_CONFIG[deal.status] ?? STATUS_CONFIG.confirmed;
  const isManual  = deal.source_type === "manual";
  const rows: DealRow[] = (deal.eco_commission || deal.peco_commission || deal.bus_commission || deal.validity_raw)
    ? [{
        id: deal.id,
        deal_id: deal.id,
        row_order: 0,
        airline_name: deal.airline_name,
        iata_code: deal.iata_number,
        variant: deal.variant,
        eco_commission: deal.eco_commission,
        peco_commission: deal.peco_commission,
        bus_commission: deal.bus_commission,
        base_type: deal.base_type,
        valid_on: deal.valid_on,
        valid_from: deal.valid_from,
        valid_to: deal.valid_to,
        validity_raw: deal.validity_raw,
        remarks: deal.remark,
      }]
    : [];
  const hasRows = rows.length > 0;

  return (
    <div className="space-y-3 pb-6">

      {/* ── header ──────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => router.back()}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft className="w-4 h-4 text-gray-600" />
          </button>
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">
              Deals / {isManual ? "Manual Entry" : "Uploads"}
            </p>
            <h1 className="text-xl font-bold text-gray-900">
              {deal.airline_name || deal.source_agent}
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {isManual ? `Entered by ${deal.source_agent}` : deal.file_name}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
            isManual
              ? "bg-indigo-50 text-indigo-600 border-indigo-200"
              : "bg-teal-50 text-teal-600 border-teal-200"
          }`}>
            {isManual ? "Manual Entry" : "File Upload"}
          </span>
          <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border ${statusCfg.color}`}>
            {statusCfg.icon} {statusCfg.label}
          </span>
        </div>
      </div>

      {/* ── meta strip ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[
          { icon: <Tag      className="w-3.5 h-3.5 text-indigo-500" />, label: "Entry Type",   value: isManual ? "Manual" : "Upload" },
          { icon: <FileText className="w-3.5 h-3.5 text-blue-500"   />, label: "File Name",    value: deal.file_name },
          { icon: <File     className="w-3.5 h-3.5 text-orange-400" />, label: "File Type",    value: deal.file_type.toUpperCase() },
          { icon: <Calendar className="w-3.5 h-3.5 text-purple-500" />, label: "Created On",   value: fmt(deal.created_at) },
        ].map(m => (
          <div key={m.label} className="bg-white rounded-xl border border-gray-200 px-3 py-2.5 flex items-start gap-2">
            <div className="mt-0.5">{m.icon}</div>
            <div className="min-w-0">
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">{m.label}</p>
              <p className="text-[12px] font-semibold text-gray-800 truncate">{m.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* ── 1. Creation / Upload Information ────────────────────────────── */}
      <Section title="Creation Information">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
          <div>
            <p className={LABEL}>Entry Type</p>
            <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${
              isManual
                ? "bg-indigo-50 text-indigo-600 border-indigo-200"
                : "bg-teal-50 text-teal-600 border-teal-200"
            }`}>
              {isManual ? "Manual" : "Upload"}
            </span>
          </div>
          <div>
            <p className={LABEL}>File Name</p>
            <div className="flex items-center gap-1.5 mt-0.5">
              <FileIcon type={deal.file_type} />
              <p className={VALUE}>{deal.file_name}</p>
            </div>
          </div>
          <div>
            <p className={LABEL}>File Type</p>
            <p className={VALUE}>{deal.file_type.toUpperCase()}</p>
          </div>
          <div>
            <p className={LABEL}>Source Agent</p>
            <div className="flex items-center gap-1.5 mt-0.5">
              <User className="w-3.5 h-3.5 text-gray-400 shrink-0" />
              <p className={VALUE}>{deal.source_agent}</p>
            </div>
          </div>
          <div>
            <p className={LABEL}>Deal Maker</p>
            <p className={deal.deal_maker_name ? VALUE : `${VALUE} text-gray-300`}>
              {deal.deal_maker_name || "—"}
            </p>
          </div>
          <div>
            <p className={LABEL}>Issue Date</p>
            <p className={VALUE}>{fmt(deal.issue_date)}</p>
          </div>
          <div>
            <p className={LABEL}>Created On</p>
            <p className={VALUE}>{fmt(deal.created_at)}</p>
          </div>
          {deal.notes && (
            <div className="col-span-2 md:col-span-3">
              <p className={LABEL}>Notes</p>
              <p className="text-[12px] text-gray-700 whitespace-pre-wrap leading-relaxed">{deal.notes}</p>
            </div>
          )}
        </div>
      </Section>

      {/* ── 2. Commission Rows ──────────────────────────────────────────── */}
      {hasRows && (
        <Section title={`Commission Rows (${rows.length})`}>
          <div className="-mx-4 -mb-3 overflow-x-auto">
            <table className="w-full min-w-max text-xs">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  {["#", "Airline", "IATA", "Variant", "ECO %", "P.ECO %", "BUS %", "Base", "Valid On", "Valid From", "Valid To", "Remarks"].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr key={r.id ?? `${r.row_order}-${idx}`}
                    className={`border-b border-gray-100 hover:bg-gray-50/60 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[10px] text-gray-400">{r.row_order + 1}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800 max-w-44 truncate">{r.airline_name || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.iata_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.variant || "—"}</td>
                    <td className="px-3 py-2">
                      {r.eco_commission
                        ? <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-50 text-blue-700">{r.eco_commission}</span>
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {r.peco_commission
                        ? <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-50 text-purple-700">{r.peco_commission}</span>
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {r.bus_commission
                        ? <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-orange-50 text-orange-700">{r.bus_commission}</span>
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.base_type || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.valid_on || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmt(r.valid_from)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{fmt(r.valid_to)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 max-w-64 truncate" title={r.remarks ?? ""}>{r.remarks || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* empty state for manual deals with no rows */}
      {isManual && !hasRows && (
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-6 text-center">
          <Tag className="w-6 h-6 text-gray-300 mx-auto mb-2" />
          <p className="text-xs text-gray-400">This is a manually entered deal — no commission rows attached.</p>
        </div>
      )}
    </div>
  );
}
