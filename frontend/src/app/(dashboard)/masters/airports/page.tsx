"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Plus, Search, Edit2, Trash2, MapPin, Upload,
  CheckCircle, XCircle, Clock, RefreshCw, Download, X, Check,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters, canSubmitMasterRequest, canViewMasterRequests } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import Pagination from "@/components/ui/Pagination";

// ── constants ──────────────────────────────────────────────────────────────

const CATEGORIZATIONS = [
  "APAC", "MEAI", "MEAI/SAARC", "SAARC",
  "EUROPEAN NATIONS", "LATIN AMERICA", "OTHER",
];
const CONTINENTS = [
  "Africa", "Asia", "Europe",
  "North America", "Oceania", "South America",
];

// ── types ──────────────────────────────────────────────────────────────────

type Airport = {
  id: number;
  apt_id: string | null;
  iata_code: string;
  country: string;
  categorization: string | null;
  continent: string | null;
  city_airport_name: string;
  is_active: boolean;
  created_at: string;
};

type Approval = {
  id: number;
  iata_code: string;
  country: string;
  categorization: string | null;
  continent: string | null;
  city_airport_name: string;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

type BulkResult = { total: number; success: number; failed: number; errors: string[] };

const emptyForm = {
  iata_code: "", country: "", categorization: "", continent: "", city_airport_name: "",
};

// ── status badge ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { icon: React.ReactNode; cls: string }> = {
    pending:  { icon: <Clock className="w-3 h-3" />,        cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
    approved: { icon: <CheckCircle className="w-3 h-3" />,  cls: "bg-green-50 text-green-700 border-green-200" },
    rejected: { icon: <XCircle className="w-3 h-3" />,      cls: "bg-red-50 text-red-700 border-red-200" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${s.cls}`}>
      {s.icon} {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ── request type badge ────────────────────────────────────────────────────

function RequestTypeBadge({ type }: { type: "new" | "update" }) {
  return type === "update"
    ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">Update</span>
    : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 border border-green-200">New</span>;
}

// ── add airport modal ──────────────────────────────────────────────────────

function AddAirportModal({
  onClose, onSaved, isPlatformAdmin,
}: { onClose: () => void; onSaved: () => void; isPlatformAdmin: boolean }) {
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [requestType, setRequestType] = useState<"new" | "update">("new");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [existingAirports, setExistingAirports] = useState<Airport[]>([]);
  const [form, setForm] = useState<typeof emptyForm>({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [uploading, setUploading] = useState(false);

  const set = <K extends keyof typeof emptyForm>(k: K, v: string) => setForm(p => ({ ...p, [k]: v }));

  useEffect(() => {
    if (requestType === "update" && existingAirports.length === 0) {
      api.get<Airport[]>("/airports/?limit=5000").then(r => setExistingAirports(r.data)).catch(() => {});
    }
  }, [requestType]);

  const handleTargetSelect = (id: number) => {
    setTargetId(id);
    const apt = existingAirports.find(a => a.id === id);
    if (apt) {
      setForm({
        iata_code: apt.iata_code,
        country: apt.country,
        categorization: apt.categorization ?? "",
        continent: apt.continent ?? "",
        city_airport_name: apt.city_airport_name,
      });
    }
  };

  const handleManualSave = async () => {
    if (!form.iata_code || !form.country || !form.city_airport_name) {
      setError("IATA Code, Country and City/Airport Name are required."); return;
    }
    if (requestType === "update" && !targetId) {
      setError("Please select the airport you want to update."); return;
    }
    setSaving(true); setError("");
    try {
      await api.post("/airports/", { ...form, request_type: requestType, target_id: targetId });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save airport.");
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
      const { data } = await api.post<BulkResult>("/airports/bulk-upload", fd, {
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
      const res = await api.get("/airports/template", { responseType: "blob" });
      const blob = res.data as Blob;

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "airport_template.xlsx";
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
        {/* header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center">
              <MapPin className="w-4 h-4 text-teal-600" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">
                {requestType === "update" ? "Update Airport" : "Add Airport"}
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

        {/* tabs */}
        <div className="flex border-b border-gray-100">
          {(["manual", "xls"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                tab === t ? "border-b-2 border-teal-500 text-teal-600" : "text-gray-400 hover:text-gray-600"
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
                          ? "bg-teal-600 text-white border-teal-600"
                          : "bg-amber-500 text-white border-amber-500"
                        : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    {rt === "new" ? "New Entry" : "Update Existing"}
                  </button>
                ))}
              </div>

              {/* Target airport selector (only for update) */}
              {requestType === "update" && (
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Select Airport to Update *
                  </label>
                  <select
                    value={targetId ?? ""}
                    onChange={e => handleTargetSelect(Number(e.target.value))}
                    className="w-full border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-amber-50"
                  >
                    <option value="">— choose existing airport —</option>
                    {existingAirports.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.iata_code} — {a.city_airport_name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    IATA Code *
                  </label>
                  <input value={form.iata_code ?? ""} onChange={e => set("iata_code", e.target.value.toUpperCase())}
                    maxLength={3} placeholder="e.g. BOM"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Country *
                  </label>
                  <input value={form.country ?? ""} onChange={e => set("country", e.target.value)}
                    placeholder="e.g. India"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50" />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  City / Airport Name *
                </label>
                <input value={form.city_airport_name ?? ""} onChange={e => set("city_airport_name", e.target.value)}
                  placeholder="e.g. Mumbai - Chhatrapati Shivaji Maharaj International Airport"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Categorization
                  </label>
                  <select value={form.categorization ?? ""} onChange={e => set("categorization", e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50">
                    <option value="">Select...</option>
                    {CATEGORIZATIONS.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Continent
                  </label>
                  <select value={form.continent ?? ""} onChange={e => set("continent", e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50">
                    <option value="">Select...</option>
                    {CONTINENTS.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              {error && <p className="text-[11px] text-red-500">{error}</p>}
            </div>
          ) : (
            <div key="xls" className="space-y-3">
              {/* template download */}
              <div className="bg-teal-50 border border-teal-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-teal-700">Download XLS Template</p>
                  <p className="text-[10px] text-teal-500 mt-0.5">
                    Columns: APT_ID (ignored), IATA_CODE, COUNTRY, CITY_AIRPORT_NAME, CATEGORIZATION, CONTINENT
                  </p>
                </div>
                <button type="button" onClick={handleTemplateDownload}
                  className="flex items-center gap-1 text-teal-600 hover:text-teal-800 text-xs font-medium">
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Select XLS / XLSX File
                </label>
                <input type="file" accept=".xls,.xlsx"
                  onChange={e => { setFile(e.target.files?.[0] ?? null); setBulkResult(null); setError(""); }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-teal-50 file:text-teal-600 file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none" />
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
                    <p className="text-[10px] text-gray-400">…and {bulkResult.errors.length - 5} more errors</p>
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
              style={{ background: "linear-gradient(135deg,#0d9488,#0f766e)" }}>
              {saving || uploading
                ? "Processing..."
                : tab === "manual"
                  ? requestType === "update"
                    ? isPlatformAdmin ? "Update Airport" : "Submit Update for Approval"
                    : isPlatformAdmin ? "Add Airport" : "Submit for Approval"
                  : isPlatformAdmin ? "Upload & Import" : "Upload & Submit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── edit modal ─────────────────────────────────────────────────────────────

function EditAirportModal({
  airport, onClose, onSaved,
}: { airport: Airport; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    country: airport.country,
    categorization: airport.categorization ?? "",
    continent: airport.continent ?? "",
    city_airport_name: airport.city_airport_name,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string, v: string) => setForm(p => ({ ...p, [k]: v }));

  const handleSave = async () => {
    if (!form.country || !form.city_airport_name) { setError("Country and City/Airport Name are required."); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/airports/${airport.id}`, form);
      onSaved(); onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to update airport.");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Edit Airport — {airport.iata_code}</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Country *</label>
            <input value={form.country ?? ""} onChange={e => set("country", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">City / Airport Name *</label>
            <input value={form.city_airport_name ?? ""} onChange={e => set("city_airport_name", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Categorization</label>
              <select value={form.categorization ?? ""} onChange={e => set("categorization", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50">
                <option value="">Select...</option>
                {CATEGORIZATIONS.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Continent</label>
              <select value={form.continent ?? ""} onChange={e => set("continent", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400 bg-gray-50">
                <option value="">Select...</option>
                {CONTINENTS.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>
          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>
        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg,#0d9488,#0f766e)" }}>
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── reject modal ───────────────────────────────────────────────────────────

function RejectModal({
  approval, onClose, onDone,
}: { approval: Approval; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const handleReject = async () => {
    setSaving(true);
    try {
      await api.patch(`/airports/approvals/${approval.id}/reject`, { rejection_reason: reason || null });
      onDone(); onClose();
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Reject Airport — {approval.iata_code}</h2>
        </div>
        <div className="px-6 py-4">
          <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Reason (optional)</label>
          <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
            placeholder="Explain why this airport is being rejected..."
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

function AirportDiffModal({
  approval, current, loading, onClose,
}: { approval: Approval; current: Airport | null; loading: boolean; onClose: () => void }) {
  const fields: { label: string; ak: keyof Approval; ck: keyof Airport }[] = [
    { label: "IATA Code",      ak: "iata_code",         ck: "iata_code" },
    { label: "Country",        ak: "country",           ck: "country" },
    { label: "Categorization", ak: "categorization",    ck: "categorization" },
    { label: "Continent",      ak: "continent",         ck: "continent" },
    { label: "City / Airport", ak: "city_airport_name", ck: "city_airport_name" },
  ];
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Change Diff — {approval.iata_code}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Updating Airport ID #{approval.target_id}</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-6 py-4">
          {loading ? (
            <div className="py-8 text-center text-xs text-gray-400">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading current record...
            </div>
          ) : !current ? (
            <p className="text-xs text-red-500 py-4 text-center">Could not load the current airport record.</p>
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

// ── main page ──────────────────────────────────────────────────────────────

export default function AirportsPage() {
  const user = useAppSelector(s => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const canSubmitRequest = canSubmitMasterRequest(user?.role);
  const canOpenRequestsTab = canViewMasterRequests(user?.role);
  const [tab, setTab]               = useState<"list" | "approvals">("list");
  const [airports, setAirports]     = useState<Airport[]>([]);
  const [approvals, setApprovals]   = useState<Approval[]>([]);
  const [loading, setLoading]       = useState(true);
  const [search, setSearch]         = useState("");
  const [catFilter, setCatFilter]   = useState("");
  const [contFilter, setContFilter] = useState("");
  const [showAdd, setShowAdd]       = useState(false);
  const [editTarget, setEditTarget] = useState<Airport | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Approval | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [diffTarget, setDiffTarget] = useState<Approval | null>(null);
  const [diffRecord, setDiffRecord] = useState<Airport | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const PAGE_SIZE = 100;

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(1); }, [catFilter, contFilter]);

  const fetchAirports = useCallback(async (currentPage = page) => {
    setLoading(true);
    try {
      const filterParams: Record<string, string | number | undefined> = {};
      if (debouncedSearch.trim()) filterParams.q = debouncedSearch.trim();
      if (catFilter) filterParams.categorization = catFilter;
      if (contFilter) filterParams.continent = contFilter;
      const [airportsRes, countRes] = await Promise.all([
        api.get<Airport[]>("/airports/", { params: { skip: (currentPage - 1) * PAGE_SIZE, limit: PAGE_SIZE, ...filterParams } }),
        api.get<{ total: number }>("/airports/count", { params: filterParams }),
      ]);
      setAirports(airportsRes.data);
      setTotalCount(countRes.data.total);
    } finally { setLoading(false); }
  }, [page, debouncedSearch, catFilter, contFilter]);

  const fetchApprovals = useCallback(async () => {
    if (!canOpenRequestsTab) return;
    try {
      const { data } = await api.get<Approval[]>("/airports/approvals");
      setApprovals(data);
    } catch { /* ignore */ }
  }, [canOpenRequestsTab]);

  useEffect(() => { fetchAirports(page); fetchApprovals(); }, [page, debouncedSearch, catFilter, contFilter, fetchAirports, fetchApprovals]);

  const handleApprove = async (id: number) => {
    setApprovingId(id);
    try {
      await api.patch(`/airports/approvals/${id}/approve`);
      await Promise.all([fetchAirports(), fetchApprovals()]);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to approve.");
    } finally { setApprovingId(null); }
  };

  const handleViewDiff = async (approval: Approval) => {
    if (!approval.target_id) return;
    setDiffTarget(approval);
    setLoadingDiff(true);
    setDiffRecord(null);
    try {
      const { data } = await api.get<Airport>(`/airports/${approval.target_id}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); } finally { setLoadingDiff(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this airport permanently?")) return;
    try {
      await api.delete(`/airports/${id}`);
      setAirports(p => p.filter(a => a.id !== id));
    } catch { alert("Failed to delete."); }
  };

  const pendingCount = approvals.filter(a => a.status === "pending").length;

  return (
    <div className="space-y-4">

      {/* ── header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Masters</p>
          <h1 className="text-xl font-bold text-gray-900">Airport Master</h1>
          <p className="text-xs text-gray-500 mt-0.5">{totalCount} airports · {new Set(airports.map(a => a.country)).size} countries on this page</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setPage(1); fetchAirports(1); fetchApprovals(); }} disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {canSubmitRequest && (
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90"
              style={{ background: "linear-gradient(135deg,#0d9488,#0f766e)" }}>
              <Plus className="w-3.5 h-3.5" />
              {isPlatformAdmin ? "Add Airport" : "Submit Airport"}
            </button>
          )}
        </div>
      </div>

      {/* ── stats ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Airports", value: totalCount, color: "text-teal-600 bg-teal-50" },
          { label: "Countries",       value: new Set(airports.map(a => a.country)).size, color: "text-blue-600 bg-blue-50" },
          { label: "Continents",      value: new Set(airports.map(a => a.continent).filter(Boolean)).size, color: "text-violet-600 bg-violet-50" },
          { label: "Pending Approvals", value: pendingCount, color: "text-orange-600 bg-orange-50" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
              <MapPin className="w-4 h-4" />
            </div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* ── tabs ───────────────────────────────────────────────────────── */}
      {canOpenRequestsTab && (
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
          {(["list", "approvals"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
              }`}>
              {t === "list" ? "Airport List" : (
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

      {/* ── airport list tab ───────────────────────────────────────────── */}
      {tab === "list" && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          {/* toolbar */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
            <div className="relative flex-1 min-w-48">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search IATA, country, city..."
                className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-teal-400 bg-gray-50" />
            </div>
            <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
              className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-teal-400">
              <option value="">All Categories</option>
              {CATEGORIZATIONS.map(c => <option key={c}>{c}</option>)}
            </select>
            <select value={contFilter} onChange={e => setContFilter(e.target.value)}
              className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-teal-400">
              <option value="">All Continents</option>
              {CONTINENTS.map(c => <option key={c}>{c}</option>)}
            </select>
            <span className="text-[11px] text-gray-400 ml-auto">{airports.length} shown · {totalCount} total</span>
          </div>

          {/* table */}
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#0d4f4f" }}>
                  {["APT_ID", "IATA_CODE", "COUNTRY", "CATEGORIZATION", "CONTINENT", "CITY_AIRPORT_NAME", ...(isPlatformAdmin ? ["ACTIONS"] : [])].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading airports...
                  </td></tr>
                ) : airports.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">No airports found.</td></tr>
                ) : airports.map((a, idx) => (
                  <tr key={a.id}
                    className={`border-b border-gray-50 hover:bg-teal-50/30 transition-colors group ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-500">{a.apt_id ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-[11px] font-bold text-teal-600 bg-teal-50 px-2 py-0.5 rounded">{a.iata_code}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{a.country}</td>
                    <td className="px-3 py-2">
                      {a.categorization
                        ? <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium border border-blue-100">{a.categorization}</span>
                        : <span className="text-[10px] text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.continent ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800 max-w-xs truncate">{a.city_airport_name}</td>
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

      {/* ── approvals / submissions tab ────────────────────────────────── */}
      {tab === "approvals" && canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-700">
              {isPlatformAdmin ? "Pending Approval Requests" : "My Submitted Airports"}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#0d4f4f" }}>
                  {["IATA_CODE", "COUNTRY", "CATEGORIZATION", "CONTINENT", "CITY_AIRPORT_NAME", "REQUEST",
                    ...(isPlatformAdmin ? ["SUBMITTED BY", "SUBMITTED AT", "ACTIONS"] : ["STATUS", "SUBMITTED AT", "REASON"])
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-xs text-gray-400">
                    {isPlatformAdmin ? "No pending approvals." : "You haven't submitted any airports yet."}
                  </td></tr>
                ) : approvals.map((a, idx) => (
                  <tr key={a.id}
                    className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2">
                      <span className="font-mono text-[11px] font-bold text-teal-600 bg-teal-50 px-2 py-0.5 rounded">{a.iata_code}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{a.country}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.categorization ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.continent ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800 max-w-xs truncate">{a.city_airport_name}</td>
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

      {/* ── modals ─────────────────────────────────────────────────────── */}
      {showAdd && (
        <AddAirportModal
          onClose={() => setShowAdd(false)}
          onSaved={() => { fetchAirports(); fetchApprovals(); }}
          isPlatformAdmin={isPlatformAdmin}
        />
      )}
      {editTarget && (
        <EditAirportModal
          airport={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={fetchAirports}
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
        <AirportDiffModal
          approval={diffTarget}
          current={diffRecord}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
    </div>
  );
}
