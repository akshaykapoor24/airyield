"use client";

// Agency Entities manager (table + add/edit modal + xlsx upload) for Agency
// Profile → Agency Onboarding. One agency -> many entities (e.g. Lords agency
// has entities in Delhi and Mumbai). In add-mode you pick the agency once, then
// add many entities under it at the same time. Entity code is unique per agency.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Plus } from "lucide-react";
import api from "@/lib/api";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

export type AgencyEntityRow = {
  id: number;
  agency_id: number;
  agency_name: string | null;
  name: string;
  code: string;
  address: string | null;
  state: string | null;
  city: string | null;
  is_active: boolean;
  login_id_count?: number | null;
};

type AgencyOpt = { id: number; name: string };

export default function AgencyEntitiesSection({ onChange }: { onChange?: (count: number) => void }) {
  const [rows, setRows] = useState<AgencyEntityRow[]>([]);
  const [agencies, setAgencies] = useState<AgencyOpt[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<AgencyEntityRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<AgencyEntityRow[]>("/agency-entities/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  const fetchAgencies = useCallback(async () => {
    try {
      const { data } = await api.get<AgencyOpt[]>("/agencies/", { params: { limit: 1000 } });
      setAgencies(data);
    } catch { setAgencies([]); }
  }, []);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);
  useEffect(() => { fetchAgencies(); }, [fetchAgencies]);

  const toggle = async (row: AgencyEntityRow) => {
    try {
      const { data } = await api.patch<AgencyEntityRow>(`/agency-entities/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this entity? This cannot be undone.")) return;
    try {
      await api.delete(`/agency-entities/${id}`);
      setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    } catch { alert("Delete failed."); }
  };

  return (
    <div className="space-y-3">
      <Toolbar label="Entity" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => { fetchAgencies(); setModal(null); }} onRefresh={fetchRows} loading={loading} />

      {agencies.length === 0 && !loading && (
        <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Tip: add an Agency first (Agency Info tab) so you can add entities under it.
        </p>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["AGENCY", "NAME", "CODE", "ADDRESS", "STATE", "CITY", "STATUS", "ACTIONS"].map(h => (
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
                <tr><td colSpan={8} className="px-4 py-12 text-center text-xs text-gray-400">No entities yet. Add one or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{r.agency_name || "—"}</td>
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
        <EntityModal entity={modal} agencies={agencies} onClose={() => setModal(false)} onSaved={() => { setModal(false); fetchRows(); }} onRefresh={fetchRows} />
      )}
    </div>
  );
}

type EntityDraft = { name: string; code: string; address: string; state: string; city: string; err?: string };
const emptyEntity = (): EntityDraft => ({ name: "", code: "", address: "", state: "", city: "" });

function EntityModal({
  entity, agencies, onClose, onSaved, onRefresh,
}: {
  entity: AgencyEntityRow | null;
  agencies: AgencyOpt[];
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
}) {
  const isEdit = !!entity;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // add-mode: pick the agency ONCE, then add many entity rows under it
  const [agencyId, setAgencyId] = useState<number | null>(null);
  const [rows, setRows] = useState<EntityDraft[]>([emptyEntity()]);
  const setRow = (i: number, patch: Partial<EntityDraft>) =>
    setRows(p => p.map((r, idx) => (idx === i ? { ...r, ...patch, err: undefined } : r)));
  const addRow = () => setRows(p => [...p, emptyEntity()]);
  const removeRow = (i: number) => setRows(p => (p.length > 1 ? p.filter((_, idx) => idx !== i) : p));
  const validCount = rows.filter(r => r.name.trim() && r.code.trim()).length;

  // edit-mode: single form
  const [form, setForm] = useState({
    agency_id: entity?.agency_id ?? null as number | null,
    name: entity?.name ?? "",
    code: entity?.code ?? "",
    address: entity?.address ?? "",
    state: entity?.state ?? "",
    city: entity?.city ?? "",
    is_active: entity?.is_active ?? true,
  });
  const set = (k: keyof typeof form, v: string | boolean | number | null) => setForm(p => ({ ...p, [k]: v }));

  const saveEdit = async () => {
    if (!form.agency_id) { setError("Please select the agency."); return; }
    if (!form.name.trim() || !form.code.trim()) { setError("Name and Code are required."); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/agency-entities/${entity!.id}`, { ...form, name: form.name.trim(), code: form.code.trim() });
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMany = async () => {
    if (!agencyId) { setError("Please select the agency."); return; }
    const drafts = rows.filter(r => r.name.trim() && r.code.trim());
    if (!drafts.length) { setError("Add at least one entity with a name and code."); return; }
    setSaving(true); setError("");
    const failed: EntityDraft[] = [];
    let created = 0;
    for (const r of drafts) {
      try {
        await api.post("/agency-entities/", {
          agency_id: agencyId,
          name: r.name.trim(),
          code: r.code.trim(),
          address: r.address || null,
          state: r.state || null,
          city: r.city || null,
          is_active: true,
        });
        created++;
      } catch (e) {
        failed.push({ ...r, err: apiError(e) });
      }
    }
    setSaving(false);
    if (failed.length === 0) {
      onSaved();
    } else {
      setRows(failed);
      setError(`${created} added, ${failed.length} failed — fix the highlighted rows and save again.`);
      if (created > 0) onRefresh();
    }
  };

  return (
    <ModalShell title={isEdit ? "Edit Entity" : "Add Entities"} onClose={onClose}>
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

      {isEdit ? (
        <div className="space-y-3">
          <div><label className={LABEL}>Agency *</label>
            <select value={form.agency_id ?? ""} onChange={e => set("agency_id", e.target.value ? Number(e.target.value) : null)} className={INPUT}>
              <option value="">— Select agency —</option>
              {agencies.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select></div>
          <div><label className={LABEL}>Entity Name *</label>
            <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Lords Delhi" className={INPUT} /></div>
          <div><label className={LABEL}>Code *</label>
            <input value={form.code} onChange={e => set("code", e.target.value)} placeholder="e.g. DEL-001" className={INPUT} /></div>
          <div><label className={LABEL}>Address</label>
            <input value={form.address} onChange={e => set("address", e.target.value)} placeholder="Street address" className={INPUT} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>State</label>
              <input value={form.state} onChange={e => set("state", e.target.value)} placeholder="e.g. Delhi" className={INPUT} /></div>
            <div><label className={LABEL}>City</label>
              <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. New Delhi" className={INPUT} /></div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
            <span className="text-xs font-semibold text-gray-600">Active</span>
          </label>

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={saveEdit} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>
      ) : tab === "manual" ? (
        <div className="space-y-3">
          {/* one agency for all the entities added below */}
          <div>
            <label className={LABEL}>Agency *</label>
            <select value={agencyId ?? ""} onChange={e => setAgencyId(e.target.value ? Number(e.target.value) : null)} className={INPUT}>
              <option value="">— Select agency —</option>
              {agencies.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <p className="text-[10px] text-gray-400 mt-1">All entities below are added under this one agency.</p>
          </div>

          <div className="space-y-2.5">
            {rows.map((r, i) => (
              <div key={i} className={`rounded-lg border p-3 space-y-2 ${r.err ? "border-red-300 bg-red-50/40" : "border-gray-200 bg-gray-50/50"}`}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Entity #{i + 1}</span>
                  {rows.length > 1 && (
                    <button onClick={() => removeRow(i)} className="p-1 hover:bg-red-100 rounded text-red-400 hover:text-red-600" title="Remove"><Trash2 className="w-3.5 h-3.5" /></button>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input value={r.name} onChange={e => setRow(i, { name: e.target.value })} placeholder="Entity Name *" className={INPUT} />
                  <input value={r.code} onChange={e => setRow(i, { code: e.target.value })} placeholder="Code *" className={INPUT} />
                </div>
                <input value={r.address} onChange={e => setRow(i, { address: e.target.value })} placeholder="Address" className={INPUT} />
                <div className="grid grid-cols-2 gap-2">
                  <input value={r.state} onChange={e => setRow(i, { state: e.target.value })} placeholder="State" className={INPUT} />
                  <input value={r.city} onChange={e => setRow(i, { city: e.target.value })} placeholder="City" className={INPUT} />
                </div>
                {r.err && <p className="text-[10px] text-red-500">{r.err}</p>}
              </div>
            ))}
          </div>

          <button onClick={addRow} className="flex items-center gap-1.5 text-xs font-semibold text-sky-600 hover:text-sky-800">
            <Plus className="w-3.5 h-3.5" /> Add another entity
          </button>

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={saveMany} disabled={saving || validCount === 0 || !agencyId} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : `Create ${validCount || ""} Entit${validCount === 1 ? "y" : "ies"}`.replace("  ", " ")}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="agency-entities" templateName="agency_entity_template.xlsx" columns="AGENCY, NAME, CODE, ADDRESS, STATE, CITY, ACTIVE" onDone={onSaved} />
      )}
    </ModalShell>
  );
}
