"use client";

// Agency Login IDs / IATA manager for Agency Profile → Agency Onboarding. Each
// login id belongs to one agency and optionally to one of that agency's entities
// (one entity -> many login ids). In add-mode you pick the agency + entity once,
// then add many login-id rows under them.

import { useState, useEffect, useCallback } from "react";
import { Edit2, Trash2, RefreshCw, Plus } from "lucide-react";
import api from "@/lib/api";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

type AirlineOpt = { id: number; name: string; iata_code: string };
type AgencyOpt = { id: number; name: string; branch_name: string | null; branch_code: string; channels: string };

/** Label an agency by branch AND channel — a vendor is onboarded once per branch
 *  and once per channel, and a credential belongs to exactly one of those rows. */
const agencyLabel = (a: AgencyOpt) => `${a.name} — ${a.branch_name || a.branch_code} · ${a.channels}`;

/** A credential belongs to exactly ONE channel, never both. */
const CHANNELS = ["GDS", "LCC"] as const;
type Channel = (typeof CHANNELS)[number];

/** Which channels this agency has credentials for. */
const channelsFor = (channels: string | undefined): Channel[] =>
  channels === "BOTH" ? ["GDS", "LCC"] : channels === "GDS" || channels === "LCC" ? [channels] : [];

/** The credential is one column, relabelled by channel. */
const credentialLabel = (ch: Channel | "") =>
  ch === "GDS" ? "Mirror ID" : ch === "LCC" ? "Login ID / Airline ID" : "Login ID";
type EntityOpt = { id: number; name: string; code: string };
// Line of business. A DIFFERENT axis from GDS/LCC and deliberately not merged
// with it — an agency can sell B2B on both channels.
const LOB_OPTIONS = ["B2B", "B2C", "B2E", "MICE"];

type LoginIdRowA = {
  id: number;
  login_id: string;
  airline_name: string | null;
  airline_code: string | null;
  lob: string | null;
  vendor_id: number | null;
  vendor_name: string | null;
  agency_id: number;
  agency_name: string | null;
  channel: string;                 // GDS | LCC
  entity_id: number | null;
  entity_name: string | null;
  entity_code: string | null;
  is_active: boolean;
};

export default function AgencyLoginIdsSection({
  onChange, initialAgencyId, onConsumeInitial,
}: {
  onChange?: (count: number) => void;
  /** Open the Add modal straight away with this agency preselected. */
  initialAgencyId?: number | null;
  onConsumeInitial?: () => void;
}) {
  const [rows, setRows] = useState<LoginIdRowA[]>([]);
  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [agencies, setAgencies] = useState<AgencyOpt[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<LoginIdRowA | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<LoginIdRowA[]>("/agency-login-ids/", { params: { search } });
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
  useEffect(() => {
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } }).then(r => setAirlines(r.data)).catch(() => setAirlines([]));
    fetchAgencies();
  }, [fetchAgencies]);

  // Arriving from "Agency added → Add Login IDs": open the modal with that
  // agency already chosen.
  useEffect(() => {
    if (initialAgencyId != null) { setModal(null); onConsumeInitial?.(); }
  }, [initialAgencyId, onConsumeInitial]);

  const toggle = async (row: LoginIdRowA) => {
    try {
      const { data } = await api.patch<LoginIdRowA>(`/agency-login-ids/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this login ID? This cannot be undone.")) return;
    try {
      await api.delete(`/agency-login-ids/${id}`);
      setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    } catch { alert("Delete failed."); }
  };

  return (
    <div className="space-y-3">
      <Toolbar label="Login ID" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => { fetchAgencies(); setModal(null); }} onRefresh={fetchRows} loading={loading} />

      {agencies.length === 0 && !loading && (
        <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Tip: add an Agency and an Entity first so you can link login IDs to them.
        </p>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["MIRROR / LOGIN ID", "CHANNEL", "AIRLINE", "AIRLINE CODE", "LOB", "ENTITY", "AGENCY", "STATUS", "ACTIONS"].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-xs text-gray-400">No login IDs yet. Add one or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.login_id}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                      r.channel === "GDS" ? "bg-sky-50 text-sky-700 border-sky-200" : "bg-violet-50 text-violet-700 border-violet-200"
                    }`}>{r.channel}</span>
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.airline_name || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.airline_code || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.lob || "—"}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{r.entity_name || "—"}</td>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{r.agency_name || "—"}</td>
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
        <LoginIdModal login={modal} airlines={airlines} agencies={agencies} presetAgencyId={initialAgencyId ?? null}
          onClose={() => setModal(false)} onSaved={() => { setModal(false); fetchRows(); }} onRefresh={fetchRows} />
      )}
    </div>
  );
}

type DraftRow = {
  login_id: string;
  airline_name: string;
  airline_code: string;
  lob: string;
  err?: string;
};

const emptyRow = (): DraftRow => ({ login_id: "", airline_name: "", airline_code: "", lob: "" });

function LoginIdModal({
  login, airlines, agencies, presetAgencyId, onClose, onSaved, onRefresh,
}: {
  login: LoginIdRowA | null;
  airlines: AirlineOpt[];
  agencies: AgencyOpt[];
  presetAgencyId: number | null;
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
}) {
  const isEdit = !!login;
  const [tab, setTab] = useState<"manual" | "xls">("manual");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // entities for the currently selected agency (add-mode or edit-mode)
  const [entities, setEntities] = useState<EntityOpt[]>([]);
  // Filtered by channel as well as agency: an LCC-only entity cannot hold a GDS
  // mirror ID, so offering it would only produce a 400 on save.
  const loadEntitiesFor = useCallback(async (agencyId: number | null, channel?: string) => {
    if (!agencyId) { setEntities([]); return; }
    try {
      const { data } = await api.get<EntityOpt[]>("/agency-entities/", {
        params: { agency_id: agencyId, limit: 1000, ...(channel ? { channel } : {}) },
      });
      setEntities(data);
    } catch { setEntities([]); }
  }, []);

  // add-mode: pick agency + entity ONCE, then add many login-id rows under them
  const [agencyId, setAgencyId] = useState<number | null>(presetAgencyId);
  const [channel, setChannel] = useState<Channel | "">("");
  const [entityId, setEntityId] = useState<number | null>(null);
  const [rows, setRows] = useState<DraftRow[]>([emptyRow()]);
  const setRow = (i: number, patch: Partial<DraftRow>) =>
    setRows(p => p.map((r, idx) => (idx === i ? { ...r, ...patch, err: undefined } : r)));
  const addRow = () => setRows(p => [...p, emptyRow()]);
  const removeRow = (i: number) => setRows(p => (p.length > 1 ? p.filter((_, idx) => idx !== i) : p));
  const validCount = rows.filter(r => r.login_id.trim()).length;

  const addAgency = agencies.find(a => a.id === agencyId);
  const addChannels = channelsFor(addAgency?.channels);

  const pickAgencyAdd = (id: number | null) => {
    setAgencyId(id); setChannel(""); setEntityId(null); setEntities([]);
  };
  const pickChannelAdd = (c: Channel | "") => {
    setChannel(c); setEntityId(null); loadEntitiesFor(agencyId, c || undefined);
  };

  // A single-channel agency has nothing to choose — pick it for the user.
  useEffect(() => {
    if (addChannels.length === 1 && channel !== addChannels[0]) pickChannelAdd(addChannels[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agencyId, addChannels.length]);

  // edit-mode: single form
  const [form, setForm] = useState({
    agency_id: login?.agency_id ?? null as number | null,
    channel: (login?.channel ?? "") as Channel | "",
    login_id: login?.login_id ?? "",
    airline_name: login?.airline_name ?? "",
    airline_code: login?.airline_code ?? "",
    lob: login?.lob ?? "",
    entity_id: login?.entity_id ?? null as number | null,
    is_active: login?.is_active ?? true,
  });
  const set = (k: keyof typeof form, v: string | number | boolean | null) => setForm(p => ({ ...p, [k]: v }));
  const pickAgencyEdit = (id: number | null) => {
    setForm(p => ({ ...p, agency_id: id, channel: "", entity_id: null })); setEntities([]);
  };
  const pickChannelEdit = (c: Channel | "") => {
    setForm(p => ({ ...p, channel: c, entity_id: null }));
    loadEntitiesFor(form.agency_id, c || undefined);
  };

  // in edit-mode, preload the login's agency entities
  useEffect(() => { if (isEdit && login) loadEntitiesFor(login.agency_id, login.channel); }, [isEdit, login, loadEntitiesFor]);

  const saveEdit = async () => {
    if (!form.agency_id) { setError("Please select the agency."); return; }
    if (!form.channel) { setError("Pick a channel — GDS or LCC."); return; }
    if (!form.login_id.trim()) { setError(`${credentialLabel(form.channel)} is required.`); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/agency-login-ids/${login!.id}`, { ...form, login_id: form.login_id.trim() });
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMany = async () => {
    if (!agencyId) { setError("Please select the agency."); return; }
    if (!channel) { setError("Pick a channel — GDS or LCC."); return; }
    const drafts = rows.filter(r => r.login_id.trim());
    if (!drafts.length) { setError(`Add at least one ${credentialLabel(channel)}.`); return; }
    setSaving(true); setError("");
    const failed: DraftRow[] = [];
    let created = 0;
    for (const r of drafts) {
      try {
        await api.post("/agency-login-ids/", {
          agency_id: agencyId,
          channel,
          entity_id: entityId,
          login_id: r.login_id.trim(),
          airline_name: r.airline_name || null,
          airline_code: r.airline_code || null,
          lob: r.lob || null,
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
          <div><label className={LABEL}>Agency *</label>
            <select value={form.agency_id ?? ""} onChange={e => pickAgencyEdit(e.target.value ? Number(e.target.value) : null)} className={INPUT}>
              <option value="">— Select agency —</option>
              {agencies.map(a => <option key={a.id} value={a.id}>{agencyLabel(a)}</option>)}
            </select></div>
          <div><label className={LABEL}>Channel *</label>
            <select value={form.channel} onChange={e => pickChannelEdit(e.target.value as Channel | "")} className={INPUT}>
              <option value="">— Select channel —</option>
              {channelsFor(agencies.find(a => a.id === form.agency_id)?.channels).map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <p className="text-[10px] text-gray-400 mt-1">A credential belongs to one channel — a mirror ID is a GDS thing, a portal login an LCC thing.</p>
          </div>
          <div><label className={LABEL}>{credentialLabel(form.channel)} *</label>
            <input value={form.login_id} onChange={e => set("login_id", e.target.value)}
              placeholder={form.channel === "GDS" ? "e.g. 6X2K-DEL" : "e.g. 6E-AGT-88213"} className={INPUT} /></div>
          <div><label className={LABEL}>Entity</label>
            <select value={form.entity_id ?? ""} onChange={e => set("entity_id", e.target.value ? Number(e.target.value) : null)}
              className={INPUT} disabled={!form.channel}>
              <option value="">{form.channel ? "— Select entity —" : "Select a channel first"}</option>
              {entities.map(en => <option key={en.id} value={en.id}>{en.name} ({en.code})</option>)}
            </select>
            <p className="text-[10px] text-gray-400 mt-1">Only entities that trade on this channel are listed.</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>Airline Name</label>
              <select value={form.airline_name}
                onChange={e => {
                  const name = e.target.value;
                  const a = airlines.find(x => x.name === name);
                  setForm(p => ({ ...p, airline_name: name, airline_code: a ? a.iata_code : "" }));
                }}
                className={INPUT}>
                <option value="">— Select airline —</option>
                {form.airline_name && !airlines.some(a => a.name === form.airline_name) && (
                  <option value={form.airline_name}>{form.airline_name}</option>
                )}
                {airlines.map(a => <option key={a.id} value={a.name}>{a.name}</option>)}
              </select></div>
            <div><label className={LABEL}>Airline Code</label>
              <input value={form.airline_code} readOnly placeholder="Auto-filled"
                title="Auto-filled from the selected airline"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none" /></div>
          </div>
          <div><label className={LABEL}>LoB</label>
            <select value={form.lob} onChange={e => set("lob", e.target.value)} className={INPUT}>
              <option value="">— Select LoB —</option>
              {form.lob && !LOB_OPTIONS.includes(form.lob) && (
                <option value={form.lob}>{form.lob}</option>
              )}
              {LOB_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select></div>
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
          {/* one agency + channel + entity for all the login IDs added below */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Agency *</label>
              <select value={agencyId ?? ""} onChange={e => pickAgencyAdd(e.target.value ? Number(e.target.value) : null)} className={INPUT}>
                <option value="">— Select agency —</option>
                {agencies.map(a => <option key={a.id} value={a.id}>{agencyLabel(a)}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Channel *</label>
              <select value={channel} onChange={e => pickChannelAdd(e.target.value as Channel | "")}
                className={INPUT} disabled={!agencyId || addChannels.length <= 1}>
                <option value="">{agencyId ? "— Select channel —" : "Select agency first"}</option>
                {addChannels.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className={LABEL}>Entity</label>
            <select value={entityId ?? ""} onChange={e => setEntityId(e.target.value ? Number(e.target.value) : null)}
              className={INPUT} disabled={!channel}>
              <option value="">{channel ? "— Select entity —" : "Select a channel first"}</option>
              {entities.map(en => <option key={en.id} value={en.id}>{en.name} ({en.code})</option>)}
            </select>
          </div>
          <p className="text-[10px] text-gray-400 -mt-1">
            All credentials below are added under this agency{entityId ? " and entity" : ""} on {channel || "the chosen channel"}.
            {channel === "GDS" && " A GDS credential is the mirror office the agency books your stock through."}
            {channel === "LCC" && " An LCC credential is one airline's agent-portal login."}
          </p>

          <div className="space-y-2.5">
            {rows.map((r, i) => (
              <div key={i} className={`rounded-lg border p-3 space-y-2 ${r.err ? "border-red-300 bg-red-50/40" : "border-gray-200 bg-gray-50/50"}`}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Login ID #{i + 1}</span>
                  {rows.length > 1 && (
                    <button onClick={() => removeRow(i)} className="p-1 hover:bg-red-100 rounded text-red-400 hover:text-red-600" title="Remove"><Trash2 className="w-3.5 h-3.5" /></button>
                  )}
                </div>
                <input value={r.login_id} onChange={e => setRow(i, { login_id: e.target.value })}
                  placeholder={`${credentialLabel(channel)} *`} className={INPUT} />
                <div className="grid grid-cols-2 gap-2">
                  <select value={r.airline_name}
                    onChange={e => {
                      const name = e.target.value;
                      const a = airlines.find(x => x.name === name);
                      setRow(i, { airline_name: name, airline_code: a ? a.iata_code : "" });
                    }}
                    className={INPUT}>
                    <option value="">— Airline —</option>
                    {airlines.map(a => <option key={a.id} value={a.name}>{a.name}</option>)}
                  </select>
                  <input value={r.airline_code} readOnly placeholder="Code (auto)"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-500 cursor-not-allowed focus:outline-none" />
                </div>
                <select value={r.lob} onChange={e => setRow(i, { lob: e.target.value })} className={INPUT}>
                  <option value="">— LoB —</option>
                  {LOB_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
                {r.err && <p className="text-[10px] text-red-500">{r.err}</p>}
              </div>
            ))}
          </div>

          <button onClick={addRow} className="flex items-center gap-1.5 text-xs font-semibold text-sky-600 hover:text-sky-800">
            <Plus className="w-3.5 h-3.5" /> Add another login ID
          </button>

          {error && <p className="text-[11px] text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button onClick={saveMany} disabled={saving || validCount === 0 || !agencyId || !channel} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
              {saving ? "Saving…" : `Create ${validCount || ""} Login ID${validCount === 1 ? "" : "s"}`.replace("  ", " ")}
            </button>
          </div>
        </div>
      ) : (
        <UploadBox resource="agency-login-ids" templateName="agency_login_id_template.xlsx" columns="CHANNEL, LOGIN_ID, AGENCY, AGENCY_BRANCH, ENTITY_CODE, AIRLINE_NAME, AIRLINE_CODE, LOB, VENDOR, ACTIVE" onDone={onSaved} />
      )}
    </ModalShell>
  );
}
