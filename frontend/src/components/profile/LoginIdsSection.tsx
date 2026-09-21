"use client";

// Reusable Login IDs / IATA manager (table + add/edit modal + xlsx upload), used by the
// onboarding wizard and My Profile. Every login ID belongs to one of the user's entities:
// the Add form picks the entity FIRST and then takes any number of login IDs under it.
//
// LOCATED BY ITS ENTITY. An IATA code is issued to an accredited location, so each login
// shows where it is — but only half of that is its own:
//   * STATE is always the entity's and is read-only. An entity is one GST registration and
//     a GSTIN belongs to one state, so an office in another state is another entity.
//   * CITY starts as the entity's and may be changed for an office in another city of the
//     same state. Left as the entity's, it is stored as "follows the entity" (NULL), so
//     correcting the entity's city later corrects every login that never overrode it.
//
// No Airline, LoB or Vendor any more — a login is identified by its entity alone. And the
// same Login ID / IATA may exist only once across ALL the user's entities: an IATA code
// belongs to one office of one entity, so a second copy is always a mistake.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Plus } from "lucide-react";
import api from "@/lib/api";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ManagedByAdminNote from "@/components/profile/ManagedByAdminNote";
import { getUser } from "@/lib/auth";
import { canManageWorkspace } from "@/lib/rbac";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

type EntityOpt = { id: number; name: string; code: string; state: string | null; city: string | null; is_active: boolean };

type LoginIdRowE = {
  id: number;
  login_id: string;
  entity_id: number | null;
  entity_name: string | null;
  entity_code: string | null;
  entity_state: string | null;   // the login's state — always its entity's
  city: string | null;           // the office's own city; null = the entity's
  entity_city: string | null;
  is_active: boolean;
};

const UPLOAD_COLUMNS = "LOGIN_ID, ENTITY_CODE, CITY, ACTIVE — LOGIN_ID and ENTITY_CODE required; blank CITY uses the entity's";
const READONLY = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none";

const lc = (s: string | null | undefined) => (s ?? "").trim().toLowerCase();
const entityLabel = (e: EntityOpt) => `${e.name} (${e.code})${e.is_active ? "" : " — inactive"}`;

export default function LoginIdsSection({ onChange }: { onChange?: (count: number) => void }) {
  const [rows, setRows] = useState<LoginIdRowE[]>([]);
  const [entities, setEntities] = useState<EntityOpt[]>([]);
  // Every login the user has, unfiltered by the search box — what the duplicate check in
  // the modal compares against.
  const [allRows, setAllRows] = useState<LoginIdRowE[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<LoginIdRowE | null | false>(false);
  const [pendingDelete, setPendingDelete] = useState<LoginIdRowE | null>(null);
  // Only the Super Admin changes login IDs. Everyone else sees those under the entities
  // granted to them, read-only — enforced by the server (backend services/entity_access).
  const manage = canManageWorkspace(getUser()?.role);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<LoginIdRowE[]>("/user-login-ids/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  const fetchAll = useCallback(async () => {
    try {
      const [{ data: logins }, { data: ents }] = await Promise.all([
        api.get<LoginIdRowE[]>("/user-login-ids/", { params: { limit: 1000 } }),
        api.get<EntityOpt[]>("/user-entities/", { params: { limit: 1000 } }),
      ]);
      setAllRows(logins);
      setEntities(ents);
    } catch { setAllRows([]); setEntities([]); }
  }, []);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const refresh = () => { fetchRows(); fetchAll(); };

  const toggle = async (row: LoginIdRowE) => {
    try {
      const { data } = await api.patch<LoginIdRowE>(`/user-login-ids/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  /** Runs inside the popup: it stays open with the error if the delete fails. */
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    await api.delete(`/user-login-ids/${id}`);
    setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    fetchAll();
  };

  const HEADERS = ["LOGIN ID / IATA", "ENTITY", "STATE", "CITY", "STATUS", ...(manage ? ["ACTIONS"] : [])];

  return (
    <div className="space-y-3">
      {!manage && (
        <ManagedByAdminNote>
          <strong>Managed by your Super Admin.</strong> These are the login IDs / IATA numbers of the entities
          assigned to you. To add or change one, ask your Super Admin.
        </ManagedByAdminNote>
      )}

      <Toolbar label="Login ID" count={rows.length} search={search} setSearch={setSearch}
        onAdd={manage ? () => setModal(null) : undefined} onRefresh={refresh} loading={loading} />

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
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">{manage ? "No login IDs yet. Add one or upload an XLS." : "No login IDs under the entities assigned to you yet."}</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800 font-mono">{r.login_id}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">
                    {/* Saved before an entity was required — edit to assign one. */}
                    {r.entity_id == null
                      ? <span className="text-amber-600">No entity</span>
                      : <>{r.entity_name} <span className="text-gray-400">({r.entity_code})</span></>}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.entity_state || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">
                    {r.city || r.entity_city || "—"}
                    {r.city && <span className="ml-1 text-[9px] text-sky-600" title="Differs from the entity's city">branch</span>}
                  </td>
                  <td className="px-3 py-2"><ActiveBadge active={r.is_active} onClick={manage ? () => toggle(r) : undefined} /></td>
                  {manage && <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                      <button onClick={() => setPendingDelete(r)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal !== false && (
        <LoginIdModal login={modal} entities={entities} existing={allRows}
          onClose={() => setModal(false)} onSaved={() => { setModal(false); refresh(); }} onRefresh={refresh} />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Delete login ID"
          confirmLabel="Delete login ID"
          onConfirm={confirmDelete}
          onClose={() => setPendingDelete(null)}
        >
          <p>
            Delete <span className="font-mono font-semibold text-gray-900">{pendingDelete.login_id}</span>
            {pendingDelete.entity_name
              ? <> from <span className="font-semibold text-gray-900">{pendingDelete.entity_name}</span> <span className="text-gray-400">({pendingDelete.entity_code})</span></>
              : null}
            ? This cannot be undone.
          </p>
          <p className="text-gray-400">The entity itself and its other login IDs are not affected.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

/** One login-ID row of the Add form. `city` null = follows the entity (the box shows the
 *  entity's city until someone types a different one). */
type DraftRow = { login_id: string; city: string | null; err?: string };

const emptyRow = (): DraftRow => ({ login_id: "", city: null });

/** "" or why this login ID is already taken — by a saved login, or by an earlier row of
 *  the same form. Case-blind, across every entity, the same rule as the server. */
function takenBy(value: string, existing: LoginIdRowE[], earlier: string[], selfId: number | null): string {
  const v = lc(value);
  if (!v) return "";
  const hit = existing.find(r => r.id !== selfId && lc(r.login_id) === v);
  if (hit) {
    return hit.entity_name
      ? `Already exists under '${hit.entity_name}' (${hit.entity_code}).`
      : "Already exists.";
  }
  if (earlier.some(e => lc(e) === v)) return "Repeated in this form.";
  return "";
}

function LoginIdModal({
  login, entities, existing, onClose, onSaved, onRefresh,
}: {
  login: LoginIdRowE | null;
  entities: EntityOpt[];
  existing: LoginIdRowE[];
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
}) {
  const isEdit = !!login;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // ── add mode: pick the entity ONCE, then add many login IDs under it ──────
  const [entityId, setEntityId] = useState<number | null>(null);
  const entity = entities.find(e => e.id === entityId) ?? null;
  const [rows, setRows] = useState<DraftRow[]>([emptyRow()]);
  const setRow = (i: number, patch: Partial<DraftRow>) =>
    setRows(p => p.map((r, idx) => (idx === i ? { ...r, ...patch, err: undefined } : r)));
  const addRow = () => setRows(p => [...p, emptyRow()]);
  const removeRow = (i: number) => setRows(p => (p.length > 1 ? p.filter((_, idx) => idx !== i) : p));
  const validCount = rows.filter(r => r.login_id.trim()).length;

  // ── edit mode: one login ──────────────────────────────────────────────────
  const [form, setForm] = useState({
    login_id: login?.login_id ?? "",
    entity_id: login?.entity_id ?? null as number | null,
    city: login?.city ?? null as string | null,
    is_active: login?.is_active ?? true,
  });
  const editEntity = entities.find(e => e.id === form.entity_id) ?? null;
  const editTaken = isEdit ? takenBy(form.login_id, existing, [], login!.id) : "";

  const saveEdit = async () => {
    if (!form.login_id.trim()) { setError("Login ID / IATA Number is required."); return; }
    if (form.entity_id == null) { setError("Entity is required."); return; }
    if (editTaken) { setError(`Login ID '${form.login_id.trim()}': ${editTaken}`); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/user-login-ids/${login!.id}`, {
        login_id: form.login_id.trim(),
        entity_id: form.entity_id,
        // The server stores a city equal to the entity's as "follows the entity".
        city: (form.city ?? "").trim() || null,
        is_active: form.is_active,
      });
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMany = async () => {
    if (entityId == null) { setError("Select the entity first."); return; }
    const drafts = rows.filter(r => r.login_id.trim());
    if (!drafts.length) { setError("Add at least one Login ID / IATA number."); return; }

    // Catch duplicates before any request, and say which row.
    const earlier: string[] = [];
    let dupFound = false;
    const checked = rows.map(r => {
      const taken = r.login_id.trim() ? takenBy(r.login_id, existing, earlier, null) : "";
      if (r.login_id.trim()) earlier.push(r.login_id);
      if (taken) dupFound = true;
      return taken ? { ...r, err: taken } : r;
    });
    if (dupFound) { setRows(checked); setError("Fix the highlighted login IDs."); return; }

    setSaving(true); setError("");
    const failed: DraftRow[] = [];
    let created = 0;
    for (const r of drafts) {
      try {
        await api.post("/user-login-ids/", {
          login_id: r.login_id.trim(),
          entity_id: entityId,
          city: (r.city ?? "").trim() || null,
          is_active: true,
        });
        created++;
      } catch (e) {
        failed.push({ ...r, err: apiError(e) });
      }
    }
    setSaving(false);
    if (failed.length === 0) {
      onSaved();                                  // all created → close + refresh
    } else {
      setRows(failed);                            // keep only the failed rows to fix
      setError(`${created} added, ${failed.length} failed — fix the highlighted rows and save again.`);
      if (created > 0) onRefresh();               // show the ones that succeeded behind the modal
    }
  };

  const entitySelect = (value: number | null, onPick: (id: number | null) => void) => (
    <select value={value ?? ""} onChange={e => onPick(e.target.value ? Number(e.target.value) : null)} className={INPUT}>
      <option value="">— Select entity —</option>
      {entities.map(en => <option key={en.id} value={en.id}>{entityLabel(en)}</option>)}
    </select>
  );

  return (
    <ModalShell title={isEdit ? "Edit Login ID" : "Add Login IDs"} onClose={onClose}>
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
          <div><label className={LABEL}>Login ID / IATA Number *</label>
            <input value={form.login_id} onChange={e => setForm(p => ({ ...p, login_id: e.target.value }))}
              placeholder="e.g. 14312345" className={`${INPUT} font-mono ${editTaken ? "border-red-300" : ""}`} />
            {editTaken && <p className="text-[10px] text-red-500 mt-1">{editTaken}</p>}
          </div>
          <div><label className={LABEL}>Entity *</label>
            {/* Moving a login to another entity resets its city to follow the new one. */}
            {entitySelect(form.entity_id, id => setForm(p => ({ ...p, entity_id: id, city: null })))}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>State</label>
              <input value={editEntity?.state ?? ""} readOnly placeholder="From the entity" title="Always the entity's state" className={READONLY} /></div>
            <div><label className={LABEL}>City</label>
              <input value={form.city ?? editEntity?.city ?? ""} onChange={e => setForm(p => ({ ...p, city: e.target.value }))}
                placeholder={editEntity ? "City" : "Select an entity"} disabled={!editEntity} className={INPUT} /></div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.is_active} onChange={e => setForm(p => ({ ...p, is_active: e.target.checked }))} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
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
          {/* 1. The entity — first, because every login below belongs to it and takes its
                 state (and, unless changed, its city) from it. */}
          <div>
            <label className={LABEL}>Entity *</label>
            {/* A city typed for the previous entity may not even be in the new one's
                state, so every row goes back to following the entity picked. */}
            {entitySelect(entityId, id => { setEntityId(id); setRows(p => p.map(r => ({ ...r, city: null, err: undefined }))); })}
            <p className="text-[10px] text-gray-400 mt-1">
              {entities.length === 0
                ? "Add an entity on the Entities tab first."
                : "All login IDs below are added under this one entity."}
            </p>
          </div>

          {/* 2. Its login IDs / IATA numbers. */}
          {entity && (
            <>
              <div className="space-y-2.5">
                {rows.map((r, i) => (
                  <div key={i} className={`rounded-lg border p-3 space-y-2 ${r.err ? "border-red-300 bg-red-50/40" : "border-gray-200 bg-gray-50/50"}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Login ID #{i + 1}</span>
                      {rows.length > 1 && (
                        <button onClick={() => removeRow(i)} className="p-1 hover:bg-red-100 rounded text-red-400 hover:text-red-600" title="Remove"><Trash2 className="w-3.5 h-3.5" /></button>
                      )}
                    </div>
                    <div><label className={LABEL}>Login ID / IATA Number *</label>
                      <input value={r.login_id} onChange={e => setRow(i, { login_id: e.target.value })}
                        placeholder="e.g. 14312345" className={`${INPUT} font-mono`} /></div>
                    <div className="grid grid-cols-2 gap-2">
                      <div><label className={LABEL}>State</label>
                        <input value={entity.state ?? ""} readOnly placeholder="—" title="Always the entity's state" className={READONLY} /></div>
                      <div><label className={LABEL}>City</label>
                        <input value={r.city ?? entity.city ?? ""} onChange={e => setRow(i, { city: e.target.value })}
                          placeholder="City" className={INPUT} /></div>
                    </div>
                    {r.err && <p className="text-[10px] text-red-500">{r.err}</p>}
                  </div>
                ))}
              </div>

              <p className="text-[10px] text-gray-400">
                State is the entity&apos;s. City starts as the entity&apos;s — change it only for an office in another city of {entity.state || "the same state"}.
              </p>

              <button onClick={addRow} className="flex items-center gap-1.5 text-xs font-semibold text-sky-600 hover:text-sky-800">
                <Plus className="w-3.5 h-3.5" /> Add another login ID
              </button>
            </>
          )}

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={saveMany} disabled={saving || !entity || validCount === 0} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : `Create ${validCount || ""} Login ID${validCount === 1 ? "" : "s"}`.replace("  ", " ")}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="user-login-ids" templateName="user_login_id_template.xlsx" columns={UPLOAD_COLUMNS} onDone={onSaved} />
      )}
    </ModalShell>
  );
}
