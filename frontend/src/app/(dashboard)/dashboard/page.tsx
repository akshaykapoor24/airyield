"use client";

import { useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight, LayoutGrid, Lock, RefreshCw } from "lucide-react";

import EntityHeatGrid from "@/components/dashboard/charts/EntityHeatGrid";
import AirlineContribution from "@/components/dashboard/charts/AirlineContribution";
import FilterBar, { filtersFromUrl, type FilterState } from "@/components/dashboard/FilterBar";
import KpiTile from "@/components/dashboard/KpiTile";
import StatusBadge from "@/components/dashboard/StatusBadge";
import { AccrualByMonthChart, FlownByMonthChart } from "@/components/dashboard/charts/MonthlyCharts";
import { fetchFilters, fetchOverview, STATUS } from "@/lib/accrual";
import { inrCompact, pct, rupees } from "@/lib/money";

/**
 * The executive layer over the PLB accrual board.
 *
 * Everything here is derived from the same board the grid renders, so the two can
 * never tell different stories. Exactly one hero figure: the accrual itself, which
 * is the number that goes on the P&L.
 */
export default function OverviewPage() {
  // Seeded from the query string so the Overview's exception cards can deep-link
  // into a pre-filtered board.
  const [filters, setFilters] = useState<FilterState>(filtersFromUrl);

  const filterOptions = useQuery({
    queryKey: ["accrual-filters", filters.period],
    queryFn: () => fetchFilters(filters.period || undefined),
    staleTime: 5 * 60_000,
  });

  const query = {
    period: filters.period || undefined,
    basis: filters.basis,
    entity: filters.entity,
    channel: filters.channel,
  };

  const ov = useQuery({
    queryKey: ["accrual-overview", query],
    queryFn: () => fetchOverview(query),
    placeholderData: keepPreviousData,
  });

  const d = ov.data;
  const t = d?.totals;
  const busy = ov.isFetching;

  const monthly = (d?.monthly ?? []).map((m) => {
    // The confirmed/provisional split is a period-level ratio; applying it per
    // month keeps the stacked column honest about the whole without pretending to
    // a per-month breakdown the board does not carry.
    const share = t && t.flown_total ? t.flown_confirmed / t.flown_total : 0;
    return {
      ...m,
      confirmed: Math.round(m.flown * share),
      provisional: Math.round(m.flown * (1 - share)),
    };
  });

  const actions = d?.actions;
  const actionTotal = actions
    ? actions.pending_deal_approvals + actions.deals_awaiting_review +
      actions.statements_awaiting_commission + actions.unmatched_commission_rows
    : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
          <LayoutGrid className="w-5 h-5 text-blue-600" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
            Dashboard
          </p>
          <h1 className="text-xl font-bold text-gray-900">Overview</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Supplier income accrued on flown revenue for {d?.period.label ?? "this period"}.
          </p>
        </div>
        <Link
          href="/dashboard/accrual"
          className="ml-auto shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-[#1e3a5f] hover:bg-[#16304f] text-white px-3 h-9.5 text-xs font-semibold"
        >
          Open the accrual board <ArrowRight className="w-3.5 h-3.5" aria-hidden />
        </Link>
      </div>

      <FilterBar
        value={filters}
        onChange={setFilters}
        options={filterOptions.data}
        showRowFilters={false}
        extra={
          busy ? (
            <RefreshCw className="w-3.5 h-3.5 text-gray-400 animate-spin" aria-label="Refreshing" />
          ) : null
        }
      />

      {d?.frozen && (
        <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 px-4 py-2.5 flex items-center gap-2 text-xs text-slate-700">
          <Lock className="w-3.5 h-3.5 shrink-0" aria-hidden />
          <span>
            <strong>{d.period.label} is frozen.</strong> These figures are the booked
            accrual and will not move when new statements arrive.
          </span>
        </div>
      )}

      {/* KPI band */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <KpiTile
          hero
          loading={busy}
          label={`PLB accrued · ${d?.period.label ?? ""}`}
          value={t ? rupees(t.accrual) : "—"}
          sub={
            t ? (
              <>
                {pct(t.effective_yield_pct)} of flown revenue.
                {t.accrual_at_risk !== 0 && (
                  <span className="block text-red-600 font-medium mt-0.5">
                    {rupees(Math.abs(t.accrual_at_risk))} of it rests on contracts that do
                    not cover these months.
                  </span>
                )}
              </>
            ) : null
          }
        />
        <KpiTile
          loading={busy}
          label="Provisional flown"
          value={t ? inrCompact(t.flown_total) : "—"}
          sub={
            t ? (
              <>
                {inrCompact(t.flown_confirmed)} confirmed ·{" "}
                {inrCompact(t.flown_provisional)} provisional
              </>
            ) : null
          }
        />
        <KpiTile
          loading={busy}
          label="Commissionable base"
          value={t ? inrCompact(t.commissionable_base) : "—"}
          sub={t ? <>Effective deflator {pct(t.effective_deflator_pct)}</> : null}
        />
        <KpiTile
          loading={busy}
          tone={t && t.flown_at_risk ? "danger" : "default"}
          label="Flown revenue at risk"
          value={t ? inrCompact(t.flown_at_risk) : "—"}
          sub="Flown with an expired deal, no deal, or a 0% rate."
        />
        <KpiTile
          loading={busy}
          tone={actionTotal ? "warning" : "default"}
          label="Waiting on someone"
          value={String(actionTotal)}
          sub={
            actions ? (
              <span className="flex flex-col gap-0.5">
                <Link href="/deals/approvals" className="hover:text-gray-800 hover:underline">
                  {actions.pending_deal_approvals} deal approvals
                </Link>
                <Link href="/deals" className="hover:text-gray-800 hover:underline">
                  {actions.deals_awaiting_review} deals awaiting review
                </Link>
                <Link href="/vendors/commission-income" className="hover:text-gray-800 hover:underline">
                  {actions.statements_awaiting_commission} statements not costed
                </Link>
              </span>
            ) : null
          }
        />
      </div>

      {/* Charts — two plots, one y-scale each. See MonthlyCharts for why. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <FlownByMonthChart data={monthly} />
        <AccrualByMonthChart data={monthly} />
      </div>

      {/* The Pareto and the exception list are both list-shaped and roughly the
          same height, so they pair. The entity matrix is wide by nature and gets
          the full width below them rather than being cut off by a card edge. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
        <AirlineContribution rows={d?.by_airline ?? []} />
        <div className="space-y-3">
          {/* Exceptions — each links into the board, pre-filtered to itself. */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-900">Needs attention</h2>
            <p className="text-xs text-gray-500 mb-3">
              The red and amber someone used to apply by hand, computed.
            </p>
            {!d?.exceptions.length ? (
              <p className="text-xs text-gray-400 py-6 text-center">
                Nothing flagged in this period.
              </p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {d.exceptions.map((e) => (
                  <li key={e.code}>
                    <Link
                      href={`/dashboard/accrual?status=${e.code}`}
                      className="flex items-center gap-3 py-2.5 group"
                    >
                      <StatusBadge code={e.code} />
                      <span className="flex-1 min-w-0">
                        <span className="block text-xs font-medium text-gray-800 truncate">
                          {e.label}
                        </span>
                        <span className="block text-[11px] text-gray-400 truncate">
                          {e.airlines.join(", ")}
                          {e.count > e.airlines.length && " and more"}
                        </span>
                      </span>
                      <span className="text-right shrink-0">
                        <span className="block text-xs font-semibold text-gray-900 tabular-nums">
                          {rupees(Math.abs(e.amount))}
                        </span>
                        <span className="block text-[10px] text-gray-400">
                          {e.count} {e.count === 1 ? "line" : "lines"}
                        </span>
                      </span>
                      <ArrowRight
                        className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 shrink-0"
                        aria-hidden
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {d && <EntityHeatGrid rows={d.by_entity} airlines={d.entity_airlines} />}

      {!!d?.data_quality.unattributed_airlines.length && (
        <div className="rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-2.5 text-xs text-amber-900">
          <strong>{d.data_quality.unattributed_airlines.length} airlines</strong> have flown
          revenue that could not be attributed to a single entity
          ({d.data_quality.unattributed_airlines.slice(0, 5).join(", ")}
          {d.data_quality.unattributed_airlines.length > 5 && ", …"}). Their accrual is
          understated until the split is keyed on the{" "}
          <Link href="/dashboard/accrual?status=NEEDS_SPLIT" className="underline font-semibold">
            accrual board
          </Link>
          , or the matching BSP summary statements are uploaded so the agent codes resolve.
        </div>
      )}

      <p className="text-[11px] text-gray-400 text-center pt-2">
        {STATUS.UNCONFIRMED.blurb} Every figure here is also in the{" "}
        <Link href="/dashboard/accrual" className="underline">accrual board</Link>, row by row.
      </p>
    </div>
  );
}
