"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, CheckCircle, AlertCircle, RefreshCw, ChevronLeft,
  FileSpreadsheet, X
} from "lucide-react";
import api from "@/lib/api";
import { useRouter } from "next/navigation";
import Link from "next/link";

// ── types ──────────────────────────────────────────────────────────────────
type TicketRow = {
  row_order:           number;
  booking_ref?:        string | null;
  segment_type?:       string | null;
  invoice_type?:       string | null;
  invoice_no?:         string | null;
  ticket_date?:        string | null;
  last_name?:          string | null;
  first_name?:         string | null;
  sector?:             string | null;
  booking_class?:      string | null;
  departure_datetime?: string | null;
  gds_pnr?:            string | null;
  airlines_code?:      string | null;
  ticket_number?:      string | null;
  sell_fare?:          number | null;
  sell_tax?:           number | null;
  sell_tax_yq?:        number | null;
  sale_yr?:            number | null;
  sale_k3?:            number | null;
  rei_sell?:           number | null;
  seat_selection?:     number | null;
  excess_baggage?:     number | null;
  meals?:              number | null;
  rfd_sell?:           number | null;
  can_charge?:         number | null;
  booking_fee_sell?:   number | null;
  cgst_sell?:          number | null;
  sgst_sell?:          number | null;
  igst_sell?:          number | null;
  comm_sell?:          number | null;
  adm?:                number | null;
  incentive_sell?:     number | null;
  dis_sell?:           number | null;
  tds_sell?:           number | null;
  total_amt?:          number | null;
  paid_by_credit_card?: number | null;
  net_amt?:            number | null;
  cc?:                 string | null;
  acc_code?:           string | null;
};

type ExtractionPreview = {
  file_name:  string;
  total_rows: number;
  rows:       TicketRow[];
  warnings:   string[];
};

// Preview table columns (subset for readability)
const PREVIEW_COLS: Array<{ key: keyof TicketRow; label: string; numeric?: boolean }> = [
  { key: "ticket_number",      label: "Ticket #"    },
  { key: "booking_ref",        label: "Booking Ref" },
  { key: "gds_pnr",            label: "PNR"         },
  { key: "airlines_code",      label: "Airline"     },
  { key: "last_name",          label: "Last Name"   },
  { key: "first_name",         label: "First Name"  },
  { key: "sector",             label: "Sector"      },
  { key: "booking_class",      label: "Class"       },
  { key: "ticket_date",        label: "Ticket Date" },
  { key: "departure_datetime", label: "Departure"   },
  { key: "sell_fare",          label: "Sell Fare",   numeric: true },
  { key: "sell_tax",           label: "Tax",         numeric: true },
  { key: "total_amt",          label: "Total Amt",   numeric: true },
  { key: "net_amt",            label: "Net AMT",     numeric: true },
  { key: "comm_sell",          label: "Comm",        numeric: true },
  { key: "acc_code",           label: "Acc Code"    },
];

function fmt(v: number | null | undefined) {
  if (v == null) return <span className="text-gray-300">—</span>;
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function UploadTicketsPage() {
  const router = useRouter();

  // step 1: drop file
  const [step,     setStep]     = useState<"drop" | "preview" | "saving" | "done">("drop");
  const [preview,  setPreview]  = useState<ExtractionPreview | null>(null);
  const [parsing,  setParsing]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [batchId,  setBatchId]  = useState<string | null>(null);

  // ── Step 1: drag-drop → extract ──────────────────────────────────────
  const onDrop = useCallback(async (files: File[]) => {
    if (!files[0]) return;
    setError(null);
    setParsing(true);
    try {
      const form = new FormData();
      form.append("file", files[0]);
      const { data } = await api.post<ExtractionPreview>("/tickets/upload/extract", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(data);
      setStep("preview");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to parse file. Please check the format.");
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

  // ── Step 2: confirm → save ────────────────────────────────────────────
  const confirmUpload = async () => {
    if (!preview) return;
    setStep("saving");
    setError(null);
    try {
      const { data } = await api.post<{ batch_id: string; created_count: number }>(
        "/tickets/upload/confirm",
        { file_name: preview.file_name, rows: preview.rows },
      );
      setBatchId(data.batch_id);
      setStep("done");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save tickets.");
      setStep("preview");
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center gap-3">
        <Link href="/tickets" className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Upload Tickets</h1>
          <p className="text-xs text-gray-500 mt-0.5">Import supplier statement XLS/XLSX file</p>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
          <button onClick={() => setError(null)} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* ── Step: drop ────────────────────────────────────────────────── */}
      {step === "drop" && (
        <div className="max-w-xl space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 text-sm text-blue-700">
            <p className="font-semibold mb-1">Expected XLS columns</p>
            <p className="text-xs leading-relaxed font-mono">
              BookingRef · SegmentType · InvoiceType · InvoiceNo · TicketDate · LastName · FirstName ·
              Sector · Class · DepartureDateTime · GDS_PNR · AirlinesCode · TicketNumber ·
              SellFare · SellTax · SellTax_YQ · Sale_YR · Sale_K3 · REI_Sell · Seat_Selection ·
              Excessbagage · Meals · RFD_SELL · CAN_Charge · Booking_Fee_Sell ·
              CGST_Sell · SGST_Sell · IGST_Sell · Comm_Sell · ADM · Incentive_Sell ·
              DIS_Sell · TDS_Sell · TotalAmt · PaidByCreditCard · Net_AMT · CC · AccCode
            </p>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div
              {...getRootProps()}
              className={`border-2 border-dashed rounded-xl p-14 text-center cursor-pointer transition-colors ${
                isDragActive ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"
              } ${parsing ? "opacity-60 cursor-not-allowed" : ""}`}
            >
              <input {...getInputProps()} />
              {parsing ? (
                <RefreshCw className="w-10 h-10 mx-auto text-blue-400 mb-3 animate-spin" />
              ) : (
                <FileSpreadsheet className="w-10 h-10 mx-auto text-gray-400 mb-3" />
              )}
              <p className="text-sm font-medium text-gray-700">
                {parsing ? "Parsing file…" : isDragActive ? "Drop the file here" : "Drag & drop XLS / XLSX"}
              </p>
              {!parsing && (
                <p className="text-xs text-gray-400 mt-1">or click to browse</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Step: preview ─────────────────────────────────────────────── */}
      {step === "preview" && preview && (
        <div className="space-y-3">
          {/* summary bar */}
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
                onClick={() => { setPreview(null); setStep("drop"); setError(null); }}
                className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmUpload}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f]"
              >
                <CheckCircle className="w-3.5 h-3.5" /> Confirm & Save {preview.total_rows} Rows
              </button>
            </div>
          </div>

          {/* warnings */}
          {preview.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {preview.warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          {/* preview table */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr style={{ background: "#1e3a5f" }}>
                    <th className="px-3 py-2 text-left text-white font-semibold uppercase tracking-wider whitespace-nowrap">#</th>
                    {PREVIEW_COLS.map(c => (
                      <th key={c.key} className="px-3 py-2 text-left text-white font-semibold uppercase tracking-wider whitespace-nowrap">
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 200).map((row, idx) => (
                    <tr key={idx} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/40"}`}>
                      <td className="px-3 py-2 text-gray-400">{row.row_order}</td>
                      {PREVIEW_COLS.map(c => (
                        <td key={c.key} className={`px-3 py-2 whitespace-nowrap ${c.numeric ? "text-right font-medium text-gray-700" : "text-gray-600"}`}>
                          {c.numeric
                            ? fmt(row[c.key] as number | null | undefined)
                            : (row[c.key] ?? <span className="text-gray-300">—</span>)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.rows.length > 200 && (
              <p className="px-4 py-2 text-[10px] text-gray-400 border-t border-gray-100">
                Showing first 200 of {preview.rows.length} rows.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Step: saving ──────────────────────────────────────────────── */}
      {step === "saving" && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mx-auto" />
            <p className="text-sm text-gray-600">Saving tickets to database…</p>
          </div>
        </div>
      )}

      {/* ── Step: done ────────────────────────────────────────────────── */}
      {step === "done" && batchId && preview && (
        <div className="max-w-md mx-auto text-center space-y-5 py-10">
          <div className="w-16 h-16 bg-green-50 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Upload Complete</h2>
            <p className="text-sm text-gray-500 mt-1">
              {preview.total_rows} tickets saved from <span className="font-medium">{preview.file_name}</span>
            </p>
            <p className="text-xs text-gray-400 mt-0.5 font-mono">Batch: {batchId}</p>
          </div>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => { setStep("drop"); setPreview(null); setBatchId(null); setError(null); }}
              className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              Upload Another
            </button>
            <button
              onClick={() => router.push("/tickets")}
              className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#16304f]"
            >
              <Upload className="w-4 h-4" /> View Tickets
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
