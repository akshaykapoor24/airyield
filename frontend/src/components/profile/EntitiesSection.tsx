"use client";

// Reusable Entities manager (table + add/edit modal + xlsx upload) used by the
// onboarding wizard and the My Profile page. Mirrors the User Master → Entity
// page but with no page-level heading so it can be embedded.
//
// Adding supports several entities in one submit ("+ Add another"); editing is
// always a single entity.
//
// STATE, PAN AND GST ARE REQUIRED, and asked in the order they can be checked: the
// state fixes a GSTIN's first two characters and the PAN fixes characters 3 to 12, so
// by the time the GSTIN box is filled there is something to compare it against — the
// same order and the same lib/indiaTax checks as Agency Master. The server repeats every
// check (api/v1/user_entities.py::entity_problem); these are here to point at the box
// that is wrong before a round trip.
//
// A DUPLICATE IS THE SAME CODE (ignoring case) OR THE SAME GSTIN — never the name, since
// a group's entities often share one ("yatra" TSI / YOL / MICE), and never the PAN, since
// one PAN holds a GSTIN in each state it registers in.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Plus, X } from "lucide-react";
import api from "@/lib/api";
import SearchSelect from "@/components/ui/SearchSelect";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ManagedByAdminNote from "@/components/profile/ManagedByAdminNote";
import { getUser } from "@/lib/auth";
import { canManageWorkspace } from "@/lib/rbac";
import {
  STATE_NAMES, canonicalState, gstinError, gstinPlaceholder, gstinTypingError,
  normaliseTaxId, panError, panTypingError,
} from "@/lib/indiaTax";
import {
  type EntityRow, type BulkCreateResult, INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

const UPLOAD_COLUMNS = "NAME, CODE, ADDRESS, STATE, CITY, GST_NUMBER, PAN_NUMBER, ACTIVE — STATE, GST and PAN required";

export default function EntitiesSection({ onChange }: { onChange?: (count: number) => void }) {
  const [rows, setRows] = useState<EntityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<EntityRow | null | false>(false);
  // Every entity the user has, unfiltered — the duplicate checks in the modal must see
  // them all, not just whatever the search box is currently showing.
  const [allRows, setAllRows] = useState<EntityRow[]>([]);
  // The entity awaiting delete confirmation, and the login IDs that go with it — loaded
  // when the popup opens, so it can say exactly what will be removed (null = still loading).
  const [pendingDelete, setPendingDelete] = useState<EntityRow | null>(null);
  const [pendingLogins, setPendingLogins] = useState<string[] | null>(null);
  // Only the Super Admin adds, edits, deletes or toggles entities. Everyone else gets the
  // entities granted to them in User management, read-only — the server enforces both
  // (backend services/entity_access); this only decides what the screen offers.
  const manage = canManageWorkspace(getUser()?.role);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<EntityRow[]>("/user-entities/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  const fetchAll = useCallback(async () => {
    try {
      const { data } = await api.get<EntityRow[]>("/user-entities/", { params: { limit: 1000 } });
      setAllRows(data);
    } catch { setAllRows([]); }
  }, []);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const toggle = async (row: EntityRow) => {
    try {
      const { data } = await api.patch<EntityRow>(`/user-entities/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const askDelete = (row: EntityRow) => {
    setPendingDelete(row);
    setPendingLogins(null);
    api.get<{ login_id: string }[]>("/user-login-ids/", { params: { entity_id: row.id, limit: 1000 } })
      .then(r => setPendingLogins(r.data.map(l => l.login_id)))
      .catch(() => setPendingLogins([]));
  };

  /** Runs inside the popup: it stays open with the error if the delete fails. The server
   *  deletes the entity's login IDs in the same transaction (api/v1/user_entities.py). */
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    await api.delete(`/user-entities/${id}`);
    setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    fetchAll();
  };

  const HEADERS = ["NAME", "CODE", "ADDRESS", "STATE", "CITY", "GST NO.", "PAN NO.", "STATUS", ...(manage ? ["ACTIONS"] : [])];

  /** An entity saved before GST and PAN were required shows it, rather than a quiet
   *  dash that reads as "not applicable" — the next edit will ask for them. */
  const taxCell = (v: string | null | undefined) =>
    v ? <span className="font-mono">{v}</span> : <span className="text-amber-600">Not entered</span>;

  return (
    <div className="space-y-3">
      {!manage && (
        <ManagedByAdminNote>
          <strong>Managed by your Super Admin.</strong> These are the entities assigned to you in User management.
          You can use them on deals and statements; to add or change one, ask your Super Admin.
        </ManagedByAdminNote>
      )}

      <Toolbar label="Entity" count={rows.length} search={search} setSearch={setSearch}
        onAdd={manage ? () => setModal(null) : undefined} onRefresh={() => { fetchRows(); fetchAll(); }} loading={loading} />

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
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">{manage ? "No entities yet. Add one or upload an XLS." : "No entities have been assigned to you yet — ask your Super Admin."}</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.code}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.address || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.state || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.city || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{taxCell(r.gst_number)}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{taxCell(r.pan_number)}</td>
                  <td className="px-3 py-2"><ActiveBadge active={r.is_active} onClick={manage ? () => toggle(r) : undefined} /></td>
                  {manage && <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                      <button onClick={() => askDelete(r)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal !== false && (
        <EntityModal entity={modal} existing={allRows} onClose={() => setModal(false)}
          onSaved={() => { setModal(false); fetchRows(); fetchAll(); }} />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Delete entity"
          confirmLabel={pendingLogins?.length ? `Delete entity + ${pendingLogins.length} login ID${pendingLogins.length === 1 ? "" : "s"}` : "Delete entity"}
          onConfirm={confirmDelete}
          onClose={() => { setPendingDelete(null); setPendingLogins(null); }}
        >
          <p>
            Delete <span className="font-semibold text-gray-900">{pendingDelete.name}</span>{" "}
            <span className="text-gray-400">({pendingDelete.code})</span>? This cannot be undone.
          </p>
          <LoginsGoingWith logins={pendingLogins} />
        </ConfirmDialog>
      )}
    </div>
  );
}

/** What the Delete popup says about the entity's login IDs — they are deleted with it,
 *  so they are listed rather than summarised. Capped so a long list cannot push the
 *  buttons off screen. */
function LoginsGoingWith({ logins }: { logins: string[] | null }) {
  if (logins === null) {
    return <p className="text-gray-400 flex items-center gap-1.5"><RefreshCw className="w-3 h-3 animate-spin" /> Checking its login IDs…</p>;
  }
  if (logins.length === 0) {
    return <p className="text-gray-400">It has no login IDs / IATA numbers.</p>;
  }
  const SHOWN = 8;
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
      <p className="text-red-700 font-semibold">
        Its {logins.length} login ID{logins.length === 1 ? "" : "s"} / IATA number{logins.length === 1 ? "" : "s"} will be deleted too:
      </p>
      <p className="mt-1 font-mono text-[11px] text-red-600 break-words">
        {logins.slice(0, SHOWN).join(", ")}
        {logins.length > SHOWN && <span className="font-sans"> and {logins.length - SHOWN} more</span>}
      </p>
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
  // Through canonicalState so a row stored as "delhi" selects the "Delhi" the picker
  // offers, instead of opening with an empty State box.
  state: canonicalState(e.state) || "", city: e.city ?? "",
  gst_number: e.gst_number ?? "", pan_number: e.pan_number ?? "",
  is_active: e.is_active,
});

/** Trim, and send blank optional fields as null rather than "". */
const toPayload = (d: Draft) => ({
  name: d.name.trim(),
  code: d.code.trim(),
  address: d.address.trim() || null,
  state: d.state || null,
  city: d.city.trim() || null,
  gst_number: normaliseTaxId(d.gst_number) || null,
  pan_number: normaliseTaxId(d.pan_number) || null,
  is_active: d.is_active,
});

const lc = (s: string | null | undefined) => (s ?? "").trim().toLowerCase();

/** The first thing wrong with one draft, or "" — required fields, the tax cross-checks,
 *  then duplicates against the saved entities and against the drafts before it. */
function draftProblem(d: Draft, i: number, drafts: Draft[], existing: EntityRow[], selfId: number | null): string {
  if (!d.name.trim()) return "Entity Name is required.";
  if (!d.code.trim()) return "Code is required.";
  if (!d.state) return "State is required — the GSTIN's first two characters are checked against it.";
  const pan = normaliseTaxId(d.pan_number);
  const gst = normaliseTaxId(d.gst_number);
  if (!pan) return "PAN Number is required.";
  if (!gst) return "GST Number is required.";
  const taxProblem = panError(pan) || gstinError(gst, { pan, state: d.state });
  if (taxProblem) return taxProblem;
  return duplicateOf(d, i, drafts, existing, selfId);
}

/** "" or why this draft duplicates something — Code (ignoring case) or GSTIN. */
function duplicateOf(d: Draft, i: number, drafts: Draft[], existing: EntityRow[], selfId: number | null): string {
  const code = lc(d.code);
  const gst = normaliseTaxId(d.gst_number);
  const others = existing.filter(e => e.id !== selfId);
  if (code) {
    const hit = others.find(e => lc(e.code) === code);
    if (hit) return `Code '${d.code.trim()}' is already used by '${hit.name}' (${hit.code}).`;
    if (drafts.slice(0, i).some(o => lc(o.code) === code)) return `Code '${d.code.trim()}' is repeated in this form.`;
  }
  if (gst) {
    const hit = others.find(e => (e.gst_number ?? "") === gst);
    if (hit) return `GSTIN ${gst} is already registered to '${hit.name}' (${hit.code}).`;
    if (drafts.slice(0, i).some(o => normaliseTaxId(o.gst_number) === gst)) return `GSTIN ${gst} is repeated in this form.`;
  }
  return "";
}

function EntityModal({ entity, existing, onClose, onSaved }: {
  entity: EntityRow | null; existing: EntityRow[]; onClose: () => void; onSaved: () => void;
}) {
  const isEdit = !!entity;
  const selfId = entity?.id ?? null;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [drafts, setDrafts] = useState<Draft[]>([entity ? fromEntity(entity) : blank()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<string[]>([]);
  // Missing fields are outlined only after a save attempt — a fresh form is empty, not wrong.
  const [tried, setTried] = useState(false);

  const set = (i: number, k: keyof Draft, v: string | boolean) =>
    setDrafts(p => p.map((d, idx) => idx === i ? { ...d, [k]: v } : d));
  const addDraft = () => setDrafts(p => [...p, blank()]);
  const removeDraft = (i: number) => setDrafts(p => p.filter((_, idx) => idx !== i));

  const save = async () => {
    setError(""); setRowErrors([]); setTried(true);

    for (let i = 0; i < drafts.length; i++) {
      const problem = draftProblem(drafts[i], i, drafts, existing, selfId);
      if (problem) {
        setError(drafts.length === 1 ? problem : `Entity ${i + 1}: ${problem}`);
        return;
      }
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
          {isEdit && entity && (!entity.gst_number || !entity.pan_number) && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              This entity was saved before GST and PAN were required — add both to save your changes.
            </p>
          )}

          {drafts.map((form, i) => {
            // Live, per-box feedback. The *Typing* checks stay quiet until a value is long
            // enough to judge; the strict ones run again on save (draftProblem).
            const panProblem = panTypingError(form.pan_number);
            const gstProblem = gstinTypingError(form.gst_number, {
              pan: panProblem ? "" : form.pan_number, state: form.state,
            });
            const dup = duplicateOf(form, i, drafts, existing, selfId);
            const codeDup = dup.startsWith("Code") ? dup : "";
            const gstDup = dup.startsWith("GSTIN") ? dup : "";
            const missing = (v: string) => tried && !v.trim();

            return (
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
                    <input value={form.name} onChange={e => set(i, "name", e.target.value)} placeholder="e.g. Acme Travels Pvt Ltd"
                      className={`${INPUT} ${missing(form.name) ? "border-red-300" : ""}`} /></div>
                  <div><label className={LABEL}>Code *</label>
                    <input value={form.code} onChange={e => set(i, "code", e.target.value)} placeholder="e.g. ENT-001"
                      className={`${INPUT} ${codeDup || missing(form.code) ? "border-red-300" : ""}`} />
                    {codeDup && <p className="text-[10px] text-red-500 mt-1">{codeDup}</p>}
                  </div>
                </div>

                <div><label className={LABEL}>Address</label>
                  <input value={form.address} onChange={e => set(i, "address", e.target.value)} placeholder="Street address" className={INPUT} /></div>

                <div className="grid grid-cols-2 gap-3">
                  <div><label className={LABEL}>State *</label>
                    <SearchSelect value={form.state} options={STATE_NAMES} onChange={v => set(i, "state", v)}
                      placeholder="Select state" invalid={tried && !form.state} />
                  </div>
                  <div><label className={LABEL}>City</label>
                    <input value={form.city} onChange={e => set(i, "city", e.target.value)} placeholder="e.g. Mumbai" className={INPUT} /></div>
                </div>

                {/* PAN before GST: the PAN is what characters 3-12 of the GSTIN are
                    checked against, so it has to be there first. */}
                <div className="grid grid-cols-2 gap-3">
                  <div><label className={LABEL}>PAN Number *</label>
                    <input value={form.pan_number} onChange={e => set(i, "pan_number", e.target.value.toUpperCase())}
                      placeholder="ABCDE1234F" maxLength={10}
                      className={`${INPUT} font-mono ${panProblem || missing(form.pan_number) ? "border-red-300" : ""}`} />
                    {panProblem && <p className="text-[10px] text-red-500 mt-1">{panProblem}</p>}
                  </div>
                  <div><label className={LABEL}>GST Number *</label>
                    <input value={form.gst_number} onChange={e => set(i, "gst_number", e.target.value.toUpperCase())}
                      placeholder={gstinPlaceholder(form.state, form.pan_number)} maxLength={15}
                      className={`${INPUT} font-mono ${gstProblem || gstDup || missing(form.gst_number) ? "border-red-300" : ""}`} />
                    {(gstProblem || gstDup) && <p className="text-[10px] text-red-500 mt-1">{gstProblem || gstDup}</p>}
                  </div>
                </div>
                <p className="text-[10px] text-gray-400 -mt-1">
                  The GSTIN is checked against the state (first two digits) and the PAN (characters 3 to 12).
                </p>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={form.is_active} onChange={e => set(i, "is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
                  <span className="text-xs font-semibold text-gray-600">Active</span>
                </label>
              </div>
            );
          })}

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
