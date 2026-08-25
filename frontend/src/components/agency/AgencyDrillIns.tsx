"use client";

// Agency drill-ins — the count pills and the two popups behind them.
//
// Lifted out of the former AgencyOverview so the Customer Directory (which now
// lists direct customers and corporates alongside agencies) can keep the
// hierarchy drill-down: agency → its entities → their login IDs.
//
// LoginIdsPopup takes the query params rather than an entity, because there are
// two ways in: every login ID under an AGENCY, or just the ones under one ENTITY.
// Those two counts legitimately differ — /agencies/overview counts every row by
// agency_id, while the per-entity count requires entity_id IS NOT NULL, so a
// login ID that was never attached to an entity shows in the first and not the
// second. The titles say which set is on screen.

import { useState, useEffect } from "react";
import { RefreshCw, Building2, KeyRound } from "lucide-react";
import api from "@/lib/api";
import { apiError, ModalShell } from "@/components/userMaster/shared";

export type EntityRow = {
  id: number;
  agency_id: number;
  name: string;
  code: string;
  login_id_count?: number | null;
};

type LoginRow = {
  id: number;
  login_id: string;
  channel: string;
  airline_name: string | null;
  airline_code: string | null;
  entity_name: string | null;
  lob: string | null;
};

export function CountPill({
  value, icon: Icon, onClick,
}: {
  value: number;
  icon: typeof Building2;
  onClick?: () => void;
}) {
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

export function EntitiesPopup({
  agencyId, agencyName, entityCount, onClose,
}: {
  agencyId: number;
  agencyName: string;
  entityCount: number;
  onClose: () => void;
}) {
  const [entities, setEntities] = useState<EntityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [loginEntity, setLoginEntity] = useState<EntityRow | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true); setErr("");
      try {
        const { data } = await api.get<EntityRow[]>("/agency-entities/", {
          params: { agency_id: agencyId, limit: 1000 },
        });
        setEntities(data);
      } catch (e) { setErr(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, [agencyId]);

  return (
    <ModalShell
      title={`${agencyName} — ${entityCount} Entit${entityCount === 1 ? "y" : "ies"}`}
      onClose={onClose}
    >
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
              <CountPill
                value={en.login_id_count ?? 0}
                icon={KeyRound}
                onClick={(en.login_id_count ?? 0) > 0 ? () => setLoginEntity(en) : undefined}
              />
            </div>
          ))}
        </div>
      )}

      {loginEntity && (
        <LoginIdsPopup
          title={`${loginEntity.name} — ${loginEntity.login_id_count ?? 0} Login ID${(loginEntity.login_id_count ?? 0) === 1 ? "" : "s"}`}
          params={{ entity_id: loginEntity.id }}
          onClose={() => setLoginEntity(null)}
        />
      )}
    </ModalShell>
  );
}

export function LoginIdsPopup({
  title, params, onClose,
}: {
  title: string;
  /** { agency_id } for every login ID under an agency, { entity_id } for one entity's. */
  params: { agency_id: number } | { entity_id: number };
  onClose: () => void;
}) {
  const [logins, setLogins] = useState<LoginRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // Serialised so the effect re-runs on a genuinely different query rather than
  // on every re-render, which a fresh object literal would cause.
  const paramKey = JSON.stringify(params);

  useEffect(() => {
    (async () => {
      setLoading(true); setErr("");
      try {
        const { data } = await api.get<LoginRow[]>("/agency-login-ids/", {
          params: { ...JSON.parse(paramKey), limit: 1000 },
        });
        setLogins(data);
      } catch (e) { setErr(apiError(e)); }
      finally { setLoading(false); }
    })();
  }, [paramKey]);

  const showEntity = "agency_id" in params;

  return (
    <ModalShell title={title} onClose={onClose}>
      {loading ? (
        <p className="py-8 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</p>
      ) : err ? (
        <p className="py-8 text-center text-xs text-red-400">{err}</p>
      ) : logins.length === 0 ? (
        <p className="py-8 text-center text-xs text-gray-400">No login IDs found.</p>
      ) : (
        <div className="overflow-x-auto border border-gray-100 rounded-lg">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50">
                {["MIRROR / LOGIN ID", "CHANNEL", "AIRLINE", ...(showEntity ? ["ENTITY"] : []), "LOB"].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logins.map((l, idx) => (
                <tr key={l.id} className={`border-b border-gray-50 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{l.login_id}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                      l.channel === "GDS" ? "bg-sky-50 text-sky-700 border-sky-200" : "bg-violet-50 text-violet-700 border-violet-200"
                    }`}>{l.channel}</span>
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">
                    {l.airline_name || "—"}{l.airline_code ? ` (${l.airline_code})` : ""}
                  </td>
                  {showEntity && (
                    <td className="px-3 py-2 text-[11px] text-gray-600">
                      {l.entity_name || <span className="text-gray-400 italic">unassigned</span>}
                    </td>
                  )}
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
