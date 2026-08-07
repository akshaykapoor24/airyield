"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Plus, Search, Edit2, Building2, TrendingUp, RefreshCw, Upload, Download, X,
  CheckCircle, XCircle, Clock, Check,
} from "lucide-react";
import api from "@/lib/api";
import { canManageGlobalMasters, canSubmitMasterRequest, canViewMasterRequests } from "@/lib/rbac";
import { useAppSelector } from "@/store/hooks";
import Pagination from "@/components/ui/Pagination";
import MasterDiffModal, { DiffFieldSpec } from "@/components/masters/MasterDiffModal";

type SupplierBranch = { name: string; iata_code: string };

// Directory / member-list fields (from the supplier master XLS). Keys match the backend.
type SupplierDirectory = {
  region_chapter: string | null;
  membership_category: string | null;
  address_1: string | null;
  address_2: string | null;
  address_3: string | null;
  city: string | null;
  pincode: string | null;
  telephone_mobile: string | null;
  website: string | null;
  email_address: string | null;
  alternate_email_id: string | null;
  accounts_email: string | null;
  fax_no: string | null;
  representative_1: string | null;
  representative_2: string | null;
};

type Supplier = {
  id: number;
  name: string;
  code: string;
  vendor_type: string | null;
  vendor_name: string | null;
  branch: string | null;
  branches: SupplierBranch[] | null;
  contact_phone: string | null;
  alternate_phone: string | null;
  contact_email: string | null;
  alternate_email: string | null;
  gst_number: string | null;
  pan_number: string | null;
  notes: string | null;
  is_active: boolean;
} & SupplierDirectory;

type BulkResult = { total: number; success: number; failed: number; errors: string[] };

type Approval = {
  id: number;
  name: string;
  vendor_type: string | null;
  vendor_name: string | null;
  branch: string | null;
  branches: SupplierBranch[] | null;
  contact_phone: string | null;
  alternate_phone: string | null;
  contact_email: string | null;
  alternate_email: string | null;
  gst_number: string | null;
  pan_number: string | null;
  notes: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_by: { id: number; full_name: string; email: string };
  submitted_at: string;
  reviewed_at: string | null;
  rejection_reason: string | null;
  request_type: "new" | "update";
  target_id: number | null;
  // ── platform-admin edit state ────────────────────────────────────────────
  /** True only when an admin changed something the submitter should see. */
  edited?: boolean;
  /** The business values as the submitter originally sent them. */
  original_payload?: Record<string, unknown> | null;
  edited_by?: { id: number; full_name: string; email: string } | null;
  edited_at?: string | null;
} & SupplierDirectory;

const VENDOR_TYPES = ["Agent", "Corporate", "OTA", "TMC", "GSA", "Other"];

// Directory fields rendered in the Add/Edit forms and the diff modal.
// `wide` fields span both grid columns (long free-text like addresses/emails).
const DIRECTORY_FIELDS: { key: keyof SupplierDirectory; label: string; wide?: boolean }[] = [
  { key: "region_chapter", label: "Region / Chapter", wide: true },
  { key: "membership_category", label: "Membership Category" },
  { key: "city", label: "City" },
  { key: "pincode", label: "Pincode" },
  { key: "website", label: "Website" },
  { key: "address_1", label: "Address 1", wide: true },
  { key: "address_2", label: "Address 2", wide: true },
  { key: "address_3", label: "Address 3", wide: true },
  { key: "telephone_mobile", label: "Telephone & Mobile", wide: true },
  { key: "email_address", label: "Email Address", wide: true },
  { key: "alternate_email_id", label: "Alternate Email ID", wide: true },
  { key: "accounts_email", label: "Accounts Email", wide: true },
  { key: "fax_no", label: "Fax No" },
  { key: "representative_1", label: "Representative I" },
  { key: "representative_2", label: "Representative II" },
];

/** Branch list as chips — shared by the table and the diff modal. */
function BranchChips({ branches }: { branches: SupplierBranch[] }) {
  if (!branches || branches.length === 0) return <span className="text-[11px] text-gray-400">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {branches.map((b, i) => (
        <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-100">
          {b.name}{b.iata_code ? <span className="font-mono font-bold"> {b.iata_code}</span> : null}
        </span>
      ))}
    </div>
  );
}

// ── diff field map ─────────────────────────────────────────────────────────
// Directory labels come from DIRECTORY_FIELDS so those 15 names live in one place.
const SUPPLIER_DIFF_FIELDS: DiffFieldSpec[] = [
  { key: "name",            label: "Vendor Name" },
  { key: "vendor_name",     label: "Display Name" },
  { key: "vendor_type",     label: "Type" },
  {
    key: "branches",
    label: "Branches",
    render: v => <BranchChips branches={(v as SupplierBranch[]) ?? []} />,
    // Branch order carries no meaning, so canonicalise before comparing —
    // reordering the list must not read as an admin edit.
    equals: (a, b) => {
      const canon = (bs: unknown) =>
        ((bs as SupplierBranch[]) ?? [])
          .map(x => `${x?.name ?? ""}|${x?.iata_code ?? ""}`)
          .sort()
          .join(";");
      return canon(a) === canon(b);
    },
  },
  { key: "contact_phone",   label: "Contact Number" },
  { key: "alternate_phone", label: "Alternate Contact" },
  { key: "contact_email",   label: "Contact Email" },
  { key: "alternate_email", label: "Alternate Email" },
  { key: "gst_number",      label: "GST Number" },
  { key: "pan_number",      label: "PAN Number" },
  { key: "notes",           label: "Remarks" },
  ...DIRECTORY_FIELDS.map(f => ({ key: f.key as string, label: f.label })),
];

const emptyDirectory: Record<keyof SupplierDirectory, string> = {
  region_chapter: "", membership_category: "", address_1: "", address_2: "", address_3: "",
  city: "", pincode: "", telephone_mobile: "", website: "", email_address: "",
  alternate_email_id: "", accounts_email: "", fax_no: "", representative_1: "", representative_2: "",
};

const emptyForm = {
  name: "",
  vendor_type: "",
  vendor_name: "",
  branch: "",
  contact_phone: "",
  alternate_phone: "",
  contact_email: "",
  alternate_email: "",
  gst_number: "",
  pan_number: "",
  notes: "",
  ...emptyDirectory,
};

function DirectoryFields({
  form, set,
}: {
  form: Record<keyof SupplierDirectory, string>;
  set: (k: keyof SupplierDirectory, v: string) => void;
}) {
  return (
    <div className="border-t border-gray-100 pt-3">
      <p className="text-[11px] font-bold text-gray-500 uppercase tracking-wide mb-2">Directory Details</p>
      <div className="grid grid-cols-2 gap-3">
        {DIRECTORY_FIELDS.map(f => (
          <div key={f.key} className={f.wide ? "col-span-2" : ""}>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{f.label}</label>
            <input value={form[f.key]} onChange={e => set(f.key, e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
          </div>
        ))}
      </div>
    </div>
  );
}

function AddSupplierModal({
  onClose, onSaved, isPlatformAdmin,
}: { onClose: () => void; onSaved: () => void; isPlatformAdmin: boolean }) {
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [requestType, setRequestType] = useState<"new" | "update">("new");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [existingSuppliers, setExistingSuppliers] = useState<Supplier[]>([]);
  const [form, setForm] = useState({ ...emptyForm });
  const [branches, setBranches] = useState<SupplierBranch[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [uploading, setUploading] = useState(false);

  const set = <K extends keyof typeof emptyForm>(k: K, v: string) => setForm(p => ({ ...p, [k]: v }));
  const addBranch = () => setBranches(p => [...p, { name: "", iata_code: "" }]);
  const removeBranch = (i: number) => setBranches(p => p.filter((_, idx) => idx !== i));
  const updateBranch = (i: number, k: keyof SupplierBranch, v: string) =>
    setBranches(p => p.map((b, idx) => idx === i ? { ...b, [k]: v } : b));

  useEffect(() => {
    if (requestType === "update" && existingSuppliers.length === 0) {
      api.get<Supplier[]>("/suppliers/?limit=5000").then(r => setExistingSuppliers(r.data)).catch(() => {});
    }
  }, [requestType]);

  const handleTargetSelect = (id: number) => {
    setTargetId(id);
    const s = existingSuppliers.find(x => x.id === id);
    if (s) {
      setForm({
        name: s.name,
        vendor_type: s.vendor_type ?? "",
        vendor_name: s.vendor_name ?? "",
        branch: s.branch ?? "",
        contact_phone: s.contact_phone ?? "",
        alternate_phone: s.alternate_phone ?? "",
        contact_email: s.contact_email ?? "",
        alternate_email: s.alternate_email ?? "",
        gst_number: s.gst_number ?? "",
        pan_number: s.pan_number ?? "",
        notes: s.notes ?? "",
        ...(Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, s[f.key] ?? ""])) as Record<keyof SupplierDirectory, string>),
      });
      setBranches(s.branches ?? []);
    }
  };

  const handleManualSave = async () => {
    if (!form.name.trim()) { setError("Vendor name is required."); return; }
    if (requestType === "update" && !targetId) { setError("Please select the supplier to update."); return; }
    setSaving(true); setError("");
    try {
      await api.post("/suppliers/", {
        name: form.name.trim(),
        vendor_type: form.vendor_type || null,
        vendor_name: form.vendor_name.trim() || null,
        branch: null,
        branches: branches.filter(b => b.name.trim()).map(b => ({ name: b.name.trim(), iata_code: b.iata_code.trim().toUpperCase() })),
        contact_phone: form.contact_phone || null,
        alternate_phone: form.alternate_phone || null,
        contact_email: form.contact_email || null,
        alternate_email: form.alternate_email || null,
        gst_number: form.gst_number || null,
        pan_number: form.pan_number || null,
        notes: form.notes || null,
        ...Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, form[f.key] || null])),
        request_type: requestType,
        target_id: targetId,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save supplier.");
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
      const { data } = await api.post<BulkResult>("/suppliers/bulk-upload", fd, {
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
      const res = await api.get("/suppliers/template", { responseType: "blob" });
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "supplier_template.xlsx";
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
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-violet-50 flex items-center justify-center">
              <Building2 className="w-4 h-4 text-violet-600" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">
                {requestType === "update" ? "Update Supplier" : "Add Supplier"}
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
                tab === t ? "border-b-2 border-violet-500 text-violet-600" : "text-gray-400 hover:text-gray-600"
              }`}>
              {t === "manual" ? "Manual Entry" : "Upload XLS"}
            </button>
          ))}
        </div>

        <div className="px-6 py-4">
          {tab === "manual" ? (
            <div className="space-y-3">
              <div className="flex gap-2">
                {(["new", "update"] as const).map(rt => (
                  <button key={rt} type="button"
                    onClick={() => { setRequestType(rt); setTargetId(null); setForm({ ...emptyForm }); setBranches([]); }}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                      requestType === rt
                        ? rt === "new" ? "bg-violet-600 text-white border-violet-600" : "bg-amber-500 text-white border-amber-500"
                        : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                    }`}>
                    {rt === "new" ? "New Entry" : "Update Existing"}
                  </button>
                ))}
              </div>

              {requestType === "update" && (
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Select Supplier to Update *
                  </label>
                  <select value={targetId ?? ""} onChange={e => handleTargetSelect(Number(e.target.value))}
                    className="w-full border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-amber-50">
                    <option value="">— choose existing supplier —</option>
                    {existingSuppliers.map(s => (
                      <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Vendor Name *</label>
                  <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Gulf Travel Co."
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Display Name</label>
                  <input value={form.vendor_name} onChange={e => set("vendor_name", e.target.value)} placeholder="Short / trade name"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Type</label>
                <select value={form.vendor_type} onChange={e => set("vendor_type", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50">
                  <option value="">— Select —</option>
                  {VENDOR_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Branches</label>
                  <button type="button" onClick={addBranch}
                    className="text-[11px] text-violet-600 font-medium hover:text-violet-800">+ Add Branch</button>
                </div>
                {branches.map((b, i) => (
                  <div key={i} className="flex gap-2 items-center mb-1.5">
                    <input value={b.name} onChange={e => updateBranch(i, "name", e.target.value)} placeholder="City / Branch name"
                      className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50" />
                    <input value={b.iata_code} onChange={e => updateBranch(i, "iata_code", e.target.value.toUpperCase().slice(0, 3))}
                      placeholder="IATA" maxLength={3}
                      className="w-16 border border-gray-200 rounded-lg px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50 text-center uppercase" />
                    <button type="button" onClick={() => removeBranch(i)}
                      className="p-1 hover:bg-red-50 rounded text-gray-400 hover:text-red-500 flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {branches.length === 0 && (
                  <p className="text-[11px] text-gray-400 italic py-1">No branches added. Click &quot;+ Add Branch&quot; to add one.</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Number</label>
                  <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)} placeholder="+91-XXXXXXXXXX"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Contact No</label>
                  <input value={form.alternate_phone} onChange={e => set("alternate_phone", e.target.value)} placeholder="+91-XXXXXXXXXX"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Person Email ID</label>
                <input type="email" value={form.contact_email} onChange={e => set("contact_email", e.target.value)} placeholder="contact@supplier.com"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Email</label>
                <input type="email" value={form.alternate_email} onChange={e => set("alternate_email", e.target.value)} placeholder="alt@supplier.com"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">GST Number</label>
                  <input value={form.gst_number} onChange={e => set("gst_number", e.target.value.toUpperCase())} placeholder="22AAAAA0000A1Z5"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">PAN Number</label>
                  <input value={form.pan_number} onChange={e => set("pan_number", e.target.value.toUpperCase())} placeholder="AAAAA0000A"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Remarks</label>
                <textarea value={form.notes} onChange={e => set("notes", e.target.value)} rows={2} placeholder="Optional notes..."
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50 resize-none" />
              </div>

              <DirectoryFields form={form} set={(k, v) => set(k, v)} />

              {error && <p className="text-[11px] text-red-500">{error}</p>}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="bg-violet-50 border border-violet-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-violet-700">Download XLS Template</p>
                  <p className="text-[10px] text-violet-500 mt-0.5">
                    Columns: COMPANY NAME, REGION / CHAPTER, MEMBERSHIP CATEGORY, ADD1-3, CITY, PINCODE,
                    TELEPHONE NOS. &amp; MOBILE NOS., WEBSITE, E.MAIL ADDRESS, ALTERNATE E-MAIL ID-1, ACCOUNTS,
                    FAX NO, REPRESENTATIVE I/II (+ optional TYPE, BRANCHES, GST_NUMBER, PAN_NUMBER, REMARKS)
                  </p>
                </div>
                <button type="button" onClick={handleTemplateDownload}
                  className="flex items-center gap-1 text-violet-600 hover:text-violet-800 text-xs font-medium whitespace-nowrap ml-3">
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Select XLS / XLSX File
                </label>
                <input type="file" accept=".xls,.xlsx"
                  onChange={e => { setFile(e.target.files?.[0] ?? null); setBulkResult(null); setError(""); }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-violet-50 file:text-violet-600 file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none" />
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
                    ? isPlatformAdmin ? "Update Supplier" : "Submit Update for Approval"
                    : isPlatformAdmin ? "Add Supplier" : "Submit for Approval"
                  : isPlatformAdmin ? "Upload & Import" : "Upload & Submit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── platform admin edits a pending request ────────────────────────────────

function EditRequestModal({
  approval, onClose, onSaved,
}: { approval: Approval; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: approval.name,
    vendor_type: approval.vendor_type ?? "",
    vendor_name: approval.vendor_name ?? "",
    contact_phone: approval.contact_phone ?? "",
    alternate_phone: approval.alternate_phone ?? "",
    contact_email: approval.contact_email ?? "",
    alternate_email: approval.alternate_email ?? "",
    gst_number: approval.gst_number ?? "",
    pan_number: approval.pan_number ?? "",
    notes: approval.notes ?? "",
    ...(Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, approval[f.key] ?? ""])) as Record<keyof SupplierDirectory, string>),
  });
  const [branches, setBranches] = useState<SupplierBranch[]>(approval.branches ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string) => setForm(p => ({ ...p, [k]: v }));
  const addBranch = () => setBranches(p => [...p, { name: "", iata_code: "" }]);
  const removeBranch = (i: number) => setBranches(p => p.filter((_, idx) => idx !== i));
  const updateBranch = (i: number, k: keyof SupplierBranch, v: string) =>
    setBranches(p => p.map((b, idx) => idx === i ? { ...b, [k]: v } : b));

  /** Returns true when the edit saved, so the caller can chain approve. */
  const save = async (): Promise<boolean> => {
    if (!form.name.trim()) { setError("Vendor name is required."); return false; }
    setError("");
    try {
      await api.patch(`/suppliers/approvals/${approval.id}`, {
        name: form.name.trim(),
        vendor_type: form.vendor_type || null,
        vendor_name: form.vendor_name.trim() || null,
        // A new array, never a mutation of the loaded one — JSON columns here
        // have no mutation tracking.
        branches: branches.filter(b => b.name.trim())
          .map(b => ({ name: b.name.trim(), iata_code: b.iata_code.trim().toUpperCase() })),
        contact_phone: form.contact_phone || null,
        alternate_phone: form.alternate_phone || null,
        contact_email: form.contact_email || null,
        alternate_email: form.alternate_email || null,
        gst_number: form.gst_number || null,
        pan_number: form.pan_number || null,
        notes: form.notes || null,
        ...Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, form[f.key] || null])),
      });
      return true;
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save changes."); return false;
    }
  };

  const handleSave = async () => {
    setSaving(true);
    if (await save()) { onSaved(); onClose(); }
    setSaving(false);
  };

  const handleSaveAndApprove = async () => {
    setSaving(true);
    if (await save()) {
      try {
        await api.patch(`/suppliers/approvals/${approval.id}/approve`);
        onSaved(); onClose();
      } catch (e: unknown) {
        // The edit is already persisted and the request is still pending — say
        // so rather than closing and losing the admin's work.
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(`Changes saved, but approval failed: ${msg ?? "please try again."}`);
        onSaved();
      }
    }
    setSaving(false);
  };

  const field = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50";

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Edit Request — {approval.name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Submitted by {approval.submitted_by.full_name} · they will see what you change
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Vendor Name *</label>
              <input value={form.name} onChange={e => set("name", e.target.value)} className={field} />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Display Name</label>
              <input value={form.vendor_name} onChange={e => set("vendor_name", e.target.value)}
                placeholder="Short / trade name" className={field} />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Type</label>
            <select value={form.vendor_type} onChange={e => set("vendor_type", e.target.value)} className={field}>
              <option value="">— Select —</option>
              {VENDOR_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Branches</label>
              <button type="button" onClick={addBranch}
                className="text-[11px] text-violet-600 font-medium hover:text-violet-800">+ Add Branch</button>
            </div>
            {branches.map((b, i) => (
              <div key={i} className="flex gap-2 items-center mb-1.5">
                <input value={b.name} onChange={e => updateBranch(i, "name", e.target.value)} placeholder="City / Branch name"
                  className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50" />
                <input value={b.iata_code} onChange={e => updateBranch(i, "iata_code", e.target.value.toUpperCase().slice(0, 3))}
                  placeholder="IATA" maxLength={3}
                  className="w-16 border border-gray-200 rounded-lg px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50 text-center uppercase" />
                <button type="button" onClick={() => removeBranch(i)}
                  className="p-1 hover:bg-red-50 rounded text-gray-400 hover:text-red-500 flex-shrink-0">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
            {branches.length === 0 && (
              <p className="text-[11px] text-gray-400 italic py-1">No branches added.</p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Number</label>
              <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)} className={field} />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Contact No</label>
              <input value={form.alternate_phone} onChange={e => set("alternate_phone", e.target.value)} className={field} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Email</label>
              <input type="email" value={form.contact_email} onChange={e => set("contact_email", e.target.value)} className={field} />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Email</label>
              <input type="email" value={form.alternate_email} onChange={e => set("alternate_email", e.target.value)} className={field} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">GST Number</label>
              <input value={form.gst_number} onChange={e => set("gst_number", e.target.value.toUpperCase())}
                className={`${field} font-mono`} />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">PAN Number</label>
              <input value={form.pan_number} onChange={e => set("pan_number", e.target.value.toUpperCase())}
                className={`${field} font-mono`} />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Remarks</label>
            <textarea value={form.notes} onChange={e => set("notes", e.target.value)} rows={2}
              className={`${field} resize-none`} />
          </div>

          <DirectoryFields form={form} set={(k, v) => set(k, v)} />

          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>
        <div className="px-6 pb-5 flex gap-2">
          <button onClick={onClose} disabled={saving}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 border border-violet-500 text-violet-600 rounded-lg py-2 text-xs font-semibold hover:bg-violet-50 disabled:opacity-50">
            {saving ? "..." : "Save Changes"}
          </button>
          <button onClick={handleSaveAndApprove} disabled={saving}
            className="flex-1 bg-green-500 hover:bg-green-600 text-white rounded-lg py-2 text-xs font-semibold disabled:opacity-50">
            {saving ? "..." : "Save & Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditSupplierModal({
  supplier, onClose, onSaved,
}: { supplier: Supplier; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: supplier.name,
    vendor_type: supplier.vendor_type ?? "",
    vendor_name: supplier.vendor_name ?? "",
    branch: supplier.branch ?? "",
    contact_phone: supplier.contact_phone ?? "",
    alternate_phone: supplier.alternate_phone ?? "",
    contact_email: supplier.contact_email ?? "",
    alternate_email: supplier.alternate_email ?? "",
    gst_number: supplier.gst_number ?? "",
    pan_number: supplier.pan_number ?? "",
    notes: supplier.notes ?? "",
    ...(Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, supplier[f.key] ?? ""])) as Record<keyof SupplierDirectory, string>),
    is_active: supplier.is_active,
  });
  const [branches, setBranches] = useState<SupplierBranch[]>(supplier.branches ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));
  const addBranch = () => setBranches(p => [...p, { name: "", iata_code: "" }]);
  const removeBranch = (i: number) => setBranches(p => p.filter((_, idx) => idx !== i));
  const updateBranch = (i: number, k: keyof SupplierBranch, v: string) =>
    setBranches(p => p.map((b, idx) => idx === i ? { ...b, [k]: v } : b));

  const handleSave = async () => {
    if (!form.name.trim()) { setError("Vendor name is required."); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/suppliers/${supplier.id}`, {
        name: form.name.trim(),
        vendor_type: form.vendor_type || null,
        vendor_name: form.vendor_name.trim() || null,
        branch: null,
        branches: branches.filter(b => b.name.trim()).map(b => ({ name: b.name.trim(), iata_code: b.iata_code.trim().toUpperCase() })),
        contact_phone: form.contact_phone || null,
        alternate_phone: form.alternate_phone || null,
        contact_email: form.contact_email || null,
        alternate_email: form.alternate_email || null,
        gst_number: form.gst_number || null,
        pan_number: form.pan_number || null,
        notes: form.notes || null,
        ...Object.fromEntries(DIRECTORY_FIELDS.map(f => [f.key, form[f.key] || null])),
        is_active: form.is_active,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to update supplier.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Edit Supplier — {supplier.code}</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Vendor Name *</label>
              <input value={form.name} onChange={e => set("name", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Display Name</label>
              <input value={form.vendor_name} onChange={e => set("vendor_name", e.target.value)} placeholder="Short / trade name"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Type</label>
            <select value={form.vendor_type} onChange={e => set("vendor_type", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50">
              <option value="">— Select —</option>
              {VENDOR_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Branches</label>
              <button type="button" onClick={addBranch}
                className="text-[11px] text-violet-600 font-medium hover:text-violet-800">+ Add Branch</button>
            </div>
            {branches.map((b, i) => (
              <div key={i} className="flex gap-2 items-center mb-1.5">
                <input value={b.name} onChange={e => updateBranch(i, "name", e.target.value)} placeholder="City / Branch name"
                  className="flex-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50" />
                <input value={b.iata_code} onChange={e => updateBranch(i, "iata_code", e.target.value.toUpperCase().slice(0, 3))}
                  placeholder="IATA" maxLength={3}
                  className="w-16 border border-gray-200 rounded-lg px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50 text-center uppercase" />
                <button type="button" onClick={() => removeBranch(i)}
                  className="p-1 hover:bg-red-50 rounded text-gray-400 hover:text-red-500 flex-shrink-0">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
            {branches.length === 0 && (
              <p className="text-[11px] text-gray-400 italic py-1">No branches added.</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Number</label>
              <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Contact No</label>
              <input value={form.alternate_phone} onChange={e => set("alternate_phone", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Contact Person Email ID</label>
            <input type="email" value={form.contact_email} onChange={e => set("contact_email", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Alternate Email</label>
            <input type="email" value={form.alternate_email} onChange={e => set("alternate_email", e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">GST Number</label>
              <input value={form.gst_number} onChange={e => set("gst_number", e.target.value.toUpperCase())}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">PAN Number</label>
              <input value={form.pan_number} onChange={e => set("pan_number", e.target.value.toUpperCase())}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Remarks</label>
            <textarea value={form.notes} onChange={e => set("notes", e.target.value)} rows={2}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 bg-gray-50 resize-none" />
          </div>

          <DirectoryFields form={form} set={(k, v) => set(k, v)} />

          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)}
              className="rounded border-gray-300 text-violet-600 focus:ring-violet-500" />
            Active supplier
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
      await api.patch(`/suppliers/approvals/${approval.id}/reject`, { rejection_reason: reason || null });
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
          <h2 className="text-sm font-bold text-gray-900">Reject Supplier — {approval.name}</h2>
        </div>
        <div className="px-6 py-4">
          <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Reason (optional)</label>
          <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
            placeholder="Explain why this supplier is being rejected..."
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

function RequestTypeBadge({ type }: { type: "new" | "update" }) {
  return type === "update"
    ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">Update</span>
    : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 border border-green-200">New</span>;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { icon: React.ReactNode; cls: string }> = {
    pending:  { icon: <Clock className="w-3 h-3" />,       cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
    approved: { icon: <CheckCircle className="w-3 h-3" />, cls: "bg-green-50 text-green-700 border-green-200" },
    rejected: { icon: <XCircle className="w-3 h-3" />,     cls: "bg-red-50 text-red-700 border-red-200" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${s.cls}`}>
      {s.icon} {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export default function SuppliersPage() {
  const user = useAppSelector(s => s.auth.user);
  const isPlatformAdmin = canManageGlobalMasters(user?.role);
  const canSubmitRequest = canSubmitMasterRequest(user?.role);
  const canOpenRequestsTab = canViewMasterRequests(user?.role);

  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  // The master list is Master Governance's to show; a tenant user only ever
  // sees what they themselves submitted. Defaulting the tab by role is what
  // enforces that — there is no control to switch back to the list.
  const [tab, setTab] = useState<"list" | "approvals">(
    isPlatformAdmin ? "list" : "approvals",
  );
  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<Supplier | null>(null);
  const [rejectTarget, setRejectTarget] = useState<Approval | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [diffTarget, setDiffTarget] = useState<Approval | null>(null);
  const [diffRecord, setDiffRecord] = useState<Supplier | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [editRequestTarget, setEditRequestTarget] = useState<Approval | null>(null);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const PAGE_SIZE = 100;

  useEffect(() => {
    const timer = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchSuppliers = useCallback(async (currentPage = page) => {
    setLoading(true);
    try {
      const q = debouncedSearch.trim();
      const searchParam = q ? { search: q } : {};
      const [suppliersRes, countRes] = await Promise.all([
        api.get<Supplier[]>("/suppliers/", { params: { skip: (currentPage - 1) * PAGE_SIZE, limit: PAGE_SIZE, ...searchParam } }),
        api.get<{ total: number }>("/suppliers/count", { params: searchParam }),
      ]);
      setSuppliers(suppliersRes.data);
      setTotalCount(countRes.data.total);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch]);

  const fetchApprovals = useCallback(async () => {
    if (!canOpenRequestsTab) return;
    try {
      const { data } = await api.get<Approval[]>("/suppliers/approvals");
      setApprovals(data);
    } catch { /* ignore */ }
  }, [canOpenRequestsTab]);

  useEffect(() => { fetchSuppliers(page); fetchApprovals(); }, [page, debouncedSearch, fetchSuppliers, fetchApprovals]);

  const handleApprove = async (id: number) => {
    setApprovingId(id);
    try {
      await api.patch(`/suppliers/approvals/${id}/approve`);
      await Promise.all([fetchSuppliers(), fetchApprovals()]);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to approve.");
    } finally {
      setApprovingId(null);
    }
  };

  const handleViewDiff = async (approval: Approval) => {
    setDiffTarget(approval);
    setDiffRecord(null);
    // A "new" request has no master record to compare against — the modal just
    // drops that column and shows the admin's edit on its own.
    if (!approval.target_id) return;
    setLoadingDiff(true);
    try {
      const { data } = await api.get<Supplier>(`/suppliers/${approval.target_id}`);
      setDiffRecord(data);
    } catch { setDiffRecord(null); } finally { setLoadingDiff(false); }
  };

  const pendingCount = approvals.filter(a => a.status === "pending").length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Masters</p>
          <h1 className="text-xl font-bold text-gray-900">Supplier Master</h1>
          <p className="text-xs text-gray-500 mt-0.5">{totalCount} suppliers · {suppliers.filter(s => s.is_active).length} active on this page</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setPage(1); fetchSuppliers(1); }} disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          {canSubmitRequest && (
            <button onClick={() => setShowAdd(true)}
              className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              <Plus className="w-3.5 h-3.5" />
              {isPlatformAdmin ? "Add Supplier" : "Submit Supplier"}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {/* Counts of master records are Master Governance's to show. A tenant
            user gets the shape of their own submissions instead. */}
        {(isPlatformAdmin ? [
          { label: "Total Suppliers", value: totalCount, icon: Building2, color: "text-violet-600 bg-violet-50" },
          { label: "Active Suppliers", value: suppliers.filter(s => s.is_active).length, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
          { label: "Pending Approvals", value: pendingCount, icon: Upload, color: "text-orange-600 bg-orange-50" },
        ] : [
          { label: "My Submissions", value: approvals.length, icon: Building2, color: "text-violet-600 bg-violet-50" },
          { label: "Awaiting Approval", value: pendingCount, icon: Upload, color: "text-orange-600 bg-orange-50" },
          { label: "Approved", value: approvals.filter(a => a.status === "approved").length, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
        ]).map(({ label, value, icon: Icon, color }) => (
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

      {canOpenRequestsTab && isPlatformAdmin && (
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
          {(["list", "approvals"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
              }`}>
              {t === "list" ? "Supplier List" : (
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

      {tab === "list" && isPlatformAdmin && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
            <div className="relative flex-1 min-w-48">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search by name, code, type or branch..."
                className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50" />
            </div>
            <span className="text-[11px] text-gray-400 ml-auto">{suppliers.length} shown · {totalCount} total</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e4d8c" }}>
                  {[
                    "CODE", "VENDOR NAME", "DISPLAY NAME", "CITY", "REGION / CHAPTER", "MEMBERSHIP",
                    "TYPE", "BRANCHES", "CONTACT", "EMAIL", "GST", "PAN", "STATUS",
                    ...(isPlatformAdmin ? ["ACTIONS"] : []),
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={isPlatformAdmin ? 14 : 13} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading suppliers...
                  </td></tr>
                ) : suppliers.length === 0 ? (
                  <tr><td colSpan={isPlatformAdmin ? 14 : 13} className="px-4 py-12 text-center text-xs text-gray-400">No suppliers found.</td></tr>
                ) : suppliers.map((s, idx) => (
                  <tr key={s.id}
                    className={`border-b border-gray-50 hover:bg-violet-50/30 transition-colors group ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{s.code}</td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-[11px] font-bold text-violet-600 bg-violet-50 px-2 py-0.5 rounded">{s.name}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{s.vendor_name ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{s.city ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500 max-w-40 truncate" title={s.region_chapter ?? ""}>{s.region_chapter ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{s.membership_category ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{s.vendor_type ?? "—"}</td>
                    <td className="px-3 py-2">
                      {s.branches && s.branches.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {s.branches.map((b, i) => (
                            <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-100">
                              {b.name}{b.iata_code ? <span className="font-mono font-bold">{b.iata_code}</span> : null}
                            </span>
                          ))}
                        </div>
                      ) : <span className="text-[11px] text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">
                      <div>{s.contact_phone ?? "—"}</div>
                      {s.alternate_phone && <div className="text-gray-400 text-[10px]">{s.alternate_phone}</div>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">
                      <div>{s.contact_email ?? "—"}</div>
                      {s.alternate_email && <div className="text-gray-400 text-[10px]">{s.alternate_email}</div>}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{s.gst_number ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{s.pan_number ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                        s.is_active ? "bg-green-50 text-green-700 border-green-200" : "bg-gray-50 text-gray-500 border-gray-200"
                      }`}>
                        {s.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    {isPlatformAdmin && (
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => setEditTarget(s)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Edit">
                            <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={totalCount} onPageChange={p => setPage(p)} />
        </div>
      )}

      {/* A viewer can neither manage the master nor submit to it, so neither
          panel above applies. Say so rather than rendering an empty page. */}
      {!isPlatformAdmin && !canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-16 text-center">
          <p className="text-sm font-medium text-gray-600">Nothing to show here</p>
          <p className="text-xs text-gray-400 mt-1 max-w-md mx-auto leading-relaxed">
            The master list is maintained by the platform team. Your role cannot submit
            master updates, so there are no submissions of your own to display.
          </p>
        </div>
      )}

      {tab === "approvals" && canOpenRequestsTab && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-700">
              {isPlatformAdmin ? "Pending Approval Requests" : "My Submitted Suppliers"}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e4d8c" }}>
                  {[
                    "VENDOR NAME", "DISPLAY NAME", "TYPE", "BRANCHES", "CONTACT", "GST", "PAN", "REQUEST",
                    ...(isPlatformAdmin
                      ? ["SUBMITTED BY", "SUBMITTED AT", "ACTIONS"]
                      : ["STATUS", "SUBMITTED AT", "REASON"]),
                  ].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-10 text-center text-xs text-gray-400">
                    {isPlatformAdmin ? "No pending approvals." : "You haven't submitted any suppliers yet."}
                  </td></tr>
                ) : approvals.map((a, idx) => (
                  <tr key={a.id} className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{a.name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{a.vendor_name ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{a.vendor_type ?? "—"}</td>
                    <td className="px-3 py-2">
                      {a.branches && a.branches.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {a.branches.map((b, i) => (
                            <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-100">
                              {b.name}{b.iata_code ? <span className="font-mono font-bold"> {b.iata_code}</span> : null}
                            </span>
                          ))}
                        </div>
                      ) : <span className="text-[11px] text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{a.contact_phone ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{a.gst_number ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{a.pan_number ?? "—"}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1 flex-wrap">
                        <RequestTypeBadge type={a.request_type} />
                        {/* So a second admin can tell this row has been touched. */}
                        {a.edited && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                            Edited
                          </span>
                        )}
                      </div>
                    </td>
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
                            {/* Also meaningful on a "new" request once edited —
                                the modal then shows submitted vs. edited. */}
                            {(a.request_type === "update" || a.edited) && (
                              <button onClick={() => handleViewDiff(a)}
                                className="px-2.5 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-[10px] font-semibold">
                                View Changes
                              </button>
                            )}
                            <button onClick={() => setEditRequestTarget(a)}
                              className="flex items-center gap-1 px-2.5 py-1 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-[10px] font-semibold">
                              <Edit2 className="w-3 h-3" /> Edit
                            </button>
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
                        <td className="px-3 py-2">
                          <StatusBadge status={a.status} />
                          {/* Lives inside the STATUS cell so no column is added.
                              Shows for pending, approved and rejected alike. */}
                          {a.edited && (
                            <button onClick={() => handleViewDiff(a)}
                              title="See what the platform admin changed"
                              className="mt-1 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100">
                              <Edit2 className="w-2.5 h-2.5" /> Edited by admin
                            </button>
                          )}
                        </td>
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
        <AddSupplierModal
          onClose={() => setShowAdd(false)}
          onSaved={() => { fetchSuppliers(); fetchApprovals(); }}
          isPlatformAdmin={isPlatformAdmin}
        />
      )}
      {editTarget && (
        <EditSupplierModal
          supplier={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={fetchSuppliers}
        />
      )}
      {rejectTarget && (
        <RejectModal
          approval={rejectTarget}
          onClose={() => setRejectTarget(null)}
          onDone={() => { fetchApprovals(); }}
        />
      )}
      {editRequestTarget && (
        <EditRequestModal
          approval={editRequestTarget}
          onClose={() => setEditRequestTarget(null)}
          onSaved={() => { fetchApprovals(); fetchSuppliers(); }}
        />
      )}
      {diffTarget && (
        <MasterDiffModal
          title={`Change Diff — ${diffTarget.name}`}
          subtitle={diffTarget.request_type === "update"
            ? `Updating Supplier ID #${diffTarget.target_id}`
            : "New supplier request"}
          fields={SUPPLIER_DIFF_FIELDS}
          // "Current" only exists for an update request.
          master={diffTarget.request_type === "update" ? diffRecord : null}
          // Once edited, the middle column is what the submitter actually sent;
          // otherwise the request row IS what they sent.
          submitted={diffTarget.edited ? (diffTarget.original_payload ?? {}) : diffTarget}
          edited={diffTarget.edited ? diffTarget : null}
          submittedLabel={isPlatformAdmin ? "User proposed" : "You submitted"}
          editedBy={diffTarget.edited_by}
          editedAt={diffTarget.edited_at}
          loading={loadingDiff}
          onClose={() => { setDiffTarget(null); setDiffRecord(null); }}
        />
      )}
    </div>
  );
}
