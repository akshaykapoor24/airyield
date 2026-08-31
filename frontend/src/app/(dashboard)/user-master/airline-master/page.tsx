"use client";

// User master → Airline Master. The airlines this tenant works with, each carrying
// the tenant's own ID for it.
//
// Why it exists: an LCC Detailed export identifies no carrier — there is no airline
// column, and the flight numbers in Segments are bare ("2571"), so nothing in the file
// says which airline it belongs to. The user picks one of these IDs in the LCC upload
// wizard and the airline is stamped onto the batch and every row from there.
//
// AIRLINE / CODE / IATA NUMERIC / CONTRACT YEAR are owned by the platform admin's
// airline master and shown read-only. Changing them is a System master update request
// (/masters/airlines). The only field a user types here is their own ID.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Edit2, Plane, Trash2 } from "lucide-react";
import api from "@/lib/api";
import SearchSelect from "@/components/ui/SearchSelect";
import {
  ActiveBadge, INPUT, LABEL, ModalShell, Toolbar, apiError,
} from "@/components/userMaster/shared";

type TenantAirline = {
  id: number;
  airline_id: number;
  ref_id: string;
  airline_name: string | null;
  airline_code: string | null;
  iata_numeric_code: string | null;
  contract_year: string | null;
  is_active: boolean;
  live_airline_name: string | null;
};

type MasterAirline = {
  id: number;
  name: string;
  iata_code: string;
  iata_numeric_code: string | null;
  contract_year: "CY" | "FY" | null;
};

function AirlineFormModal({
  editing, onClose, onSaved,
}: {
  editing: TenantAirline | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [master, setMaster] = useState<MasterAirline[]>([]);
  const [airlineName, setAirlineName] = useState(editing?.airline_name ?? "");
  const [refId, setRefId] = useState(editing?.ref_id ?? "");
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Same call the platform airline master page makes — AirlineRead already carries
  // iata_numeric_code and contract_year, so no new endpoint is needed.
  useEffect(() => {
    api.get<MasterAirline[]>("/airlines/?limit=5000")
      .then(r => setMaster(r.data))
      .catch(e => setError(apiError(e)));
  }, []);

  // Keyed by name: the airline master has no duplicate names, and SearchSelect works
  // over plain strings. Picking a name is what fills code / numeric / contract year.
  const names = useMemo(() => master.map(a => a.name), [master]);
  const selected = useMemo(
    () => master.find(a => a.name === airlineName) ?? null,
    [master, airlineName],
  );

  const save = async () => {
    if (!selected) { setError("Select an airline."); return; }
    if (!refId.trim()) { setError("Enter your ID for this airline."); return; }
    setSaving(true); setError("");
    try {
      const body = { airline_id: selected.id, ref_id: refId.trim(), is_active: isActive };
      if (editing) await api.patch(`/tenant-airlines/${editing.id}`, body);
      else await api.post("/tenant-airlines/", body);
      onSaved();
      onClose();
    } catch (e) {
      setError(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title={editing ? "Edit Airline" : "Add Airline"} onClose={onClose}>
      <div className="space-y-3">
        {/* Step 1 — pick the airline. Collapsed dropdown with search inside, so 212
            master rows stay browsable without the panel dominating the modal. */}
        <div>
          <label className={LABEL}>
            Airline Name <span className="text-red-500">*</span>
          </label>
          <SearchSelect
            value={airlineName}
            options={names}
            onChange={setAirlineName}
            placeholder={master.length ? "Select an airline…" : "Loading airlines…"}
            disabled={master.length === 0}
          />
        </div>

        {/* Filled from the platform airline master the moment a name is picked.
            Read-only — changing these is a System master update request. */}
        {selected ? (
          <div className="grid grid-cols-3 gap-2 rounded-lg border border-gray-100 bg-gray-50/70 p-2.5">
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Code</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{selected.iata_code || "—"}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">IATA Numeric</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{selected.iata_numeric_code || "—"}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Contract Year</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{selected.contract_year || "—"}</p>
            </div>
          </div>
        ) : (
          <p className="text-[11px] text-gray-400 -mt-1">
            Code, IATA numeric code and contract year come from the airline master once you pick a name.
          </p>
        )}

        {/* Step 2 — the only field the user types. */}
        <div>
          <label className={LABEL}>
            Your ID for this airline <span className="text-red-500">*</span>
          </label>
          <input
            value={refId}
            onChange={e => setRefId(e.target.value)}
            placeholder="e.g. KTDEL471"
            className={INPUT}
          />
          <p className="text-[10px] text-gray-400 mt-1">
            This is what you select when uploading an LCC statement. It must be unique within your account.
          </p>
        </div>

        <label className="flex items-center gap-2 text-xs text-gray-600">
          <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)} />
          Active — inactive airlines are hidden from the LCC upload picker
        </label>

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <button
          onClick={save}
          disabled={saving}
          className="w-full text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
          style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
        >
          {saving ? "Saving…" : editing ? "Save Changes" : "Add Airline"}
        </button>
      </div>
    </ModalShell>
  );
}

export default function AirlineMasterPage() {
  const [rows, setRows] = useState<TenantAirline[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<TenantAirline | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const { data } = await api.get<TenantAirline[]>("/tenant-airlines/", {
        params: search.trim() ? { search: search.trim() } : undefined,
      });
      setRows(data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const toggleActive = async (r: TenantAirline) => {
    try {
      await api.patch(`/tenant-airlines/${r.id}`, { is_active: !r.is_active });
      load();
    } catch (e) { setError(apiError(e)); }
  };

  const remove = async (r: TenantAirline) => {
    if (!confirm(`Remove ${r.airline_name ?? "this airline"} (${r.ref_id}) from your Airline Master?`)) return;
    try {
      await api.delete(`/tenant-airlines/${r.id}`);
      load();
    } catch (e) { setError(apiError(e)); }
  };

  const openAdd = () => { setEditing(null); setShowForm(true); };
  const openEdit = (r: TenantAirline) => { setEditing(r); setShowForm(true); };

  return (
    <div className="space-y-3">
      <Toolbar
        label="Airline"
        count={rows.length}
        search={search}
        setSearch={setSearch}
        onAdd={openAdd}
        onRefresh={load}
        loading={loading}
      />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-600">{error}</div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
                <th className="px-3 py-2.5">ID</th>
                <th className="px-3 py-2.5">Airline</th>
                <th className="px-3 py-2.5">Code</th>
                <th className="px-3 py-2.5">IATA Numeric Code</th>
                <th className="px-3 py-2.5">Contract Year</th>
                <th className="px-3 py-2.5">Status</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map(r => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2.5 font-semibold text-gray-900">{r.ref_id}</td>
                  <td className="px-3 py-2.5 text-gray-700">
                    {r.airline_name ?? "—"}
                    {/* The snapshot is what statements were stamped with; flag drift
                        rather than silently showing one name or the other. */}
                    {r.live_airline_name && r.live_airline_name !== r.airline_name && (
                      <span className="ml-1.5 text-[10px] text-amber-600">
                        (master now: {r.live_airline_name})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{r.airline_code ?? "—"}</td>
                  <td className="px-3 py-2.5 text-gray-600">{r.iata_numeric_code ?? "—"}</td>
                  <td className="px-3 py-2.5 text-gray-600">{r.contract_year ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <ActiveBadge active={r.is_active} onClick={() => toggleActive(r)} />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => openEdit(r)} className="p-1.5 hover:bg-gray-100 rounded-lg" title="Edit">
                        <Edit2 className="w-3.5 h-3.5 text-gray-500" />
                      </button>
                      <button onClick={() => remove(r)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Remove">
                        <Trash2 className="w-3.5 h-3.5 text-red-500" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center">
                    <Plane className="w-6 h-6 text-gray-300 mx-auto mb-2" />
                    <p className="text-xs text-gray-500 font-medium">No airlines yet</p>
                    <p className="text-[11px] text-gray-400 mt-1">
                      Add the airlines you work with and give each one your own ID — you&apos;ll need it
                      to upload an LCC statement.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && (
        <AirlineFormModal
          editing={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={load}
        />
      )}
    </div>
  );
}
