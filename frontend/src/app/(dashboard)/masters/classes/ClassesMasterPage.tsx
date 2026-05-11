"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus,
  Search,
  Edit2,
  Trash2,
  Upload,
  Download,
  RefreshCw,
  X,
  Tag,
  CheckCircle,
  XCircle,
  Clock,
  Check,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters, canSubmitMasterRequest, canViewMasterRequests } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import Pagination from "@/components/ui/Pagination";

type AirlineClassMaster = {
  id: number;
  airline_name: string;
  class_type: string;
  class_code: string;
  airline_type: string | null;
  class_note: string | null;
  is_active: boolean;
};

type BulkResult = { total: number; success: number; failed: number; errors: string[] };
type ClassApproval = {
  id: number;
  airline_name: string;
  class_type: string;
  class_code: string;
  airline_type: string | null;
  class_note: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
};

const emptyForm = {
  airline_name: "",
  class_type: "",
  class_code: "",
  airline_type: "",
  class_note: "",
};

function normalize(s: string) {
  return (s ?? "").toString().trim().toLowerCase();
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

function AddClassesModal({
  onClose,
  onSaved,
  isPlatformAdmin,
}: {
  onClose: () => void;
  onSaved: () => void;
  isPlatformAdmin: boolean;
}) {
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [requestType, setRequestType] = useState<"new" | "update">("new");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [existingClasses, setExistingClasses] = useState<AirlineClassMaster[]>([]);
  const [form, setForm] = useState<typeof emptyForm>({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const set = <K extends keyof typeof emptyForm>(k: K, v: string) => setForm(p => ({ ...p, [k]: v }));

  useEffect(() => {
    if (requestType === "update" && existingClasses.length === 0) {
      api.get<AirlineClassMaster[]>("/classes/?limit=5000").then(r => setExistingClasses(r.data)).catch(() => {});
    }
  }, [requestType]);

  const handleTargetSelect = (id: number) => {
    setTargetId(id);
    const cls = existingClasses.find(c => c.id === id);
    if (cls) {
      setForm({
        airline_name: cls.airline_name,
        class_type: cls.class_type,
        class_code: cls.class_code,
        airline_type: cls.airline_type ?? "",
        class_note: cls.class_note ?? "",
      });
    }
  };

  const handleManualSave = async () => {
    if (!form.airline_name.trim() || !form.class_type.trim() || !form.class_code.trim()) {
      setError("AIRLINE_NAME, CLASS_TYPE and CLASS_CODE are required.");
      return;
    }
    if (requestType === "update" && !targetId) {
      setError("Please select the class you want to update.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.post("/classes/", {
        airline_name: form.airline_name,
        class_type: form.class_type,
        class_code: form.class_code,
        airline_type: form.airline_type.trim() || null,
        class_note: form.class_note.trim() || null,
        request_type: requestType,
        target_id: targetId,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save class.");
    } finally {
      setSaving(false);
    }
  };

  const handleXLSUpload = async () => {
    if (!file) {
      setError("Please select a file.");
      return;
    }
    setUploading(true);
    setError("");
    setBulkResult(null);

    const fd = new FormData();
    fd.append("file", file);

    try {
      const { data } = await api.post<BulkResult>("/classes/bulk-upload", fd, {
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
      const res = await api.get("/classes/template", { responseType: "blob" });
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "airline_class_template.xlsx";
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
            <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center">
              <Tag className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">
                {requestType === "update" ? "Update Airline Class" : "Add Airline Class"}
              </h2>
              <p className="text-[10px] text-gray-400">
                {isPlatformAdmin
                  ? requestType === "update" ? "Will directly update the existing record" : "Will be added directly to master data"
                  : requestType === "update" ? "Update request will be sent for approval" : "Will be sent for Platform Admin approval"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg" aria-label="Close">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="flex border-b border-gray-100">
          {(["manual", "xls"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                tab === t ? "border-b-2 border-emerald-500 text-emerald-600" : "text-gray-400 hover:text-gray-600"
              }`}
            >
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
                          ? "bg-emerald-600 text-white border-emerald-600"
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
                    Select Class to Update *
                  </label>
                  <select
                    value={targetId ?? ""}
                    onChange={e => handleTargetSelect(Number(e.target.value))}
                    className="w-full border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-amber-50"
                  >
                    <option value="">— choose existing class —</option>
                    {existingClasses.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.airline_name} / {c.class_type} / {c.class_code}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Airline Name *
                </label>
                <input
                  value={form.airline_name ?? ""}
                  onChange={e => set("airline_name", e.target.value)}
                  placeholder="e.g. AEROFLOT AIRLINES"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    CLASS_TYPE *
                  </label>
                  <input
                    value={form.class_type ?? ""}
                    onChange={e => set("class_type", e.target.value)}
                    placeholder="e.g. ECONOMY CLASS"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    CLASS_CODE *
                  </label>
                  <input
                    value={form.class_code ?? ""}
                    onChange={e => set("class_code", e.target.value.toUpperCase())}
                    placeholder="e.g. G, J, Y, LCC"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  AIRLINE_TYPE
                </label>
                <select
                  value={form.airline_type ?? ""}
                  onChange={e => set("airline_type", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
                >
                  <option value="">Select...</option>
                  <option value="GDS">GDS</option>
                  <option value="LCC">LCC</option>
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  CLASS_NOTE
                </label>
                <textarea
                  value={form.class_note ?? ""}
                  onChange={e => set("class_note", e.target.value)}
                  rows={3}
                  placeholder="Optional notes"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50 resize-none"
                />
              </div>

              {error && <p className="text-[11px] text-red-500">{error}</p>}
            </div>
          ) : (
            <div key="xls" className="space-y-3">
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-emerald-700">Download XLS Template</p>
                  <p className="text-[10px] text-emerald-600 mt-0.5">
                    Required: AIRLINE_NAME, CLASS_TYPE, CLASS_CODE (ROW_ID is ignored).
                    Optional: AIRLINE_TYPE, CLASS_NOTE.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleTemplateDownload}
                  className="flex items-center gap-1 text-emerald-600 hover:text-emerald-800 text-xs font-medium"
                >
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Select XLS / XLSX File
                </label>
                <input
                  type="file"
                  accept=".xls,.xlsx"
                  onChange={e => {
                    setFile(e.target.files?.[0] ?? null);
                    setBulkResult(null);
                    setError("");
                  }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-emerald-50 file:text-emerald-600 file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none"
                />
              </div>

              {bulkResult && (
                <div
                  className={`rounded-lg border px-3 py-2.5 text-xs space-y-1 ${
                    bulkResult.failed > 0 ? "bg-yellow-50 border-yellow-200" : "bg-green-50 border-green-200"
                  }`}
                >
                  <p className="font-semibold">
                    Upload complete — {bulkResult.success} of {bulkResult.total} rows{" "}
                    {isPlatformAdmin ? "added" : "submitted for approval"}
                  </p>
                  {bulkResult.errors.slice(0, 5).map((e, i) => (
                    <p key={i} className="text-[10px] text-red-500">
                      {e}
                    </p>
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
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            {bulkResult ? "Close" : "Cancel"}
          </button>
          {!bulkResult && (
            <button
              onClick={tab === "manual" ? handleManualSave : handleXLSUpload}
              disabled={saving || uploading}
              className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              style={{ background: "linear-gradient(135deg,#047857,#059669)" }}
            >
              {saving || uploading
                ? "Processing..."
                : tab === "manual"
                  ? requestType === "update"
                    ? isPlatformAdmin ? "Update Class" : "Submit Update for Approval"
                    : isPlatformAdmin ? "Add Class" : "Submit for Approval"
                  : isPlatformAdmin ? "Upload & Import" : "Upload & Submit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function EditClassesModal({
  item,
  onClose,
  onSaved,
}: {
  item: AirlineClassMaster;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    airline_name: item.airline_name,
    class_type: item.class_type,
    class_code: item.class_code,
    airline_type: item.airline_type ?? "",
    class_note: item.class_note ?? "",
    is_active: item.is_active,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  const handleSave = async () => {
    if (!form.airline_name.trim() || !form.class_type.trim() || !form.class_code.trim()) {
      setError("AIRLINE_NAME, CLASS_TYPE and CLASS_CODE are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.patch(`/classes/${item.id}`, {
        airline_name: form.airline_name,
        class_type: form.class_type,
        class_code: form.class_code,
        airline_type: form.airline_type.trim() || null,
        class_note: form.class_note.trim() || null,
        is_active: form.is_active,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to update class.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">
            Edit Class — {item.class_code}
          </h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg" aria-label="Close">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              Airline Name *
            </label>
            <input
              value={form.airline_name ?? ""}
              onChange={e => set("airline_name", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                CLASS_TYPE *
              </label>
              <input
                value={form.class_type ?? ""}
                onChange={e => set("class_type", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                CLASS_CODE *
              </label>
              <input
                value={form.class_code ?? ""}
                onChange={e => set("class_code", e.target.value.toUpperCase())}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              AIRLINE_TYPE
            </label>
            <select
              value={form.airline_type ?? ""}
              onChange={e => set("airline_type", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50"
            >
              <option value="">Select...</option>
              <option value="GDS">GDS</option>
              <option value="LCC">LCC</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              CLASS_NOTE
            </label>
            <textarea
              value={form.class_note ?? ""}
              onChange={e => set("class_note", e.target.value)}
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-gray-50 resize-none"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={e => set("is_active", e.target.checked)}
              className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
            />
            Active
          </label>

          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg,#047857,#059669)" }}
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── diff modal ─────────────────────────────────────────────────────────────

function ClassDiffModal({
  approval, current, loading, onClose,
}: { approval: ClassApproval; current: AirlineClassMaster | null; loading: boolean; onClose: () => void }) {
  const fields: { label: string; ak: keyof ClassApproval; ck: keyof AirlineClassMaster }[] = [
    { label: "Airline Name", ak: "airline_name", ck: "airline_name" },
    { label: "Class Type",   ak: "class_type",   ck: "class_type" },
    { label: "Class Code",   ak: "class_code",   ck: "class_code" },
    { label: "Airline Type", ak: "airline_type", ck: "airline_type" },
    { label: "Class Note",   ak: "class_note",   ck: "class_note" },
  ];
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Change Diff — {approval.class_code}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Updating Class ID #{approval.target_id}</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-6 py-4">
          {loading ? (
            <div className="py-8 text-center text-xs text-gray-400">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading current record...
            </div>
          ) : !current ? (
            <p className="text-xs text-red-500 py-4 text-center">Could not load the current class record.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide w-32">Field</th>
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

export default function ClassesMasterPage() {
  const user = useAppSelector(s => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const canSubmitRequest = canSubmitMasterRequest(user?.role);
  const canOpenRequestsTab = canViewMasterRequests(user?.role);

  const [items, setItems] = useState<AirlineClassMaster[]>([]);
  const [approvals, setApprovals] = useState<ClassApproval[]>([]);
  const [tab, setTab] = useState<"list" | "approvals">("list");
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<AirlineClassMaster | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ClassApproval | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [diffTarget, setDiffTarget] = useState<ClassApproval | null>(null);
  const [diffRecord, setDiffRecord] = useState<AirlineClassMaster | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const PAGE_SIZE = 100;

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchItems = useCallback(async (currentPage = page) => {
    setLoading(true);
    setFetchError(null);
    try {
      const searchParams = debouncedSearch.trim() ? { q: debouncedSearch.trim() } : {};
      const [itemsRes, countRes] = await Promise.all([
        api.get<AirlineClassMaster[]>("/classes/", { params: { skip: (currentPage - 1) * PAGE_SIZE, limit: PAGE_SIZE, ...searchParams } }),
        api.get<{ total: number }>("/classes/count", { params: searchParams }),
      ]);
      setItems(itemsRes.data);
      setTotalCount(countRes.data.total);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        "Failed to load classes.";
      setFetchError(msg);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch]);

  const fetchApprovals = useCallback(async () => {
    if (!canOpenRequestsTab) return;
    try {
      const { data } = await api.get<ClassApproval[]>("/classes/approvals");
      setApprovals(data);
    } catch {
      // ignore and keep table empty
    }
  }, [canOpenRequestsTab]);

  useEffect(() => {
    fetchItems(page);
    fetchApprovals();
  }, [page, debouncedSearch, fetchItems, fetchApprovals]);

  const stats = useMemo(() => {
    const active = items.filter(i => i.is_active).length;
    const lcc = items.filter(i => normalize(i.airline_type ?? "") === "lcc").length;
    const gds = items.filter(i => normalize(i.airline_type ?? "") === "gds").length;
    const pending = approvals.filter(a => a.status === "pending").length;
    return { total: totalCount, active, lcc, gds, pending };
  }, [items, approvals, totalCount]);

  const handleViewDiff = async (approval: ClassApproval) => {
    if (!approval.target_id) return;
    setDiffTarget(approval);
    setLoadingDiff(true);
    setDiffRecord(null);
    try {
      const { data } = await api.get<AirlineClassMaster>(`/classes/${approval.target_id}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); } finally { setLoadingDiff(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this class row?")) return;
    try {
      await api.delete(`/classes/${id}`);
      setItems(p => p.filter(x => x.id !== id));
    } catch {
      alert("Failed to delete class row.");
    }
  };

  const handleApprove = async (id: number) => {
    setApprovingId(id);
    try {
      await api.patch(`/classes/approvals/${id}/approve`);
      await Promise.all([fetchItems(), fetchApprovals()]);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to approve request.");
    } finally {
      setApprovingId(null);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    try {
      await api.patch(`/classes/approvals/${rejectTarget.id}/reject`, { rejection_reason: rejectReason || null });
      setRejectTarget(null);
      setRejectReason("");
      await fetchApprovals();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to reject request.");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Masters</p>
          <h1 className="text-xl font-bold text-gray-900">Airline Class Master</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {totalCount} records · {stats.active} active on this page
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => { setPage(1); fetchItems(1); }}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {canSubmitRequest && (
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90"
              style={{ background: "linear-gradient(135deg,#0d9488,#059669)" }}
            >
              <Plus className="w-3.5 h-3.5" />
              {isPlatformAdmin ? "Add Class" : "Submit Class"}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Records", value: stats.total, color: "text-teal-600 bg-teal-50" },
          { label: "Active", value: stats.active, color: "text-emerald-600 bg-emerald-50" },
          { label: "LCC", value: stats.lcc, color: "text-orange-600 bg-orange-50" },
          { label: "Pending Approvals", value: stats.pending, color: "text-violet-600 bg-violet-50" },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            className={`bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm`}
          >
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
              <Tag className="w-4 h-4" />
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
              {t === "list" ? "Class List" : (
                <span className="flex items-center gap-1.5">
                  {isPlatformAdmin ? "Pending Approvals" : "My Submissions"}
                  {stats.pending > 0 && t === "approvals" && isPlatformAdmin && (
                    <span className="bg-orange-500 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full">{stats.pending}</span>
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
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search airline, class type/code..."
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-emerald-400 bg-gray-50"
            />
          </div>
          <span className="text-[11px] text-gray-400 ml-auto">{items.length} shown · {totalCount} total</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#0d9488" }}>
                {["AIRLINE_NAME", "CLASS_TYPE", "CLASS_CODE", "AIRLINE_TYPE", "CLASS_NOTE", ...(isPlatformAdmin ? ["ACTIONS"] : [])].map(
                  h => (
                    <th
                      key={h}
                      className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={isPlatformAdmin ? 6 : 5} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading classes...
                  </td>
                </tr>
              ) : fetchError ? (
                <tr>
                  <td colSpan={isPlatformAdmin ? 6 : 5} className="px-4 py-12 text-center text-xs text-red-500">
                    {fetchError}{" "}
                    <button onClick={() => fetchItems(page)} className="underline ml-1 text-teal-600 hover:text-teal-700">
                      Retry
                    </button>
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={isPlatformAdmin ? 6 : 5} className="px-4 py-12 text-center text-xs text-gray-400">
                    No classes found.
                  </td>
                </tr>
              ) : (
                items.map((it, idx) => (
                  <tr
                    key={it.id}
                    className={`border-b border-gray-50 hover:bg-teal-50/30 transition-colors group ${
                      idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                    }`}
                  >
                    <td className="px-3 py-2 text-[11px] text-gray-800">{it.airline_name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{it.class_type}</td>
                    <td className="px-3 py-2 text-[11px] font-mono font-bold text-teal-700 bg-teal-50 rounded">
                      {it.class_code}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{it.airline_type ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 max-w-xs truncate" title={it.class_note ?? ""}>
                      {it.class_note ?? "—"}
                    </td>
                    {isPlatformAdmin && (
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => setEditTarget(it)}
                            className="p-1.5 hover:bg-blue-50 rounded-lg"
                            title="Edit"
                          >
                            <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                          </button>
                          <button
                            onClick={() => handleDelete(it.id)}
                            className="p-1.5 hover:bg-red-50 rounded-lg"
                            title="Delete"
                          >
                            <Trash2 className="w-3.5 h-3.5 text-red-400" />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))
              )}
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
              {isPlatformAdmin ? "Pending Approval Requests" : "My Submitted Classes"}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#0d9488" }}>
                  {["AIRLINE_NAME", "CLASS_TYPE", "CLASS_CODE", "AIRLINE_TYPE", "CLASS_NOTE", "REQUEST",
                    ...(isPlatformAdmin ? ["SUBMITTED BY", "SUBMITTED AT", "ACTIONS"] : ["STATUS", "SUBMITTED AT", "REASON"])
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-xs text-gray-400">
                    {isPlatformAdmin ? "No pending approvals." : "You haven't submitted any classes yet."}
                  </td></tr>
                ) : approvals.map((a, idx) => (
                  <tr key={a.id}
                    className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{a.airline_name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{a.class_type}</td>
                    <td className="px-3 py-2 text-[11px] font-mono font-bold text-teal-700 bg-teal-50 rounded">{a.class_code}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{a.airline_type ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 max-w-xs truncate">{a.class_note ?? "—"}</td>
                    <td className="px-3 py-2"><RequestTypeBadge type={a.request_type} /></td>
                    {isPlatformAdmin ? (
                      <>
                        <td className="px-3 py-2">
                          <p className="text-[11px] font-semibold text-gray-700">{a.submitted_by.full_name}</p>
                          <p className="text-[10px] text-gray-400">{a.submitted_by.email}</p>
                        </td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{new Date(a.submitted_at).toLocaleDateString()}</td>
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
                            <button onClick={() => { setRejectTarget(a); setRejectReason(""); }}
                              className="flex items-center gap-1 px-2.5 py-1 bg-red-500 hover:bg-red-600 text-white rounded-lg text-[10px] font-semibold">
                              <X className="w-3 h-3" /> Reject
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2"><StatusBadge status={a.status} /></td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{new Date(a.submitted_at).toLocaleDateString()}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500 max-w-xs truncate">{a.rejection_reason ?? "—"}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {diffTarget && (
        <ClassDiffModal
          approval={diffTarget}
          current={diffRecord}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
      {showAdd && <AddClassesModal onClose={() => setShowAdd(false)} onSaved={() => { fetchItems(); fetchApprovals(); }} isPlatformAdmin={isPlatformAdmin} />}
      {editTarget && (
        <EditClassesModal
          item={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={fetchItems}
        />
      )}
      {rejectTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">Reject Class — {rejectTarget.class_code}</h2>
            </div>
            <div className="px-6 py-4">
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Reason (optional)</label>
              <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} rows={3}
                placeholder="Explain why this class is being rejected..."
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 bg-gray-50 resize-none" />
            </div>
            <div className="px-6 pb-5 flex gap-3">
              <button onClick={() => setRejectTarget(null)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
              <button onClick={handleReject}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold">
                Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

