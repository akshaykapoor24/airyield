"use client";

// Customer Directory — every counterparty we sell to, in one table:
// direct customers (Customer Master), B2B agencies (Agency Master) and
// corporates (Corporate Master).
//
// Four fetches, merged on the client. That is the repo's convention at these
// sizes (PartyDirectory pulls limit=500; the agency pickers pull limit=1000) and
// it avoids a union endpoint that would have to reconcile two different
// ownership models — agencies are scoped by user_id alone, customers and
// corporates by tenant_id + created_by_id. Two of the four calls are for
// agencies because /agencies/ carries the contact and tax columns but no counts,
// while /agencies/overview carries the counts and nothing else.
//
// One source failing must not blank the page: each is settled independently and
// reports its own inline error, so a directory with a dead corporates endpoint
// still lists agencies and direct customers.

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { RefreshCw, Building2, KeyRound, Search, AlertCircle, ArrowUpRight } from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import Pagination from "@/components/ui/Pagination";
import { CountPill, EntitiesPopup, LoginIdsPopup } from "@/components/agency/AgencyDrillIns";
import type { Party } from "@/lib/party";
import {
  COUNTERPARTY, COUNTERPARTY_KINDS, channelBadges, fromAgency, fromParty,
  searchBlob, subtitleOf,
  type AgencyCounts, type AgencyRow, type Counterparty, type CounterpartyKind,
} from "@/lib/counterparty";

const PAGE_SIZE = 25;
/** Matches the server default on all three list endpoints. */
const FETCH_LIMIT = 500;

type Tab = "all" | CounterpartyKind;

const HEADERS = [
  "TYPE", "NAME", "COMPANY / BRANCH", "PHONE", "EMAIL",
  "GST NO", "PAN NO", "ENTITIES", "LOGIN IDS", "STATUS", "",
];

export default function CounterpartyDirectory() {
  const [rows, setRows] = useState<Counterparty[]>([]);
  const [loading, setLoading] = useState(true);
  /** Per-source failures — a dead endpoint costs its own rows, not the page. */
  const [errors, setErrors] = useState<string[]>([]);
  /** Sources that came back exactly at the cap, so more rows may exist. */
  const [capped, setCapped] = useState<string[]>([]);

  const [tab, setTab] = useState<Tab>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const [entityModal, setEntityModal] = useState<Counterparty | null>(null);
  const [loginModal, setLoginModal] = useState<Counterparty | null>(null);

  /** Bumped by Refresh; the fetch effect keys off it. */
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = () => { setLoading(true); setReloadKey(k => k + 1); };

  // The fetch lives inside the effect rather than in a useCallback so that no
  // state is set synchronously on mount, and so `cancelled` can drop the result
  // of a request that is overtaken by unmount or by a second Refresh.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const [agenciesRes, countsRes, customersRes, corporatesRes] = await Promise.allSettled([
        api.get<AgencyRow[]>("/agencies/", { params: { limit: FETCH_LIMIT } }),
        api.get<AgencyCounts[]>("/agencies/overview"),
        api.get<Party[]>("/customers/", { params: { limit: FETCH_LIMIT } }),
        api.get<Party[]>("/corporates/", { params: { limit: FETCH_LIMIT } }),
      ]);
      if (cancelled) return;

      const nextErrors: string[] = [];
      const nextCapped: string[] = [];
      const next: Counterparty[] = [];

      // Counts are an enrichment, not a source — losing them must not lose the
      // agencies themselves, so a failure here degrades the pills to 0, silently.
      const countsById = new Map<number, AgencyCounts>();
      if (countsRes.status === "fulfilled") {
        for (const c of countsRes.value.data) countsById.set(c.id, c);
      }

      if (agenciesRes.status === "fulfilled") {
        const data = agenciesRes.value.data;
        next.push(...data.map(a => fromAgency(a, countsById.get(a.id))));
        if (data.length >= FETCH_LIMIT) nextCapped.push("agencies");
      } else {
        nextErrors.push(`Agencies: ${apiError(agenciesRes.reason)}`);
      }

      if (customersRes.status === "fulfilled") {
        const data = customersRes.value.data;
        next.push(...data.map(p => fromParty(p, "direct")));
        if (data.length >= FETCH_LIMIT) nextCapped.push("direct customers");
      } else {
        nextErrors.push(`Direct customers: ${apiError(customersRes.reason)}`);
      }

      if (corporatesRes.status === "fulfilled") {
        const data = corporatesRes.value.data;
        next.push(...data.map(p => fromParty(p, "corporate")));
        if (data.length >= FETCH_LIMIT) nextCapped.push("corporates");
      } else {
        nextErrors.push(`Corporates: ${apiError(corporatesRes.reason)}`);
      }

      next.sort((a, b) => a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind));

      setRows(next);
      setErrors(nextErrors);
      setCapped(nextCapped);
      setLoading(false);
    })();

    return () => { cancelled = true; };
  }, [reloadKey]);

  const counts = useMemo(() => {
    const c: Record<Tab, number> = { all: rows.length, direct: 0, agency: 0, corporate: 0 };
    for (const r of rows) c[r.kind] += 1;
    return c;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter(r =>
      (tab === "all" || r.kind === tab) &&
      (q === "" || searchBlob(r).includes(q))
    );
  }, [rows, tab, search]);

  // Clamped during render rather than corrected in an effect: a refresh that
  // shrinks the result set would otherwise show one empty page before the
  // correction landed. The tab and search handlers reset `page` themselves.
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <div className="space-y-3">
      {/* Type tabs + search + refresh */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-white">
          {(["all", ...COUNTERPARTY_KINDS] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setPage(1); }}
              className={`px-3 py-2 text-xs font-medium border-r border-gray-200 last:border-r-0 transition-colors ${
                tab === t ? "text-white" : "text-gray-600 hover:bg-gray-50"
              }`}
              style={tab === t ? { background: "#1e3a5f" } : undefined}
            >
              {t === "all" ? "All" : COUNTERPARTY[t].label}
              <span className={`ml-1.5 tabular-nums ${tab === t ? "text-white/70" : "text-gray-400"}`}>
                {counts[t]}
              </span>
            </button>
          ))}
        </div>

        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search name, company, branch, email or phone…"
            className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400"
          />
        </div>

        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {errors.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-red-50 border border-red-200 text-[11px] text-red-700">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
          <div>
            {errors.map(e => <p key={e}>{e}</p>)}
            <p className="text-red-500 mt-0.5">The other types are listed below.</p>
          </div>
        </div>
      )}

      {capped.length > 0 && (
        <div className="px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
          Showing the first {FETCH_LIMIT} {capped.join(" and ")} — there may be more. Use search in
          the master to find a specific one.
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {HEADERS.map((h, i) => (
                  <th
                    key={h || `col-${i}`}
                    className="px-4 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…
                </td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">
                  {rows.length === 0 ? (
                    <>
                      No customers yet. Add them in{" "}
                      {COUNTERPARTY_KINDS.map((k, i) => (
                        <span key={k}>
                          {i > 0 && (i === COUNTERPARTY_KINDS.length - 1 ? " or " : ", ")}
                          <Link href={COUNTERPARTY[k].masterHref} className="text-[#1e3a5f] font-semibold hover:underline">
                            {COUNTERPARTY[k].masterLabel}
                          </Link>
                        </span>
                      ))}.
                    </>
                  ) : (
                    "No customers match this filter."
                  )}
                </td></tr>
              ) : pageRows.map((r, idx) => (
                <tr key={r.key} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${COUNTERPARTY[r.kind].badge}`}>
                      {COUNTERPARTY[r.kind].label}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[12px] font-semibold text-gray-800">{r.name}</td>
                  <td className="px-4 py-2.5 text-[11px] text-gray-600">
                    {r.kind === "agency" ? (
                      <div className="flex items-center gap-1.5">
                        <span>{r.branchName || r.branchCode || "—"}</span>
                        {channelBadges(r.channels).map(c => (
                          <span key={c} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                            c === "GDS" ? "bg-sky-50 text-sky-700 border-sky-200" : "bg-violet-50 text-violet-700 border-violet-200"
                          }`}>{c}</span>
                        ))}
                      </div>
                    ) : (
                      subtitleOf(r) || "—"
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-[11px] text-gray-600">{r.phone || "—"}</td>
                  <td className="px-4 py-2.5 text-[11px] text-gray-600 max-w-[200px] truncate" title={r.email || undefined}>
                    {r.email || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-[11px]">
                    {r.gstRegistered
                      ? <span className="text-gray-600">{r.gstNo || "—"}</span>
                      : <span className="text-gray-400 italic">Unregistered</span>}
                  </td>
                  <td className="px-4 py-2.5 text-[11px] text-gray-600">{r.panNo || "—"}</td>
                  <td className="px-4 py-2.5">
                    {r.kind === "agency" ? (
                      <CountPill
                        value={r.entityCount ?? 0}
                        icon={Building2}
                        onClick={(r.entityCount ?? 0) > 0 ? () => setEntityModal(r) : undefined}
                      />
                    ) : <span className="text-[11px] text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    {r.kind === "agency" ? (
                      <CountPill
                        value={r.loginIdCount ?? 0}
                        icon={KeyRound}
                        onClick={(r.loginIdCount ?? 0) > 0 ? () => setLoginModal(r) : undefined}
                      />
                    ) : <span className="text-[11px] text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                      r.isActive
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-gray-50 text-gray-500 border-gray-200"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${r.isActive ? "bg-green-500" : "bg-gray-400"}`} />
                      {r.isActive ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <Link
                      href={COUNTERPARTY[r.kind].masterHref}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-[#1e3a5f] hover:underline"
                    >
                      Manage <ArrowUpRight className="w-3 h-3" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!loading && filtered.length > 0 && (
          <Pagination page={safePage} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={setPage} />
        )}
      </div>

      {entityModal && (
        <EntitiesPopup
          agencyId={entityModal.id}
          agencyName={entityModal.name}
          entityCount={entityModal.entityCount ?? 0}
          onClose={() => setEntityModal(null)}
        />
      )}

      {loginModal && (
        <LoginIdsPopup
          // "All login IDs", not just the entity-attached ones — this count comes
          // from /agencies/overview, which counts every row by agency_id.
          title={`${loginModal.name} — all ${loginModal.loginIdCount ?? 0} Login ID${(loginModal.loginIdCount ?? 0) === 1 ? "" : "s"}`}
          params={{ agency_id: loginModal.id }}
          onClose={() => setLoginModal(null)}
        />
      )}
    </div>
  );
}
