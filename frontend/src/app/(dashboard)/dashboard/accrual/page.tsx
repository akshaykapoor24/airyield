"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Lock, RefreshCw, TrendingUp, Unlock } from "lucide-react";
import toast from "react-hot-toast";

import AccrualGrid from "@/components/dashboard/AccrualGrid";
import AccrualRowDrawer from "@/components/dashboard/AccrualRowDrawer";
import FilterBar, { filtersFromUrl, type FilterState } from "@/components/dashboard/FilterBar";
import {
  downloadBoardXlsx, fetchBoard, fetchFilters, freezePeriod, patchCells, reopenPeriod,
  type AccrualRow, type CellPatch,
} from "@/lib/accrual";
import { rupees } from "@/lib/money";

const BTN =
  "inline-flex items-center gap-1.5 rounded-lg px-3 h-9.5 text-xs font-semibold transition-colors";

export default function PlbAccrualPage() {
  const qc = useQueryClient();
  // Seeded from the query string so the Overview's exception cards can deep-link
  // into a pre-filtered board.
  const [filters, setFilters] = useState<FilterState>(filtersFromUrl);
  const [openRow, setOpenRow] = useState<AccrualRow | null>(null);

  const filterOptions = useQuery({
    queryKey: ["accrual-filters", filters.period],
    queryFn: () => fetchFilters(filters.period || undefined),
    staleTime: 5 * 60_000,
  });

  const query = {
    period: filters.period || undefined,
    basis: filters.basis,
    airline: filters.airline,
    entity: filters.entity,
    channel: filters.channel,
    lob: filters.lob,
    status: filters.status,
    search: filters.search || undefined,
  };

  const board = useQuery({
    queryKey: ["accrual-board", query],
    queryFn: () => fetchBoard(query),
    // Hold the previous render while refetching instead of flashing a skeleton —
    // the grid is wide, and a remount would throw away the horizontal scroll.
    placeholderData: keepPreviousData,
  });

  const periodKey = board.data?.period.key ?? filters.period;
  const frozen = !!board.data?.frozen;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["accrual-board"] });
    qc.invalidateQueries({ queryKey: ["accrual-overview"] });
  };

  const patch = useMutation({
    mutationFn: (cells: CellPatch[]) => patchCells(periodKey, cells),
    onSuccess: invalidate,
    onError: (e: { response?: { data?: { detail?: string } } }) =>
      toast.error(e.response?.data?.detail ?? "Could not save that value."),
  });

  const freeze = useMutation({
    mutationFn: () => freezePeriod(periodKey),
    onSuccess: () => {
      toast.success(`${board.data?.period.label} frozen.`);
      invalidate();
    },
    onError: (e: { response?: { data?: { detail?: string } } }) =>
      toast.error(e.response?.data?.detail ?? "Could not freeze the period."),
  });

  const reopen = useMutation({
    mutationFn: () => reopenPeriod(periodKey),
    onSuccess: () => {
      toast.success(`${board.data?.period.label} re-opened.`);
      invalidate();
    },
  });

  const dq = board.data?.data_quality;
  const coverageWarning = useMemo(() => {
    if (!dq || dq.travel_date_coverage_pct == null) return null;
    if (filters.basis === "issue") return null;
    if (dq.travel_date_coverage_pct >= 95) return null;
    return `Only ${dq.travel_date_coverage_pct}% of BSP rows carry a travel date. The rest are bucketed by issue date — upload the matching TGQ HMPR statements to place them on the month they actually flew.`;
  }, [dq, filters.basis]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
          <TrendingUp className="w-5 h-5 text-blue-600" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
            Dashboard
          </p>
          <h1 className="text-xl font-bold text-gray-900">PLB Accrual</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Supplier income earned on flown revenue, before the airline pays it.
            Flown × deflator × PLB rate, per deal line.
          </p>
        </div>
      </div>

      <FilterBar
        value={filters}
        onChange={setFilters}
        options={filterOptions.data}
        extra={
          <>
            {board.isFetching && (
              <RefreshCw className="w-3.5 h-3.5 text-gray-400 animate-spin" aria-label="Refreshing" />
            )}
            <button
              type="button"
              onClick={() => downloadBoardXlsx(query)}
              className={`${BTN} border border-emerald-200 text-emerald-700 hover:bg-emerald-50`}
            >
              <Download className="w-3.5 h-3.5" aria-hidden /> Export
            </button>
            {frozen ? (
              <button
                type="button"
                onClick={() => reopen.mutate()}
                disabled={reopen.isPending}
                className={`${BTN} border border-gray-200 text-gray-700 hover:bg-gray-50`}
              >
                <Unlock className="w-3.5 h-3.5" aria-hidden /> Re-open
              </button>
            ) : (
              <button
                type="button"
                onClick={() => freeze.mutate()}
                disabled={freeze.isPending || !board.data?.rows.length}
                className={`${BTN} bg-[#1e3a5f] text-white hover:bg-[#16304f] disabled:opacity-50`}
              >
                <Lock className="w-3.5 h-3.5" aria-hidden /> Freeze period
              </button>
            )}
          </>
        }
      />

      {frozen && board.data?.frozen && (
        <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 px-4 py-2.5 flex items-center gap-2 text-xs text-slate-700">
          <Lock className="w-3.5 h-3.5 shrink-0" aria-hidden />
          <span>
            <strong>{board.data.period.label} is frozen</strong> at{" "}
            {rupees(board.data.frozen.total_accrual ?? 0)} across{" "}
            {board.data.frozen.row_count} lines, booked{" "}
            {new Date(board.data.frozen.frozen_at).toLocaleDateString("en-GB", {
              day: "numeric", month: "short", year: "numeric",
            })}
            . New statement uploads will not move it. Re-open to edit.
          </span>
        </div>
      )}

      {coverageWarning && (
        <div className="rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-2.5 text-xs text-amber-900">
          {coverageWarning}
        </div>
      )}

      {board.isError && (
        <div className="rounded-xl bg-red-50 ring-1 ring-red-200 px-4 py-3 text-sm text-red-700">
          Could not load the accrual board.
        </div>
      )}

      {board.isLoading && !board.data ? (
        <div className="bg-white rounded-xl border border-gray-200 p-16 flex items-center justify-center">
          <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" aria-label="Loading" />
        </div>
      ) : board.data ? (
        <AccrualGrid
          board={board.data}
          frozen={frozen}
          busy={board.isFetching || patch.isPending}
          onOpenRow={setOpenRow}
          onPatch={(p) => patch.mutate(p)}
        />
      ) : null}

      {openRow && board.data && (
        <AccrualRowDrawer
          row={openRow}
          months={board.data.months}
          periodLabel={board.data.period.label}
          onClose={() => setOpenRow(null)}
        />
      )}
    </div>
  );
}
