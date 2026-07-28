"use client";

// Agency Info manager (table + add/edit modal + supplier-sourced add + xlsx
// upload) for Agency Profile → Agency Onboarding. Agencies are private to the
// user; details are copied from the global Supplier Master at add-time.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Search } from "lucide-react";
import api from "@/lib/api";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

export type AgencyRow = {
  id: number;
  name: string;
  vendor_type: string | null;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  notes: string | null;
  is_active: boolean;
};

// the supplier fields an agency copies from at add-time
type SupplierFull = {
  id: number;
  name: string;
  vendor_type: string | null;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  notes: string | null;
};

export default function AgencyInfoSection({ onChange }: { onChange?: (count: number) => void }) {
  const [rows, setRows] = useState<AgencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<AgencyRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<AgencyRow[]>("/agencies/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);

  const toggle = async (row: AgencyRow) => {
    try {
      const { data } = await api.patch<AgencyRow>(`/agencies/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this agency? Its entities and login IDs will be removed too. This cannot be undone.")) return;
    try {
      await api.delete(`/agencies/${id}`);
      setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    } catch { alert("Delete failed."); }
  };

  return (
    <div className="space-y-3">
      <Toolbar label="Agency" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => setModal(null)} onRefresh={fetchRows} loading={loading} />

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["NAME", "VENDOR TYPE", "GST", "PAN", "PHONE", "EMAIL", "STATUS", "ACTIONS"].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-xs text-gray-400">No agencies yet. Add one from the Supplier Master or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.vendor_type || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.gst_number || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.pan_number || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.contact_phone || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.contact_email || "—"}</td>
                  <td className="px-3 py-2"><ActiveBadge active={r.is_active} onClick={() => toggle(r)} /></td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                      <button onClick={() => del(r.id)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal !== false && (
        <AgencyModal agency={modal} onClose={() => setModal(false)} onSaved={() => { setModal(false); fetchRows(); }} onRefresh={fetchRows} />
      )}
    </div>
  );
}

function AgencyModal({
  agency, onClose, onSaved, onRefresh,
}: {
  agency: AgencyRow | null;
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
}) {
  const isEdit = !!agency;
  const [tab, setTab] = useState<"supplier" | "multi" | "xls">("supplier");
  const [suppliers, setSuppliers] = useState<SupplierFull[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // single "From Supplier" / edit form
  const [supplierId, setSupplierId] = useState<number | null>(null);
  const [form, setForm] = useState({
    name: agency?.name ?? "",
    vendor_type: agency?.vendor_type ?? "",
    gst_number: agency?.gst_number ?? "",
    pan_number: agency?.pan_number ?? "",
    contact_phone: agency?.contact_phone ?? "",
    contact_email: agency?.contact_email ?? "",
    notes: agency?.notes ?? "",
    is_active: agency?.is_active ?? true,
  });
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  // multi-pick state
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pickSearch, setPickSearch] = useState("");
  const [result, setResult] = useState<{ created: number; skipped: number } | null>(null);

  useEffect(() => {
    if (!isEdit) {
      api.get<SupplierFull[]>("/suppliers/", { params: { limit: 5000 } })
        .then(r => setSuppliers(r.data)).catch(() => setSuppliers([]));
    }
  }, [isEdit]);

  const pickSupplier = (id: number) => {
    setSupplierId(id);
    const s = suppliers.find(x => x.id === id);
    if (s) {
      setForm({
        name: s.name ?? "",
        vendor_type: s.vendor_type ?? "",
        gst_number: s.gst_number ?? "",
        pan_number: s.pan_number ?? "",
        contact_phone: s.contact_phone ?? "",
        contact_email: s.contact_email ?? "",
        notes: s.notes ?? "",
        is_active: true,
      });
    }
  };

  const saveSingle = async () => {
    if (!form.name.trim()) { setError("Agency name is required."); return; }
    setSaving(true); setError("");
    try {
      const body = { ...form, name: form.name.trim() };
      if (isEdit && agency) await api.patch(`/agencies/${agency.id}`, body);
      else await api.post("/agencies/", body);
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMulti = async () => {
    if (picked.size === 0) { setError("Select at least one supplier."); return; }
    setSaving(true); setError(""); setResult(null);
    try {
      const { data } = await api.post<{ created: number; skipped: number }>(
        "/agencies/from-suppliers", { supplier_ids: Array.from(picked) });
      setResult(data);
      setPicked(new Set());
      if (data.created > 0) onRefresh();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const filteredSuppliers = pickSearch.trim()
    ? suppliers.filter(s => s.name.toLowerCase().includes(pickSearch.trim().toLowerCase()))
    : suppliers;

  const manualForm = (
    <div className="space-y-3">
      {!isEdit && (
        <div>
          <label className={LABEL}>Agency (from Supplier Master) *</label>
          <select value={supplierId ?? ""} onChange={e => pickSupplier(Number(e.target.value))} className={INPUT}>
            <option value="">— Select a supplier —</option>
            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}{s.vendor_type ? ` — ${s.vendor_type}` : ""}</option>)}
          </select>
          <p className="text-[10px] text-gray-400 mt-1">Details below are auto-filled from the supplier and stay editable.</p>
        </div>
      )}
      <div><label className={LABEL}>Agency Name *</label>
        <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Lords Travels" className={INPUT} /></div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>Vendor Type</label>
          <input value={form.vendor_type} onChange={e => set("vendor_type", e.target.value)} placeholder="e.g. Agent" className={INPUT} /></div>
        <div><label className={LABEL}>GST Number</label>
          <input value={form.gst_number} onChange={e => set("gst_number", e.target.value)} placeholder="GSTIN" className={INPUT} /></div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>PAN Number</label>
          <input value={form.pan_number} onChange={e => set("pan_number", e.target.value)} placeholder="PAN" className={INPUT} /></div>
        <div><label className={LABEL}>Phone</label>
          <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)} placeholder="Contact phone" className={INPUT} /></div>
      </div>
      <div><label className={LABEL}>Email</label>
        <input value={form.contact_email} onChange={e => set("contact_email", e.target.value)} placeholder="Contact email" className={INPUT} /></div>
      <div><label className={LABEL}>Notes</label>
        <input value={form.notes} onChange={e => set("notes", e.target.value)} placeholder="Remarks" className={INPUT} /></div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
        <span className="text-xs font-semibold text-gray-600">Active</span>
      </label>

      {error && <p className="text-[11px] text-red-500">{error}</p>}

      <div className="flex gap-3 pt-1">
        <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        <button onClick={saveSingle} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Create Agency"}
        </button>
      </div>
    </div>
  );

  return (
    <ModalShell title={isEdit ? "Edit Agency" : "Add Agency"} onClose={onClose}>
      {!isEdit && (
        <div className="flex border-b border-gray-100 mb-4 -mt-1">
          {([["supplier", "From Supplier"], ["multi", "Add from Supplier Master"], ["xls", "Upload XLS"]] as const).map(([t, lbl]) => (
            <button key={t} onClick={() => { setTab(t); setError(""); }}
              className={`flex-1 py-2.5 text-[11px] font-semibold ${tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400"}`}>
              {lbl}
            </button>
          ))}
        </div>
      )}

      {isEdit || tab === "supplier" ? manualForm
        : tab === "multi" ? (
          <div className="space-y-3">
            <p className="text-[11px] text-gray-500">Pick the agencies you work with from the Supplier Master — each becomes an agency. Ones you already added are skipped.</p>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={pickSearch} onChange={e => setPickSearch(e.target.value)} placeholder="Search suppliers…"
                className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400" />
            </div>
            <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-50">
              {filteredSuppliers.length === 0 ? (
                <p className="px-3 py-6 text-center text-[11px] text-gray-400">No suppliers found.</p>
              ) : filteredSuppliers.map(s => (
                <label key={s.id} className="flex items-center gap-2 px-3 py-2 hover:bg-sky-50/40 cursor-pointer">
                  <input type="checkbox" checked={picked.has(s.id)}
                    onChange={e => setPicked(p => { const n = new Set(p); if (e.target.checked) n.add(s.id); else n.delete(s.id); return n; })}
                    className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
                  <span className="text-[11px] font-semibold text-gray-700">{s.name}</span>
                  {s.vendor_type && <span className="text-[10px] text-gray-400">{s.vendor_type}</span>}
                </label>
              ))}
            </div>

            {result && (
              <div className="rounded-lg border bg-green-50 border-green-200 px-3 py-2 text-[11px] text-green-700">
                {result.created} agenc{result.created === 1 ? "y" : "ies"} added{result.skipped > 0 ? `, ${result.skipped} skipped (already added or unavailable)` : ""}.
              </div>
            )}
            {error && <p className="text-[11px] text-red-500">{error}</p>}

            <div className="flex gap-3 pt-1">
              <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Close</button>
              <button onClick={saveMulti} disabled={saving || picked.size === 0} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                {saving ? "Adding…" : `Add ${picked.size || ""} Agenc${picked.size === 1 ? "y" : "ies"}`.replace("  ", " ")}
              </button>
            </div>
          </div>
        ) : (
          <UploadBox resource="agencies" templateName="agency_template.xlsx" columns="NAME, VENDOR_TYPE, GST, PAN, PHONE, EMAIL, NOTES, ACTIVE" onDone={onSaved} />
        )}
    </ModalShell>
  );
}
