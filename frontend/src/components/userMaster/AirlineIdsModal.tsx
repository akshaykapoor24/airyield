"use client";

// User Master → Airline Master → the ids for ONE airline.
//
// A tenant normally holds several agent-portal ids per carrier — five Indigo logins
// across offices is ordinary — so this manages a list, not a single field. The
// airline's own columns (code / IATA numeric / contract year) are the platform
// admin's and shown read-only; changing them is a System master update request
// (/masters/airlines). The only thing typed here is the user's own id.
//
// New ids go through POST /tenant-airlines/bulk in one save, so a duplicate in the
// third row does not throw away the other four the user typed — the failures come
// back per id to be corrected in place.

import { useState } from "react";
import { Check, Plus, Trash2, X } from "lucide-react";
import api from "@/lib/api";
import {
  type AirlineCatalogEntry, type TenantAirlineIdRow,
  ActiveBadge, INPUT, LABEL, ModalShell, apiError,
} from "@/components/userMaster/shared";

type BulkError = { ref_id: string; error: string };
// `created` is TenantAirlineRead — the id row as stored. The two grid-only fields
// (in_use_count, snapshot_name_drifted) are known for a row just created.
type CreatedId = { id: number; ref_id: string; is_active: boolean };
type BulkResult = { created: CreatedId[]; errors: BulkError[] };

/** A row being typed. `err` is the server's reason after a partial save. */
type Draft = { ref_id: string; err?: string };

const emptyDraft = (): Draft => ({ ref_id: "" });

export default function AirlineIdsModal({
  entry, onClose, onChanged,
}: {
  entry: AirlineCatalogEntry;
  onClose: () => void;
  /** Called after any successful change so the grid behind can refresh. */
  onChanged: () => void;
}) {
  // Seeded from the grid, then owned here: the modal covers the grid while it is
  // open, so re-reading the parent's prop mid-edit would only clobber typing.
  const [ids, setIds] = useState<TenantAirlineIdRow[]>(entry.ids);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [drafts, setDrafts] = useState<Draft[]>([emptyDraft()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const setDraft = (i: number, ref_id: string) =>
    setDrafts(p => p.map((d, idx) => (idx === i ? { ref_id, err: undefined } : d)));
  const addDraft = () => setDrafts(p => [...p, emptyDraft()]);
  const removeDraft = (i: number) =>
    setDrafts(p => (p.length > 1 ? p.filter((_, idx) => idx !== i) : [emptyDraft()]));
  const validCount = drafts.filter(d => d.ref_id.trim()).length;

  const changed = (row: TenantAirlineIdRow) =>
    edits[row.id] !== undefined && edits[row.id].trim() !== row.ref_id;

  const saveRename = async (row: TenantAirlineIdRow) => {
    const next = (edits[row.id] ?? "").trim();
    if (!next) { setError("An id cannot be blank."); return; }
    setBusy(true); setError("");
    try {
      await api.patch(`/tenant-airlines/${row.id}`, { ref_id: next });
      setIds(p => p.map(r => (r.id === row.id ? { ...r, ref_id: next } : r)));
      setEdits(p => { const n = { ...p }; delete n[row.id]; return n; });
      onChanged();
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };

  const toggle = async (row: TenantAirlineIdRow) => {
    setBusy(true); setError("");
    try {
      await api.patch(`/tenant-airlines/${row.id}`, { is_active: !row.is_active });
      setIds(p => p.map(r => (r.id === row.id ? { ...r, is_active: !r.is_active } : r)));
      onChanged();
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };

  const remove = async (row: TenantAirlineIdRow) => {
    if (!confirm(`Remove the id "${row.ref_id}" from ${entry.name}?`)) return;
    setBusy(true); setError("");
    try {
      await api.delete(`/tenant-airlines/${row.id}`);
      setIds(p => p.filter(r => r.id !== row.id));
      onChanged();
    } catch (e) {
      // The 409 already explains that the id is on uploaded statements and should
      // be deactivated instead — show it as-is rather than paraphrasing.
      setError(apiError(e));
    } finally { setBusy(false); }
  };

  const addAll = async () => {
    const wanted = drafts.filter(d => d.ref_id.trim());
    if (!wanted.length) { setError("Enter at least one id."); return; }
    setBusy(true); setError("");
    try {
      const { data } = await api.post<BulkResult>("/tenant-airlines/bulk", {
        airline_id: entry.airline_id,
        ids: wanted.map(d => ({ ref_id: d.ref_id.trim(), is_active: true })),
      });
      const created = data.created ?? [];
      const failed = data.errors ?? [];
      if (created.length) {
        setIds(p => [...p, ...created.map(c => ({
          ...c, in_use_count: 0, snapshot_name_drifted: false,
        }))].sort((a, b) => a.ref_id.localeCompare(b.ref_id)));
        onChanged();
      }
      if (!failed.length) {
        setDrafts([emptyDraft()]);
      } else {
        // Keep only what failed, each carrying its reason, so the user fixes those
        // rows instead of retyping the ones that landed.
        setDrafts(failed.map(f => ({ ref_id: f.ref_id, err: f.error })));
        setError(`${created.length} added, ${failed.length} not — fix the rows below.`);
      }
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };

  return (
    <ModalShell title={`IDs — ${entry.name}${entry.iata_code ? ` (${entry.iata_code})` : ""}`} onClose={onClose}>
      <div className="space-y-3">
        {/* Owned by the platform airline master, shown for confirmation only. */}
        <div className="grid grid-cols-3 gap-2 rounded-lg border border-gray-100 bg-gray-50/70 p-2.5">
          {[
            ["Code", entry.iata_code],
            ["IATA Numeric", entry.iata_numeric_code],
            ["Contract Year", entry.contract_year],
          ].map(([label, value]) => (
            <div key={label as string}>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{value || "—"}</p>
            </div>
          ))}
        </div>

        {/* ── Ids already saved ───────────────────────────────────────────── */}
        {ids.length > 0 && (
          <div>
            <label className={LABEL}>Your IDs ({ids.length})</label>
            <div className="space-y-2">
              {ids.map(row => (
                <div key={row.id} className="flex items-center gap-2">
                  <input
                    value={edits[row.id] ?? row.ref_id}
                    onChange={e => setEdits(p => ({ ...p, [row.id]: e.target.value }))}
                    onKeyDown={e => { if (e.key === "Enter" && changed(row)) saveRename(row); }}
                    className={`${INPUT} flex-1 ${row.is_active ? "" : "text-gray-400"}`}
                  />
                  {changed(row) ? (
                    <button
                      onClick={() => saveRename(row)} disabled={busy}
                      className="p-1.5 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 disabled:opacity-50"
                      title="Save this id"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <span className="w-7.5 shrink-0" />
                  )}
                  <ActiveBadge active={row.is_active} onClick={() => toggle(row)} />
                  <button
                    onClick={() => remove(row)} disabled={busy}
                    className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600 disabled:opacity-50"
                    title={row.in_use_count
                      ? `Used by ${row.in_use_count} statement(s) — deactivate instead`
                      : "Remove this id"}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
            {ids.some(r => r.in_use_count > 0) && (
              <p className="text-[10px] text-gray-400 mt-1.5">
                An id already used by an uploaded statement can&apos;t be removed — deactivate it
                instead, which hides it from new uploads and leaves those statements intact.
              </p>
            )}
          </div>
        )}

        {/* ── New ids ─────────────────────────────────────────────────────── */}
        <div>
          <label className={LABEL}>{ids.length ? "Add more IDs" : "Add your first ID"}</label>
          <div className="space-y-2">
            {drafts.map((d, i) => (
              <div key={i}>
                <div className="flex items-center gap-2">
                  <input
                    value={d.ref_id}
                    onChange={e => setDraft(i, e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") addDraft(); }}
                    placeholder={`e.g. ${entry.iata_code}-DEL-88213`}
                    className={`${INPUT} flex-1 ${d.err ? "border-red-300 bg-red-50/40" : ""}`}
                  />
                  <button
                    onClick={() => removeDraft(i)}
                    className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600"
                    title="Clear this row"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                {d.err && <p className="text-[10px] text-red-500 mt-1">{d.err}</p>}
              </div>
            ))}
          </div>
          <button onClick={addDraft} className="flex items-center gap-1.5 text-xs font-semibold text-sky-600 hover:text-sky-800 mt-2">
            <Plus className="w-3.5 h-3.5" /> Add another ID
          </button>
          <p className="text-[10px] text-gray-400 mt-1.5">
            An ID must be unique across your whole account — it&apos;s what you pick when uploading
            an LCC statement, and the file itself doesn&apos;t name the airline.
          </p>
        </div>

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-3 pt-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            Done
          </button>
          <button
            onClick={addAll}
            disabled={busy || validCount === 0}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
          >
            {busy ? "Saving…" : `Add ${validCount || ""} ID${validCount === 1 ? "" : "s"}`.replace("  ", " ")}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
