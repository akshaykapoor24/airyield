"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Plus, Search, Edit2, Trash2, Plane, Globe, TrendingUp, RefreshCw, Upload, Download, X,
  CheckCircle, XCircle, Clock, Check,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters, canSubmitMasterRequest, canViewMasterRequests } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import Pagination from "@/components/ui/Pagination";

type Airline = {
  id: number;
  name: string;
  iata_code: string;
  icao_code: string | null;
  logo_url: string | null;
  is_active: boolean;
  contract_year: "CY" | "FY" | null;
};

type BulkResult = { total: number; success: number; failed: number; errors: string[] };

type Approval = {
  id: number;
  name: string;
  iata_code: string;
  icao_code: string | null;
  contract_year: "CY" | "FY" | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

const emptyForm = {
  name: "",
  iata_code: "",
  icao_code: "",
  contract_year: "",
};

function AddAirlineModal({
  onClose, onSaved, isPlatformAdmin,
}: { onClose: () => void; onSaved: () => void; isPlatformAdmin: boolean }) {
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [requestType, setRequestType] = useState<"new" | "update">("new");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [existingAirlines, setExistingAirlines] = useState<Airline[]>([]);
  const [form, setForm] = useState<typeof emptyForm>({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [uploading, setUploading] = useState(false);

  const set = <K extends keyof typeof emptyForm>(k: K, v: string) => setForm(p => ({ ...p, [k]: v }));

  useEffect(() => {
    if (requestType === "update" && existingAirlines.length === 0) {
      api.get<Airline[]>("/airlines/?limit=5000").then(r => setExistingAirlines(r.data)).catch(() => {});
    }
  }, [requestType]);

  const handleTargetSelect = (id: number) => {
    setTargetId(id);
    const airline = existingAirlines.find(a => a.id === id);
    if (airline) {
      setForm({
        name: airline.name,
        iata_code: airline.iata_code,
        icao_code: airline.icao_code ?? "",
        contract_year: airline.contract_year ?? "",
      });
    }
  };

  const handleManualSave = async () => {
    if (!form.name.trim() || !form.iata_code.trim()) {
      setError("Airline name and code are required.");
      return;
    }
    if (requestType === "update" && !targetId) {
      setError("Please select the airline you want to update.");
      return;
    }
    setSaving(true); setError("");
    try {
      await api.post("/airlines/", {
        name: form.name.trim(),
        iata_code: form.iata_code.trim().toUpperCase(),
        icao_code: form.icao_code.trim() || null,
        contract_year: form.contract_year || null,
        request_type: requestType,
        target_id: targetId,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save airline.");
    } finally {
      setSaving(false);
    }
  };

  const handleXLSUpload = async () => {
    if (!file) { setError("Please select a file."); return; }
    setUploading(true); setError(""); setBulkResult(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const { data } = await api.post<BulkResult>("/airlines/bulk-upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setBulkResult(data);
      if (data.success > 0) onSaved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleTemplateDownload = async () => {
    setError("");
    try {
      const res = await api.get("/airlines/template", { responseType: "blob" });
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "airline_template.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Template download failed.");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-sky-50 flex items-center justify-center">
              <Plane className="w-4 h-4 text-sky-600" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">
                {requestType === "update" ? "Update Airline" : "Add Airline"}
              </h2>
              <p className="text-[10px] text-gray-400">
                {isPlatformAdmin
                  ? requestType === "update" ? "Will directly update the existing record" : "Will be added directly to master data"
                  : requestType === "update" ? "Update request will be sent for approval" : "Will be sent for Platform Admin approval"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="flex border-b border-gray-100">
          {(["manual", "xls"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400 hover:text-gray-600"
              }`}>
              {t === "manual" ? "Manual Entry" : "Upload XLS"}
            </button>
          ))}
        </div>

        <div className="px-6 py-4">
          {tab === "manual" ? (
            <div key="manual" className="space-y-3">
              {/* New / Update toggle */}
              <div className="flex gap-2">
                {(["new", "update"] as const).map(rt => (
                  <button
                    key={rt}
                    type="button"
                    onClick={() => { setRequestType(rt); setTargetId(null); setForm({ ...emptyForm }); }}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                      requestType === rt
                        ? rt === "new"
                          ? "bg-sky-600 text-white border-sky-600"
                          : "bg-amber-500 text-white border-amber-500"
                        : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    {rt === "new" ? "New Entry" : "Update Existing"}
                  </button>
                ))}
              </div>

              {requestType === "update" && (
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Select Airline to Update *
                  </label>
                  <select
                    value={targetId ?? ""}
                    onChange={e => handleTargetSelect(Number(e.target.value))}
                    className="w-full border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-amber-50"
                  >
                    <option value="">— choose existing airline —</option>
                    {existingAirlines.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.iata_code} — {a.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Airline Name *
                </label>
                <input value={form.name ?? ""} onChange={e => set("name", e.target.value)}
                  placeholder="e.g. Air India"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Airline Code *
                  </label>
                  <input value={form.iata_code ?? ""} onChange={e => set("iata_code", e.target.value.toUpperCase())}
                    maxLength={3} placeholder="e.g. AI"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    IATA Numeric Code
                  </label>
                  <input value={form.icao_code ?? ""} onChange={e => set("icao_code", e.target.value.toUpperCase())}
                    maxLength={4} placeholder="e.g. AIC"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Contract Year
                </label>
                <select value={form.contract_year} onChange={e => set("contract_year", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50">
                  <option value="">— Select —</option>
                  <option value="CY">CY — Calendar Year (ends Dec 31)</option>
                  <option value="FY">FY — Financial Year (ends Mar 31)</option>
                </select>
              </div>

              {error && <p className="text-[11px] text-red-500">{error}</p>}
            </div>
          ) : (
            <div key="xls" className="space-y-3">
              <div className="bg-sky-50 border border-sky-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-sky-700">Download XLS Template</p>
                  <p className="text-[10px] text-sky-500 mt-0.5">
                    Columns: AIRLINE_ID (ignored), Code, IATA_NUMERIC_CODE, Airline, DUPLICATE_FLAG (ignored)
                  </p>
                </div>
                <button type="button" onClick={handleTemplateDownload}
                  className="flex items-center gap-1 text-sky-600 hover:text-sky-800 text-xs font-medium">
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Select XLS / XLSX File
                </label>
                <input type="file" accept=".xls,.xlsx"
                  onChange={e => { setFile(e.target.files?.[0] ?? null); setBulkResult(null); setError(""); }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-sky-50 file:text-sky-600 file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none" />
              </div>

              {bulkResult && (
                <div className={`rounded-lg border px-3 py-2.5 text-xs space-y-1 ${
                  bulkResult.failed > 0 ? "bg-yellow-50 border-yellow-200" : "bg-green-50 border-green-200"
                }`}>
                  <p className="font-semibold">
                    Upload complete — {bulkResult.success} of {bulkResult.total} rows{" "}
                    {isPlatformAdmin ? "added" : "submitted for approval"}
                  </p>
                  {bulkResult.errors.slice(0, 5).map((e, i) => (
                    <p key={i} className="text-[10px] text-red-500">{e}</p>
                  ))}
                  {bulkResult.errors.length > 5 && (
                    <p className="text-[10px] text-gray-400">...and {bulkResult.errors.length - 5} more errors</p>
                  )}
                </div>
              )}

              {error && <p className="text-[11px] text-red-500">{error}</p>}
            </div>
          )}
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            {bulkResult ? "Close" : "Cancel"}
          </button>
          {!bulkResult && (
            <button
              onClick={tab === "manual" ? handleManualSave : handleXLSUpload}
              disabled={saving || uploading}
              className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving || uploading
                ? "Processing..."
                : tab === "manual"
                  ? requestType === "update"
                    ? isPlatformAdmin ? "Update Airline" : "Submit Update for Approval"
                    : isPlatformAdmin ? "Add Airline" : "Submit for Approval"
                  : isPlatformAdmin ? "Upload & Import" : "Upload & Submit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function RequestTypeBadge({ type }: { type: "new" | "update" }) {
  return type === "update"
    ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">Update</span>
    : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 border border-green-200">New</span>;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { icon: React.ReactNode; cls: string }> = {
    pending: { icon: <Clock className="w-3 h-3" />, cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
    approved: { icon: <CheckCircle className="w-3 h-3" />, cls: "bg-green-50 text-green-700 border-green-200" },
    rejected: { icon: <XCircle className="w-3 h-3" />, cls: "bg-red-50 text-red-700 border-red-200" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${s.cls}`}>
      {s.icon} {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function EditAirlineModal({
  airline, onClose, onSaved,
}: { airline: Airline; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: airline.name,
    iata_code: airline.iata_code,
    icao_code: airline.icao_code ?? "",
    contract_year: airline.contract_year ?? "",
    is_active: airline.is_active,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  const handleSave = async () => {
    if (!form.name.trim() || !form.iata_code.trim()) {
      setError("Airline name and code are required.");
      return;
    }
    setSaving(true); setError("");
    try {
      await api.patch(`/airlines/${airline.id}`, {
        name: form.name.trim(),
        iata_code: form.iata_code.trim().toUpperCase(),
        icao_code: String(form.icao_code).trim() || null,
        contract_year: String(form.contract_year).trim() || null,
        is_active: form.is_active,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to update airline.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Edit Airline — {airline.iata_code}</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Airline Name *</label>
            <input value={form.name ?? ""} onChange={e => set("name", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Airline Code *</label>
              <input value={form.iata_code ?? ""} onChange={e => set("iata_code", e.target.value.toUpperCase())}
                maxLength={3}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">IATA Numeric Code</label>
              <input value={String(form.icao_code ?? "")} onChange={e => set("icao_code", e.target.value.toUpperCase())}
                maxLength={4}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contract Year</label>
            <select value={form.contract_year} onChange={e => set("contract_year", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50">
              <option value="">— Select —</option>
              <option value="CY">CY — Calendar Year (ends Dec 31)</option>
              <option value="FY">FY — Financial Year (ends Mar 31)</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={e => set("is_active", e.target.checked)}
              className="rounded border-gray-300 text-sky-600 focus:ring-sky-500"
            />
            Active airline
          </label>
          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>
        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RejectModal({
  approval, onClose, onDone,
}: { approval: Approval; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const handleReject = async () => {
    setSaving(true);
    try {
      await api.patch(`/airlines/approvals/${approval.id}/reject`, { rejection_reason: reason || null });
      onDone();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Reject Airline — {approval.iata_code}</h2>
        </div>
        <div className="px-6 py-4">
          <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Reason (optional)</label>
          <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
            placeholder="Explain why this airline is being rejected..."
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 bg-gray-50 resize-none" />
        </div>
        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={handleReject} disabled={saving}
            className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50">
            {saving ? "Rejecting..." : "Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── diff modal ─────────────────────────────────────────────────────────────

function AirlineDiffModal({
  approval, current, loading, onClose,
}: { approval: Approval; current: Airline | null; loading: boolean; onClose: () => void }) {
  const fields: { label: string; ak: keyof Approval; ck: keyof Airline }[] = [
    { label: "Airline Name",       ak: "name",          ck: "name" },
    { label: "Airline Code",       ak: "iata_code",     ck: "iata_code" },
    { label: "IATA Numeric Code",  ak: "icao_code",     ck: "icao_code" },
    { label: "Contract Year",      ak: "contract_year", ck: "contract_year" },
  ];
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Change Diff — {approval.iata_code}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Updating Airline ID #{approval.target_id}</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-6 py-4">
          {loading ? (
            <div className="py-8 text-center text-xs text-gray-400">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading current record...
            </div>
          ) : !current ? (
            <p className="text-xs text-red-500 py-4 text-center">Could not load the current airline record.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide w-36">Field</th>
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Current</th>
                  <th className="text-left py-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {fields.map(({ label, ak, ck }) => {
                  const cur = String(current[ck] ?? "");
                  const proposed = String(approval[ak] ?? "");
                  const changed = cur !== proposed;
                  return (
                    <tr key={label} className={`border-b border-gray-50 ${changed ? "bg-amber-50/60" : ""}`}>
                      <td className="py-2 pr-3 font-semibold text-gray-600 text-[11px]">{label}</td>
                      <td className="py-2 pr-3 text-gray-500">{cur || "—"}</td>
                      <td className={`py-2 font-medium ${changed ? "text-amber-700" : "text-gray-700"}`}>
                        {proposed || "—"}
                        {changed && <span className="ml-1.5 text-[9px] bg-amber-200 text-amber-800 px-1 py-0.5 rounded font-bold">CHANGED</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="px-6 pb-4">
          <button onClick={onClose} className="w-full border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Close</button>
        </div>
      </div>
    </div>
  );
}

export default function AirlinesPage() {
  const user = useAppSelector(s => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const canSubmitRequest = canSubmitMasterRequest(user?.role);
  const canOpenRequestsTab = canViewMasterRequests(user?.role);

  const [airlines, setAirlines] = useState<Airline[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"list" | "approvals">("list");
  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<Airline | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Approval | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [diffTarget, setDiffTarget] = useState<Approval | null>(null);
  const [diffRecord, setDiffRecord] = useState<Airline | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const PAGE_SIZE = 100;

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchAirlines = useCallback(async (currentPage = page) => {
    setLoading(true);
    try {
      const q = debouncedSearch.trim();
      const searchParam = q ? { search: q } : {};
      const [airlinesRes, countRes] = await Promise.all([
        api.get<Airline[]>("/airlines/", { params: { skip: (currentPage - 1) * PAGE_SIZE, limit: PAGE_SIZE, ...searchParam } }),
        api.get<{ total: number }>("/airlines/count", { params: searchParam }),
      ]);
      setAirlines(airlinesRes.data);
      setTotalCount(countRes.data.total);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch]);

  const fetchApprovals = useCallback(async () => {
    if (!canOpenRequestsTab) return;
    try {
      const { data } = await api.get<Approval[]>("/airlines/approvals");
      setApprovals(data);
    } catch { /* ignore */ }
  }, [canOpenRequestsTab]);

  useEffect(() => { fetchAirlines(page); fetchApprovals(); }, [page, debouncedSearch, fetchAirlines, fetchApprovals]);

  const handleApprove = async (id: number) => {
    setApprovingId(id);
    try {
      await api.patch(`/airlines/approvals/${id}/approve`);
      await Promise.all([fetchAirlines(), fetchApprovals()]);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to approve.");
    } finally {
      setApprovingId(null);
    }
  };

  const handleViewDiff = async (approval: Approval) => {
    if (!approval.target_id) return;
    setDiffTarget(approval);
    setLoadingDiff(true);
    setDiffRecord(null);
    try {
      const { data } = await api.get<Airline>(`/airlines/${approval.target_id}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); } finally { setLoadingDiff(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this airline permanently?")) return;
    try {
      await api.delete(`/airlines/${id}`);
      setAirlines(p => p.filter(a => a.id !== id));
    } catch {
      alert("Failed to delete airline.");
    }
  };

  const pendingCount = approvals.filter(a => a.status === "pending").length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Masters</p>
          <h1 className="text-xl font-bold text-gray-900">Airline Master</h1>
          <p className="text-xs text-gray-500 mt-0.5">{totalCount} airlines · {airlines.filter(a => a.is_active).length} active on this page</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setPage(1); fetchAirlines(1); }} disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {canSubmitRequest && (
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              <Plus className="w-3.5 h-3.5" />
              {isPlatformAdmin ? "Add Airline" : "Submit Airline"}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Airlines", value: totalCount, icon: Plane, color: "text-sky-600 bg-sky-50" },
          { label: "Active Airlines", value: airlines.filter(a => a.is_active).length, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
          { label: "With IATA Numeric Code", value: airlines.filter(a => a.icao_code).length, icon: Globe, color: "text-violet-600 bg-violet-50" },
          { label: "Pending Approvals", value: pendingCount, icon: Upload, color: "text-orange-600 bg-orange-50" },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {canOpenRequestsTab && (
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
          {(["list", "approvals"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
              }`}>
              {t === "list" ? "Airline List" : (
                <span className="flex items-center gap-1.5">
                  {isPlatformAdmin ? "Pending Approvals" : "My Submissions"}
                  {pendingCount > 0 && t === "approvals" && isPlatformAdmin && (
                    <span className="bg-orange-500 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full">{pendingCount}</span>
                  )}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {tab === "list" && (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search airline, code or IATA numeric code..."
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400 bg-gray-50" />
          </div>
          <span className="text-[11px] text-gray-400 ml-auto">{airlines.length} shown · {totalCount} total</span>
        </div>     

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["AIRLINE", "CODE", "IATA_NUMERIC_CODE", "CONTRACT YEAR", "STATUS", ...(isPlatformAdmin ? ["ACTIONS"] : [])].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={isPlatformAdmin ? 6 : 5} className="px-4 py-12 text-center text-xs text-gray-400">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading airlines...
                </td></tr>
              ) : airlines.length === 0 ? (
                <tr><td colSpan={isPlatformAdmin ? 6 : 5} className="px-4 py-12 text-center text-xs text-gray-400">No airlines found.</td></tr>
              ) : airlines.map((a, idx) => (
                <tr key={a.id}
                  className={`border-b border-gray-50 hover:bg-sky-50/30 transition-colors group ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                  <td className="px-3 py-2 text-[11px] text-gray-800">{a.name}</td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-[11px] font-bold text-sky-600 bg-sky-50 px-2 py-0.5 rounded">{a.iata_code}</span>
                  </td>
                  <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{a.icao_code ?? "—"}</td>
                  <td className="px-3 py-2">
                    {a.contract_year
                      ? <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-50 text-indigo-600 border border-indigo-200">{a.contract_year}</span>
                      : <span className="text-[11px] text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                      a.is_active ? "bg-green-50 text-green-700 border-green-200" : "bg-gray-50 text-gray-500 border-gray-200"
                    }`}>
                      {a.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  {isPlatformAdmin && (
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => setEditTarget(a)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Edit">
                          <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                        </button>
                        <button onClick={() => handleDelete(a.id)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={totalCount}
          onPageChange={(p) => setPage(p)}
        />
      </div>
      )}

      {tab === "approvals" && canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-700">
              {isPlatformAdmin ? "Pending Approval Requests" : "My Submitted Airlines"}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e4d8c" }}>
                  {["AIRLINE", "CODE", "IATA_NUMERIC_CODE", "CONTRACT YEAR", "REQUEST",
                    ...(isPlatformAdmin ? ["SUBMITTED BY", "SUBMITTED AT", "ACTIONS"] : ["STATUS", "SUBMITTED AT", "REASON"])
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-xs text-gray-400">
                    {isPlatformAdmin ? "No pending approvals." : "You haven't submitted any airlines yet."}
                  </td></tr>
                ) : approvals.map((a, idx) => (
                  <tr key={a.id}
                    className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{a.name}</td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-[11px] font-bold text-sky-600 bg-sky-50 px-2 py-0.5 rounded">{a.iata_code}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{a.icao_code ?? "—"}</td>
                    <td className="px-3 py-2">
                      {a.contract_year
                        ? <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-50 text-indigo-600 border border-indigo-200">{a.contract_year}</span>
                        : <span className="text-[11px] text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2"><RequestTypeBadge type={a.request_type} /></td>
                    {isPlatformAdmin ? (
                      <>
                        <td className="px-3 py-2">
                          <p className="text-[11px] font-semibold text-gray-700">{a.submitted_by.full_name}</p>
                          <p className="text-[10px] text-gray-400">{a.submitted_by.email}</p>
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">
                          {new Date(a.submitted_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {a.request_type === "update" && (
                              <button onClick={() => handleViewDiff(a)}
                                className="px-2.5 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-[10px] font-semibold">
                                View Changes
                              </button>
                            )}
                            <button onClick={() => handleApprove(a.id)} disabled={approvingId === a.id}
                              className="flex items-center gap-1 px-2.5 py-1 bg-green-500 hover:bg-green-600 text-white rounded-lg text-[10px] font-semibold disabled:opacity-50">
                              <Check className="w-3 h-3" />
                              {approvingId === a.id ? "..." : "Approve"}
                            </button>
                            <button onClick={() => setRejectTarget(a)}
                              className="flex items-center gap-1 px-2.5 py-1 bg-red-500 hover:bg-red-600 text-white rounded-lg text-[10px] font-semibold">
                              <X className="w-3 h-3" /> Reject
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2"><StatusBadge status={a.status} /></td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">
                          {new Date(a.submitted_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500 max-w-xs truncate">
                          {a.rejection_reason ?? "—"}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAdd && (
        <AddAirlineModal
          onClose={() => setShowAdd(false)}
          onSaved={() => { fetchAirlines(); fetchApprovals(); }}
          isPlatformAdmin={isPlatformAdmin}
        />
      )}
      {editTarget && (
        <EditAirlineModal
          airline={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={fetchAirlines}
        />
      )}
      {rejectTarget && (
        <RejectModal
          approval={rejectTarget}
          onClose={() => setRejectTarget(null)}
          onDone={() => { fetchApprovals(); }}
        />
      )}
      {diffTarget && (
        <AirlineDiffModal
          approval={diffTarget}
          current={diffRecord}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
    </div>
  );
}
