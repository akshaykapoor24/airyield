"use client";

// Agency Overview — a drill-down of the whole hierarchy. Each row is an agency
// showing its entity + login-id counts. Click an entity count to see that
// agency's entities (each with its own login-id count); click a login-id count
// to see the login IDs. (e.g. Lords → 4 entities → 10 login IDs.)

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Building2, KeyRound } from "lucide-react";
import api from "@/lib/api";
import { apiError, ModalShell } from "@/components/userMaster/shared";

type OverviewRow = { id: number; name: string; entity_count: number; login_id_count: number };
type EntityRow = { id: number; agency_id: number; name: string; code: string; login_id_count?: number | null };
type LoginRow = { id: number; login_id: string; airline_name: string | null; airline_code: string | null; entity_name: string | null; lob: string | null };

function CountPill({ value, icon: Icon, onClick }: { value: number; icon: typeof Building2; onClick?: () => void }) {
  const disabled = value === 0 || !onClick;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors ${
        disabled
          ? "bg-gray-50 text-gray-400 border-gray-200 cursor-default"
          : "bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100 cursor-pointer"
      }`}>
      <Icon className="w-3.5 h-3.5" /> {value}
    </button>
  );
}

// Overview content. `embedded` hides the page header so it can be hosted inside
// the Customer Directory tabbed page (which supplies its own header). The Refresh
// button is kept in both modes.
export default function AgencyOverview({ embedded = false }: { embedded?: boolean }) {
  const [rows, setRows] = useState<OverviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [entityModal, setEntityModal] = useState<OverviewRow | null>(null);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<OverviewRow[]>("/agencies/overview");
      setRows(data);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  return (
    <div className="space-y-4">
      <div className={`flex items-end gap-3 ${embedded ? "justify-end" : "justify-between"}`}>
        {!embedded && (
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Agency Profile</p>
            <h1 className="text-xl font-bold text-gray-900">Agency Overview</h1>
            <p className="text-xs text-gray-500 mt-0.5">Each agency with its entities and login IDs. Click a count to drill in.</p>
          </div>
        )}
        <button onClick={fetchRows} disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {["AGENCY", "ENTITIES", "LOGIN IDS"].map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-xs text-gray-400">No agencies yet. Add some in Onboarding.</td></tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-4 py-2.5 text-[12px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-4 py-2.5"><CountPill value={r.entity_count} icon={Building2} onClick={r.entity_count > 0 ? () => setEntityModal(r) : undefined} /></td>
                  <td className="px-4 py-2.5"><CountPill value={r.login_id_count} icon={KeyRound} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {entityModal && (
        <EntitiesPopup agency={entityModal} onClose={() => setEntityModal(null)} />
      )}
    </div>
  );
}

function EntitiesPopup({ agency, onClose }: { agency: OverviewRow; onClose: () => void }) {
  const [entities, setEntities] = useState<EntityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [loginModal, setLoginModal] = useState<EntityRow | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true); setErr("");
      try {
        const { data } = await api.get<EntityRow[]>("/agency-entities/", { params: { agency_id: agency.id, limit: 1000 } });
        setEntities(data);
      } catch (e) { setErr(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, [agency.id]);

  return (
    <ModalShell title={`${agency.name} — ${agency.entity_count} Entit${agency.entity_count === 1 ? "y" : "ies"}`} onClose={onClose}>
      {loading ? (
        <p className="py-8 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</p>
      ) : err ? (
        <p className="py-8 text-center text-xs text-red-400">{err}</p>
      ) : entities.length === 0 ? (
        <p className="py-8 text-center text-xs text-gray-400">No entities under this agency.</p>
      ) : (
        <div className="divide-y divide-gray-50 border border-gray-100 rounded-lg">
          {entities.map(en => (
            <div key={en.id} className="flex items-center justify-between px-3 py-2.5">
              <div>
                <p className="text-[12px] font-semibold text-gray-800">{en.name}</p>
                <p className="text-[10px] text-gray-400">{en.code}</p>
              </div>
              <CountPill value={en.login_id_count ?? 0} icon={KeyRound}
                onClick={(en.login_id_count ?? 0) > 0 ? () => setLoginModal(en) : undefined} />
            </div>
          ))}
        </div>
      )}

      {loginModal && (
        <LoginIdsPopup entity={loginModal} onClose={() => setLoginModal(null)} />
      )}
    </ModalShell>
  );
}

function LoginIdsPopup({ entity, onClose }: { entity: EntityRow; onClose: () => void }) {
  const [logins, setLogins] = useState<LoginRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true); setErr("");
      try {
        const { data } = await api.get<LoginRow[]>("/agency-login-ids/", { params: { entity_id: entity.id, limit: 1000 } });
        setLogins(data);
      } catch (e) { setErr(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, [entity.id]);

  return (
    <ModalShell title={`${entity.name} — ${entity.login_id_count ?? logins.length} Login ID${(entity.login_id_count ?? logins.length) === 1 ? "" : "s"}`} onClose={onClose}>
      {loading ? (
        <p className="py-8 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</p>
      ) : err ? (
        <p className="py-8 text-center text-xs text-red-400">{err}</p>
      ) : logins.length === 0 ? (
        <p className="py-8 text-center text-xs text-gray-400">No login IDs under this entity.</p>
      ) : (
        <div className="overflow-x-auto border border-gray-100 rounded-lg">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50">
                {["LOGIN ID / IATA", "AIRLINE", "LOB"].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logins.map((l, idx) => (
                <tr key={l.id} className={`border-b border-gray-50 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{l.login_id}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{l.airline_name || "—"}{l.airline_code ? ` (${l.airline_code})` : ""}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{l.lob || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ModalShell>
  );
}
