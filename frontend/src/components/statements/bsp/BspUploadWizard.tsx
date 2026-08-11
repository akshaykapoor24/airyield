"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  X, FileText, CheckCircle2, UploadCloud, Loader2, ArrowRight, AlertTriangle,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";
import BspComparisonPanel from "./BspComparisonPanel";

function inr(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}

/** Drag-and-drop PDF dropzone (single file). */
function Dropzone({ file, onPick, label }: { file: File | null; onPick: (f: File | null) => void; label: string }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pick = (f: File | null) => {
    if (f && !f.name.toLowerCase().endsWith(".pdf")) { toast.error("Please choose a PDF file."); return; }
    onPick(f);
  };
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
      onClick={() => !file && inputRef.current?.click()}
      className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
        dragging ? "border-blue-500 bg-blue-50" : file ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 bg-slate-50/60 hover:border-slate-300 cursor-pointer"
      }`}
    >
      {file ? (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
          <div className="w-9 h-9 rounded-lg bg-red-50 border border-red-100 flex items-center justify-center shrink-0">
            <FileText className="w-5 h-5 text-red-500" />
          </div>
          <div className="min-w-0 flex-1 text-left">
            <p className="text-xs font-semibold text-slate-800 truncate" title={file.name}>{file.name}</p>
            <p className="text-[11px] text-slate-500">{(file.size / (1024 * 1024)).toFixed(1)} MB · PDF</p>
          </div>
          <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
          <button onClick={(e) => { e.stopPropagation(); onPick(null); }} className="p-1 rounded text-slate-400 hover:text-red-500 shrink-0"><X className="w-4 h-4" /></button>
        </div>
      ) : (
        <>
          <div className="w-11 h-11 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-2">
            <UploadCloud className="w-6 h-6 text-blue-600" />
          </div>
          <p className="text-sm font-medium text-slate-700">{label}</p>
          <p className="text-xs text-slate-400 mt-0.5">Drag & drop or click to browse · PDF only</p>
        </>
      )}
      <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
    </div>
  );
}

const STEPS = ["Summary", "Detailed", "Compare"];

type SummaryData = {
  batch_id: string; status: string; agent_code?: string | null; agent_name?: string | null;
  period_from?: string | null; period_to?: string | null; reference?: string | null;
  gt_balance_payable?: number | string | null; error?: string | null;
};
type DetailData = {
  batch_id: string; status: string; progress_pct: number; processed_pages: number;
  total_pages: number; processed_rows: number; error?: string | null;
};
type Comparison = { group_id: string; match_status: string; lines: { line: string; summary: number | string | null; detail: number | string | null; variance: number | string | null; ok: boolean }[] };

export default function BspUploadWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState(1);
  const [summaryFile, setSummaryFile] = useState<File | null>(null);
  const [detailFile, setDetailFile] = useState<File | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [summaryBatch, setSummaryBatch] = useState<string | null>(null);
  const [detailBatch, setDetailBatch] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [detail, setDetail] = useState<DetailData | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => stopPoll, []);

  // ── Step 1: upload summary, then poll it ──────────────────────────────────
  const uploadSummary = async () => {
    if (!summaryFile) { notifyRequired("Choose the BSP Summary PDF (FCAGBILLSUMNG) to continue."); return; }
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", summaryFile);
      const { data } = await api.post<{ batch_id: string; group_id: string }>("/bsp/summary/upload", fd);
      setGroupId(data.group_id); setSummaryBatch(data.batch_id);
      setSummary({ batch_id: data.batch_id, status: "pending" });
    } catch (e) { toast.error(errMsg(e, "Failed to upload summary.")); }
    finally { setBusy(false); }
  };

  const fetchSummary = useCallback(async (id: string) => {
    const { data } = await api.get<SummaryData>(`/bsp/summary/${id}`);
    setSummary(data);
    return data;
  }, []);

  useEffect(() => {
    if (!summaryBatch) return;
    const active = summary?.status === "pending" || summary?.status === "processing";
    if (!active) return;
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchSummary(summaryBatch);
        if (s.status === "completed" || s.status === "failed") stopPoll();
      } catch { /* keep polling */ }
    }, 2500);
    return stopPoll;
  }, [summaryBatch, summary?.status, fetchSummary]);

  // ── Step 2: upload detailed against the group, then poll it ───────────────
  const uploadDetail = async () => {
    if (!detailFile) { notifyRequired("Choose the BSP Detailed PDF (FCAGBILLDETALT) to continue."); return; }
    // The button only ever checked the file, so a missing group id — the summary
    // upload having returned without one — made "Upload & compare" a dead click
    // with no message at all.
    if (!groupId) {
      notifyRequired("The summary upload didn't return a billing group. Go back and re-upload the Summary PDF.");
      setStep(1);
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", detailFile); fd.append("group_id", groupId);
      const { data } = await api.post<{ batch_id: string }>("/bsp/upload", fd);
      setDetailBatch(data.batch_id);
      setDetail({ batch_id: data.batch_id, status: "pending", progress_pct: 0, processed_pages: 0, total_pages: 0, processed_rows: 0 });
      setStep(3);
    } catch (e) { toast.error(errMsg(e, "Failed to upload detailed statement.")); }
    finally { setBusy(false); }
  };

  const fetchDetail = useCallback(async (id: string) => {
    const { data } = await api.get<DetailData>(`/bsp/statements/${id}`);
    setDetail(data);
    return data;
  }, []);

  useEffect(() => {
    if (!detailBatch) return;
    const active = detail?.status === "pending" || detail?.status === "processing";
    if (!active) { return; }
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const d = await fetchDetail(detailBatch);
        if (d.status === "completed" || d.status === "failed") {
          stopPoll();
          if (groupId) {
            try { const { data } = await api.get<Comparison>(`/bsp/groups/${groupId}`); setComparison(data); } catch { /* */ }
          }
        }
      } catch { /* keep polling */ }
    }, 3000);
    return stopPoll;
  }, [detailBatch, detail?.status, fetchDetail, groupId]);

  const summaryReady = summary?.status === "completed";
  const summaryFailed = summary?.status === "failed";
  const detailDone = detail?.status === "completed" || detail?.status === "failed";

  // header mismatch warning (soft)
  const headerMismatch =
    comparison && summary && detail?.status === "completed" &&
    comparison.match_status === "mismatch";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header + steps */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">Upload BSP statement</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-100">
          {STEPS.map((s, i) => {
            const n = i + 1; const active = step === n; const done = step > n;
            return (
              <div key={s} className="flex items-center gap-2">
                <span className={`w-6 h-6 rounded-full text-[11px] font-bold flex items-center justify-center ${
                  done ? "bg-emerald-500 text-white" : active ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-400"
                }`}>{done ? "✓" : n}</span>
                <span className={`text-xs font-medium ${active ? "text-slate-800" : "text-slate-400"}`}>{s}</span>
                {n < STEPS.length && <span className="w-6 h-px bg-slate-200" />}
              </div>
            );
          })}
        </div>

        <div className="px-5 py-4 overflow-y-auto">
          {/* ── STEP 1 ── */}
          {step === 1 && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">Upload the <b>Summary</b> PDF (FCAGBILLSUMNG). We read the agent and billing period from the file — no need to enter them.</p>
              <Dropzone file={summaryFile} onPick={setSummaryFile} label="Drop the BSP Summary PDF here" />
              {summary && (summary.status === "pending" || summary.status === "processing") && (
                <div className="flex items-center gap-2 text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading the summary…
                </div>
              )}
              {summaryFailed && (
                <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5" /> {summary?.error || "Could not read the summary PDF."}
                </div>
              )}
              {summaryReady && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 px-3.5 py-3 text-xs">
                  <p className="font-semibold text-emerald-800 mb-1.5 flex items-center gap-1.5"><CheckCircle2 className="w-4 h-4" /> Summary read</p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-600">
                    <div><span className="text-slate-400">Agent:</span> {summary?.agent_code} {summary?.agent_name ? `· ${summary.agent_name}` : ""}</div>
                    <div><span className="text-slate-400">Reference:</span> {summary?.reference || "—"}</div>
                    <div><span className="text-slate-400">Period:</span> {summary?.period_from} → {summary?.period_to}</div>
                    <div><span className="text-slate-400">Balance Payable:</span> <b>₹{inr(summary?.gt_balance_payable)}</b></div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── STEP 2 ── */}
          {step === 2 && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">Now upload the matching <b>Detailed</b> PDF (FCAGBILLDETALT) for the same agent and period. It's parsed in the background.</p>
              <Dropzone file={detailFile} onPick={setDetailFile} label="Drop the BSP Detailed PDF here" />
              <p className="text-[11px] text-slate-400">Large statements (1,000–2,000 pages) parse in the background — you'll see progress on the next step.</p>
            </div>
          )}

          {/* ── STEP 3 ── */}
          {step === 3 && (
            <div className="space-y-3">
              {detail && !detailDone && (
                <div className="bg-blue-50/60 border border-blue-100 rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2 text-[12px] text-blue-700 mb-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Parsing the detailed statement… {detail.processed_pages}/{detail.total_pages || "?"} pages · {detail.processed_rows} rows so far.
                  </div>
                  <div className="h-2 w-full bg-blue-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${detail.progress_pct}%` }} />
                  </div>
                </div>
              )}
              {detail?.status === "failed" && (
                <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5" /> {detail.error || "Could not parse the detailed PDF."}
                </div>
              )}
              {comparison && <BspComparisonPanel matchStatus={comparison.match_status} lines={comparison.lines} />}
              {headerMismatch && (
                <p className="text-[11px] text-amber-600 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> If you expected a match, check that both PDFs are the same agent and billing period.</p>
              )}
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="flex justify-between gap-2 px-5 py-3.5 border-t border-slate-100">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
            {step === 3 && detailDone ? "Close" : "Cancel"}
          </button>
          <div className="flex gap-2">
            {step === 1 && !summaryReady && (
              <button onClick={uploadSummary} disabled={!summaryFile || busy || summary?.status === "processing" || summary?.status === "pending"}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />} Upload summary
              </button>
            )}
            {step === 1 && summaryReady && (
              <button onClick={() => setStep(2)} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                Next: detailed <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            {step === 2 && (
              <button onClick={uploadDetail} disabled={!detailFile || busy}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />} Upload & compare
              </button>
            )}
            {step === 3 && detailDone && (
              <button onClick={() => { onDone(); onClose(); }} className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
