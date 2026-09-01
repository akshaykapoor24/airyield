"use client";

// User master → Airline Master. The airlines this tenant works with, each carrying
// the tenant's own ID(s) for it.
//
// Why it exists: an LCC Detailed export identifies no carrier — there is no airline
// column, and the flight numbers in Segments are bare ("2571"), so nothing in the file
// says which airline it belongs to. The user picks one of these IDs in the LCC upload
// wizard and the airline is stamped onto the batch and every row from there.
//
// The grid is a LIVE VIEW of the platform admin's airline master, not a per-tenant
// copy of it: AIRLINE / CODE / IATA NUMERIC / CONTRACT YEAR arrive already filled and
// read-only (changing them is a System master update request at /masters/airlines),
// and the only column the user owns is ID. An airline with no ID yet is not a stored
// row — it is a master row the tenant hasn't claimed, which is why "All airlines"
// costs nothing and why an airline the admin adds appears here immediately.
//
// One airline holds MANY IDs. Five Indigo agent logins across offices is ordinary, so
// the ID cell is a list of chips, managed in AirlineIdsModal.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plane, Plus, RefreshCw, Search, Upload } from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";
import AirlineIdsModal from "@/components/userMaster/AirlineIdsModal";
import {
  type AirlineCatalogEntry, ModalShell, UploadBox, apiError,
} from "@/components/userMaster/shared";

type CatalogPage = {
  items: AirlineCatalogEntry[];
  total: number;
  mine_count: number;
  all_count: number;
};

type Scope = "mine" | "all";
const PAGE_SIZE = 100;

const EMPTY: CatalogPage = { items: [], total: 0, mine_count: 0, all_count: 0 };

export default function AirlineMasterPage() {
  const [scope, setScope] = useState<Scope>("mine");
  const [data, setData] = useState<CatalogPage>(EMPTY);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manage, setManage] = useState<AirlineCatalogEntry | null>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const { data } = await api.get<CatalogPage>("/tenant-airlines/catalog", {
        params: {
          scope,
          skip: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
          ...(debounced.trim() ? { search: debounced.trim() } : {}),
        },
      });
      setData(data);
    } catch (e) {
      setError(apiError(e));
      setData(EMPTY);
    } finally {
      setLoading(false);
    }
  }, [scope, page, debounced]);

  useEffect(() => { load(); }, [load]);

  const pickScope = (next: Scope) => { setScope(next); setPage(1); };

  // The modal edits ids in place and reports back; re-read so the chips, the counts
  // and the "My airlines" membership on the grid all follow.
  const refresh = useCallback(() => { load(); }, [load]);

  const rows = data.items;
  const emptyMessage = useMemo(() => {
    if (debounced.trim()) return `Nothing matches “${debounced.trim()}”.`;
    if (scope === "mine") return null;      // handled by the richer empty state below
    return "The airline master is empty — the platform team maintains it.";
  }, [debounced, scope]);

  return (
    <div className="space-y-3">
      {/* Toolbar. Not the shared <Toolbar/>: this page has scope tabs and imports
          IDs rather than adding a record, so its own row is clearer than bending
          that one. Same classes, so it still reads as the same control strip. */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5">
          {([
            ["mine", "My airlines", data.mine_count],
            ["all", "All airlines", data.all_count],
          ] as const).map(([key, label, count]) => (
            <button
              key={key}
              onClick={() => pickScope(key)}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                scope === key ? "bg-[#1e3a5f] text-white" : "text-gray-500 hover:bg-gray-50"
              }`}
            >
              {label} <span className={scope === key ? "opacity-70" : "text-gray-400"}>({count})</span>
            </button>
          ))}
        </div>

        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search airline, code or your ID…"
            className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400"
          />
        </div>

        <button onClick={load} disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
        <button onClick={() => setImporting(true)}
          className="flex items-center gap-1.5 text-white px-3.5 py-2 rounded-lg text-xs font-medium" style={{ background: "#1e3a5f" }}>
          <Upload className="w-3.5 h-3.5" /> Import IDs
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-600">{error}</div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
                <th className="px-3 py-2.5 min-w-64">ID</th>
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
                <tr key={r.airline_id} className="hover:bg-gray-50 align-top">
                  {/* The only column the user owns. Chips, because one airline
                      routinely carries several ids. */}
                  <td className="px-3 py-2.5">
                    {r.ids.length === 0 ? (
                      <button
                        onClick={() => setManage(r)}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-sky-600 hover:text-sky-800"
                      >
                        <Plus className="w-3 h-3" /> Add ID
                      </button>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1">
                        {r.ids.map(i => (
                          <span
                            key={i.id}
                            title={[
                              i.is_active ? null : "Inactive — hidden from the LCC upload picker",
                              i.in_use_count ? `Used by ${i.in_use_count} uploaded statement(s)` : null,
                            ].filter(Boolean).join(" · ") || undefined}
                            className={`px-1.5 py-0.5 rounded border text-[11px] font-semibold ${
                              i.is_active
                                ? "bg-sky-50 text-sky-700 border-sky-200"
                                : "bg-gray-50 text-gray-400 border-gray-200"
                            }`}
                          >
                            {i.ref_id}
                          </span>
                        ))}
                        <button
                          onClick={() => setManage(r)}
                          className="p-0.5 rounded border border-dashed border-gray-300 text-gray-400 hover:text-sky-600 hover:border-sky-300"
                          title={`Add another ID for ${r.name}`}
                        >
                          <Plus className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-gray-700">
                    {r.name}
                    {/* The snapshot is what statements were stamped with; flag drift
                        rather than silently showing one name or the other. */}
                    {r.ids.some(i => i.snapshot_name_drifted) && (
                      <span className="ml-1.5 text-[10px] text-amber-600" title="Some IDs were added under an earlier name; the statements they stamped still carry it.">
                        (renamed since)
                      </span>
                    )}
                    {!r.master_is_active && (
                      <span className="ml-1.5 text-[10px] text-gray-400">(inactive in master)</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{r.iata_code || "—"}</td>
                  <td className="px-3 py-2.5 text-gray-600">{r.iata_numeric_code || "—"}</td>
                  <td className="px-3 py-2.5 text-gray-600">{r.contract_year || "—"}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {r.id_count === 0 ? (
                      <span className="text-[10px] text-gray-400">No ID yet</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border bg-green-50 text-green-700 border-green-200">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                        {r.active_id_count} active
                        {r.id_count > r.active_id_count && (
                          <span className="text-gray-400 font-normal">· {r.id_count - r.active_id_count} off</span>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => setManage(r)}
                      className="px-2 py-1 rounded-lg border border-gray-200 text-[11px] font-medium text-gray-600 hover:bg-gray-50 whitespace-nowrap"
                    >
                      Manage IDs
                    </button>
                  </td>
                </tr>
              ))}

              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center">
                    <Plane className="w-6 h-6 text-gray-300 mx-auto mb-2" />
                    {emptyMessage ? (
                      <p className="text-xs text-gray-500 font-medium">{emptyMessage}</p>
                    ) : (
                      <>
                        <p className="text-xs text-gray-500 font-medium">No IDs yet</p>
                        <p className="text-[11px] text-gray-400 mt-1 max-w-md mx-auto">
                          Open <button onClick={() => pickScope("all")} className="text-sky-600 font-semibold hover:underline">All airlines</button>{" "}
                          to find the airlines you work with and give each one your own ID — you&apos;ll
                          need it to upload an LCC statement.
                        </p>
                      </>
                    )}
                  </td>
                </tr>
              )}

              {loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {data.total > PAGE_SIZE && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
        )}
      </div>

      {manage && (
        <AirlineIdsModal
          entry={manage}
          // No reload on close: the modal reports each change as it happens, so
          // the grid behind it is already current.
          onClose={() => setManage(null)}
          onChanged={refresh}
        />
      )}

      {importing && (
        <ModalShell title="Import Airline IDs" onClose={() => setImporting(false)}>
          <p className="text-[11px] text-gray-500 mb-3">
            Repeat an airline code to give one airline several IDs — that is what the file is for.
            Unknown codes and IDs you already use are reported row by row, not silently skipped.
          </p>
          <UploadBox
            resource="tenant-airlines"
            templateName="airline_id_template.xlsx"
            columns="AIRLINE_CODE, ID, ACTIVE"
            onDone={refresh}
          />
        </ModalShell>
      )}
    </div>
  );
}
