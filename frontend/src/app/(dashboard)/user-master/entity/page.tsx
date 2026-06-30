"use client";

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import {
  type EntityRow, INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

export default function EntityPage() {
  const [rows, setRows] = useState<EntityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<EntityRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<EntityRow[]>("/entities/", { params: { search } });
      setRows(data);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);

  const toggle = async (row: EntityRow) => {
    try {
      const { data } = await api.patch<EntityRow>(`/entities/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this entity? This cannot be undone.")) return;
    try { await api.delete(`/entities/${id}`); setRows(p => p.filter(r => r.id !== id)); }
    catch { alert("Delete failed."); }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">User Master</p>
        <h1 className="text-xl font-bold text-gray-900">Entity</h1>
        <p className="text-xs text-gray-500 mt-0.5">Manage your billing / legal entities</p>
      </div>

      <Toolbar label="Entity" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => setModal(null)} onRefresh={fetchRows} loading={loading} />

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["NAME", "CODE", "ADDRESS", "STATE", "CITY", "STATUS", "ACTIONS"].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">No entities yet. Add one or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.code}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.address || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.state || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.city || "—"}</td>
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
        <EntityModal entity={modal} onClose={() => setModal(false)} onSaved={() => { setModal(false); fetchRows(); }} />
      )}
    </div>
  );
}

function EntityModal({ entity, onClose, onSaved }: { entity: EntityRow | null; onClose: () => void; onSaved: () => void }) {
  const isEdit = !!entity;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [form, setForm] = useState({
    name: entity?.name ?? "",
    code: entity?.code ?? "",
    address: entity?.address ?? "",
    state: entity?.state ?? "",
    city: entity?.city ?? "",
    is_active: entity?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  const save = async () => {
    if (!form.name.trim() || !form.code.trim()) { setError("Name and Code are required."); return; }
    setSaving(true); setError("");
    try {
      const body = { ...form, name: form.name.trim(), code: form.code.trim() };
      if (isEdit && entity) await api.patch(`/entities/${entity.id}`, body);
      else await api.post("/entities/", body);
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={isEdit ? "Edit Entity" : "Add Entity"} onClose={onClose}>
      {!isEdit && (
        <div className="flex border-b border-gray-100 mb-4 -mt-1">
          {(["manual", "xls"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-semibold ${tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400"}`}>
              {t === "manual" ? "Manual Entry" : "Upload XLS"}
            </button>
          ))}
        </div>
      )}

      {(isEdit || tab === "manual") ? (
        <div className="space-y-3">
          <div><label className={LABEL}>Entity Name *</label>
            <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Acme Travels Pvt Ltd" className={INPUT} /></div>
          <div><label className={LABEL}>Code *</label>
            <input value={form.code} onChange={e => set("code", e.target.value)} placeholder="e.g. ENT-001" className={INPUT} /></div>
          <div><label className={LABEL}>Address</label>
            <input value={form.address} onChange={e => set("address", e.target.value)} placeholder="Street address" className={INPUT} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>State</label>
              <input value={form.state} onChange={e => set("state", e.target.value)} placeholder="e.g. Maharashtra" className={INPUT} /></div>
            <div><label className={LABEL}>City</label>
              <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} /></div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
            <span className="text-xs font-semibold text-gray-600">Active</span>
          </label>

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={save} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : isEdit ? "Save Changes" : "Create Entity"}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="entities" templateName="entity_template.xlsx" columns="NAME, CODE, ADDRESS, STATE, CITY, ACTIVE" onDone={onSaved} />
      )}
    </ModalShell>
  );
}
