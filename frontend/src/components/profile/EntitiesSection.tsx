"use client";

// Reusable Entities manager (table + add/edit modal + xlsx upload) used by the
// onboarding wizard and the My Profile page. Mirrors the User Master → Entity
// page but with no page-level heading so it can be embedded.
//
// Adding supports several entities in one submit ("+ Add another"); editing is
// always a single entity.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Plus, X } from "lucide-react";
import api from "@/lib/api";
import {
  type EntityRow, type BulkCreateResult, INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

const UPLOAD_COLUMNS = "NAME, CODE, ADDRESS, STATE, CITY, GST_NUMBER, PAN_NUMBER, ACTIVE";

export default function EntitiesSection({ onChange }: { onChange?: (count: number) => void }) {
  const [rows, setRows] = useState<EntityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<EntityRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<EntityRow[]>("/user-entities/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);

  const toggle = async (row: EntityRow) => {
    try {
      const { data } = await api.patch<EntityRow>(`/user-entities/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this entity? This cannot be undone.")) return;
    try {
      await api.delete(`/user-entities/${id}`);
      setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    } catch { alert("Delete failed."); }
  };

  const HEADERS = ["NAME", "CODE", "ADDRESS", "STATE", "CITY", "GST NO.", "PAN NO.", "STATUS", "ACTIONS"];

  return (
    <div className="space-y-3">
      <Toolbar label="Entity" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => setModal(null)} onRefresh={fetchRows} loading={loading} />

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {HEADERS.map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">No entities yet. Add one or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.code}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.address || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.state || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.city || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600 font-mono">{r.gst_number || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600 font-mono">{r.pan_number || "—"}</td>
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

// ── Add / Edit ──────────────────────────────────────────────────────────────

type Draft = {
  name: string; code: string; address: string; state: string; city: string;
  gst_number: string; pan_number: string; is_active: boolean;
};

const blank = (): Draft => ({
  name: "", code: "", address: "", state: "", city: "",
  gst_number: "", pan_number: "", is_active: true,
});

const fromEntity = (e: EntityRow): Draft => ({
  name: e.name ?? "", code: e.code ?? "", address: e.address ?? "",
  state: e.state ?? "", city: e.city ?? "",
  gst_number: e.gst_number ?? "", pan_number: e.pan_number ?? "",
  is_active: e.is_active,
});

/** Trim, and send blank optional fields as null rather than "". */
const toPayload = (d: Draft) => ({
  name: d.name.trim(),
  code: d.code.trim(),
  address: d.address.trim() || null,
  state: d.state.trim() || null,
  city: d.city.trim() || null,
  gst_number: d.gst_number.trim().toUpperCase() || null,
  pan_number: d.pan_number.trim().toUpperCase() || null,
  is_active: d.is_active,
});

function EntityModal({ entity, onClose, onSaved }: { entity: EntityRow | null; onClose: () => void; onSaved: () => void }) {
  const isEdit = !!entity;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [drafts, setDrafts] = useState<Draft[]>([entity ? fromEntity(entity) : blank()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<string[]>([]);

  const set = (i: number, k: keyof Draft, v: string | boolean) =>
    setDrafts(p => p.map((d, idx) => idx === i ? { ...d, [k]: v } : d));
  const addDraft = () => setDrafts(p => [...p, blank()]);
  const removeDraft = (i: number) => setDrafts(p => p.filter((_, idx) => idx !== i));

  const save = async () => {
    setError(""); setRowErrors([]);

    const missing = drafts.findIndex(d => !d.name.trim() || !d.code.trim());
    if (missing !== -1) {
      setError(
        drafts.length === 1
          ? "Name and Code are required."
          : `Entity ${missing + 1}: Name and Code are required.`,
      );
      return;
    }

    setSaving(true);
    try {
      if (isEdit && entity) {
        await api.patch(`/user-entities/${entity.id}`, toPayload(drafts[0]));
        onSaved();
        return;
      }
      if (drafts.length === 1) {
        await api.post("/user-entities/", toPayload(drafts[0]));
        onSaved();
        return;
      }
      // Several at once: valid rows are saved even if some are rejected, so keep
      // the modal open and report exactly which ones need fixing.
      const { data } = await api.post<BulkCreateResult>("/user-entities/bulk", {
        entities: drafts.map(toPayload),
      });
      if (data.failed === 0) { onSaved(); return; }
      setRowErrors(data.errors);
      setError(`${data.success} of ${data.total} entities added — fix the rest below.`);
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell
      title={isEdit ? "Edit Entity" : drafts.length > 1 ? `Add Entities (${drafts.length})` : "Add Entity"}
      onClose={onClose}
      wide={!isEdit && tab === "manual"}
    >
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
          {drafts.map((form, i) => (
            <div key={i} className={drafts.length > 1 ? "border border-gray-200 rounded-xl p-3 space-y-3 relative bg-gray-50/50" : "space-y-3"}>
              {drafts.length > 1 && (
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-sky-700">Entity {i + 1}</span>
                  <button onClick={() => removeDraft(i)} title="Remove this entity"
                    className="p-1 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div><label className={LABEL}>Entity Name *</label>
                  <input value={form.name} onChange={e => set(i, "name", e.target.value)} placeholder="e.g. Acme Travels Pvt Ltd" className={INPUT} /></div>
                <div><label className={LABEL}>Code *</label>
                  <input value={form.code} onChange={e => set(i, "code", e.target.value)} placeholder="e.g. ENT-001" className={INPUT} /></div>
              </div>

              <div><label className={LABEL}>Address</label>
                <input value={form.address} onChange={e => set(i, "address", e.target.value)} placeholder="Street address" className={INPUT} /></div>

              <div className="grid grid-cols-2 gap-3">
                <div><label className={LABEL}>State</label>
                  <input value={form.state} onChange={e => set(i, "state", e.target.value)} placeholder="e.g. Maharashtra" className={INPUT} /></div>
                <div><label className={LABEL}>City</label>
                  <input value={form.city} onChange={e => set(i, "city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} /></div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div><label className={LABEL}>GST Number</label>
                  <input value={form.gst_number} onChange={e => set(i, "gst_number", e.target.value.toUpperCase())}
                    placeholder="22ABCDE1234F1Z5" maxLength={15} className={`${INPUT} font-mono`} /></div>
                <div><label className={LABEL}>PAN Number</label>
                  <input value={form.pan_number} onChange={e => set(i, "pan_number", e.target.value.toUpperCase())}
                    placeholder="ABCDE1234F" maxLength={10} className={`${INPUT} font-mono`} /></div>
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={form.is_active} onChange={e => set(i, "is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
                <span className="text-xs font-semibold text-gray-600">Active</span>
              </label>
            </div>
          ))}

          {!isEdit && (
            <button onClick={addDraft} type="button"
              className="w-full flex items-center justify-center gap-1.5 border border-dashed border-sky-300 text-sky-600 rounded-lg py-2 text-xs font-semibold hover:bg-sky-50">
              <Plus className="w-3.5 h-3.5" /> Add another entity
            </button>
          )}

          {error && <p className="text-[11px] text-red-500">{error}</p>}
          {rowErrors.length > 0 && (
            <div className="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 space-y-0.5">
              {rowErrors.map((er, i) => <p key={i} className="text-[10px] text-red-500">{er}</p>)}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={save} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : isEdit ? "Save Changes" : drafts.length > 1 ? `Create ${drafts.length} Entities` : "Create Entity"}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="user-entities" templateName="user_entity_template.xlsx" columns={UPLOAD_COLUMNS} onDone={onSaved} />
      )}
    </ModalShell>
  );
}
