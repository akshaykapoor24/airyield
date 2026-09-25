"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  CalendarClock, CalendarRange, CircleDashed, Coins, Globe2, HelpCircle, PlaneLanding,
  PlaneTakeoff, RefreshCw, TriangleAlert, Wallet,
} from "lucide-react";

import BoardFilterBar, { toBoardQuery, type BoardFilters } from "@/components/dashboard/BoardFilterBar";
import CohortMatrix, { type CohortMode } from "@/components/dashboard/flown/CohortMatrix";
import FlownByMonthChart from "@/components/dashboard/flown/FlownByMonthChart";
import PlbSlabPanel from "@/components/dashboard/flown/PlbSlabPanel";
import {
  BoardHeader, BoardTabs, EmptyState, MetaChip, Metric, Notice, Panel, SectionLabel, TD, TH,
} from "@/components/dashboard/ui/Board";
import { inrCompact, pct, rupees } from "@/lib/money";
import { defaultRange, fetchRevenueFilters } from "@/lib/revenueBoard";
import { fetchSalesFlown } from "@/lib/salesFlown";
import { cn } from "@/lib/utils";

const today = () => new Date().toISOString().slice(0, 10);
const fmtDay = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

/**
 * Sales vs Flown — of what we sold, how much has flown, and what that flown earns.
 *
 * A ticket is sold on its issue date and earns a flown-based incentive only on its travel
 * date. This is finance's cohort sheet off the data: each sale month, how much of it flew
 * in each later month, the commissionable (non-excluded) share of that flown, and where
 * the carrier's flown stands against its PLB slabs.
 *
 * The sale figure is Total Revenue's — same lines, same predicate — so the two tabs agree
 * for the same window.
 */
export default function SalesVsFlownPage() {
  const [filters, setFilters] = useState<BoardFilters>(() => ({
    ...defaultRange(),
    as_of: today(),
    scope: "auto",
    currency: "",
    airline: [],
    segment: "",
    source: [],
  }));
  const [mode, setMode] = useState<CohortMode>("pct");
  // Blank = use the exclusion observed on the flown lines; a number = the user's override.
  const [exclusionOverride, setExclusionOverride] = useState<string>("");

  const options = useQuery({
    queryKey: ["revenue-filters", filters.scope],
    queryFn: () => fetchRevenueFilters(filters.scope),
    staleTime: 5 * 60_000,
  });

  const query = useMemo(() => toBoardQuery(filters), [filters]);
  const summary = useQuery({
    queryKey: ["sales-flown", query],
    queryFn: () => fetchSalesFlown(query),
    placeholderData: keepPreviousData,
  });

  const d = summary.data;
  const t = d?.totals;
  const busy = summary.isFetching;
  const asOfYm = (d?.as_of ?? filters.as_of).slice(0, 7);

  const observedExclusion = t?.deflator_pct == null ? null : 100 - t.deflator_pct;
  const overrideNum = exclusionOverride.trim() === "" ? null : Number(exclusionOverride);
  const exclusion =
    overrideNum != null && !Number.isNaN(overrideNum)
      ? Math.min(100, Math.max(0, overrideNum))
      : observedExclusion;

  const sold = t?.sold ?? 0;
  const share = (v: number | null | undefined) => (sold ? ((v ?? 0) / sold) * 100 : 0);
  const undatedShare = share(t?.no_travel_date);
  const otherCurrencies = Object.entries(d?.other_currencies ?? {});
  const eligible = t?.flown != null && exclusion != null ? t.flown * (1 - exclusion / 100) : null;

  return (
    <div className="space-y-4">
      <BoardTabs />

      <BoardHeader
        icon={PlaneTakeoff}
        title="Sales vs Flown"
        description="Of what you sold, how much has flown and when — and what that flown earns against the PLB slabs. Sold on the issue date, flown on the travel date."
        meta={
          <>
            {filters.date_from && filters.date_to && (
              <MetaChip icon={CalendarRange}>
                Sold {fmtDay(filters.date_from)} – {fmtDay(filters.date_to)}
              </MetaChip>
            )}
            <MetaChip icon={CalendarClock}>Flown as of {fmtDay(d?.as_of ?? filters.as_of)}</MetaChip>
            {d?.currency && <MetaChip icon={Coins}>{d.currency}</MetaChip>}
            {filters.segment && (
              <MetaChip>{filters.segment === "D" ? "Domestic" : "International"}</MetaChip>
            )}
          </>
        }
        actions={
          busy ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[11px] text-white/80">
              <RefreshCw className="w-3 h-3 animate-spin" aria-hidden /> Updating
            </span>
          ) : null
        }
      />

      <BoardFilterBar value={filters} onChange={setFilters} options={options.data} />

      {t && undatedShare >= 5 && (
        <Notice
          icon={TriangleAlert}
          title={`${pct(undatedShare, 0)} of this sale (${inrCompact(t.no_travel_date)}) carries no travel date, so it cannot be split into flown and not flown.`}
        >
          BSP settlement rows print no travel date of their own. Upload the matching TGQ HMPR
          statements (and rebuild) to place them on the month they actually flew. Until then
          the flown figures below are a floor, not the full picture.
        </Notice>
      )}

      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
        <Metric
          hero
          className="xl:col-span-1"
          icon={Wallet}
          loading={busy}
          label={`Sold${d?.currency ? ` · ${d.currency}` : ""}`}
          value={inrCompact(t?.sold ?? null)}
          sub={t ? `${t.rows.toLocaleString("en-IN")} lines · refunds of ${inrCompact(t.refunds)} netted` : null}
        />
        <Metric
          icon={PlaneLanding}
          tone="emerald"
          loading={busy}
          label="Flown"
          value={inrCompact(t?.flown ?? null)}
          progress={t ? share(t.flown) : null}
          sub={t ? `${pct(share(t.flown), 1)} of sold` : null}
        />
        <Metric
          icon={PlaneTakeoff}
          tone="brand"
          loading={busy}
          label="Not yet flown"
          value={inrCompact(t?.unflown ?? null)}
          progress={t ? share(t.unflown) : null}
          sub={t ? `${pct(share(t.unflown), 1)} of sold — booked to travel later` : null}
        />
        <Metric
          icon={HelpCircle}
          tone={undatedShare >= 5 ? "amber" : "slate"}
          loading={busy}
          label="No travel date"
          value={inrCompact(t?.no_travel_date ?? null)}
          progress={t ? undatedShare : null}
          sub={t ? `${pct(undatedShare, 1)} of sold · ${t.no_travel_date_rows.toLocaleString("en-IN")} lines` : null}
        />
        <Metric
          icon={Coins}
          tone="emerald"
          loading={busy}
          label="Eligible flown"
          value={inrCompact(eligible)}
          sub={exclusion != null ? `After ${pct(exclusion, 1)} exclusion` : "Set an exclusion to compute"}
        />
      </section>

      {!!otherCurrencies.length && (
        <Notice tone="slate" icon={Globe2} title={`Showing ${d?.currency} only`}>
          Totals are never added across currencies.{" "}
          {otherCurrencies.map(([c, n]) => `${n.toLocaleString("en-IN")} ${c}`).join(", ")}{" "}
          line(s) are not in these figures.
        </Notice>
      )}

      <SectionLabel hint="Sale month × travel month">Cohort</SectionLabel>

      <Panel
        flush
        loading={busy}
        title="Sold month × flown month"
        subtitle="Each row is one month's sale; each column is when it flew. Eligible = flown × (1 − exclusion)."
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              Exclusion
              <span className="relative">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={exclusionOverride}
                  placeholder={observedExclusion == null ? "—" : observedExclusion.toFixed(1)}
                  onChange={(e) => setExclusionOverride(e.target.value)}
                  className="w-24 rounded-lg border border-gray-200 py-1.5 pl-2.5 pr-6 text-xs focus:outline-none focus:ring-1 focus:ring-brand-400"
                  title="Blank = the share observed on flown lines (gross that is not Basic fare). Type a figure to override."
                />
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">%</span>
              </span>
            </label>
            <div className="inline-flex rounded-lg bg-gray-100 p-0.5 text-xs" role="tablist">
              {(["pct", "amount"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  onClick={() => setMode(m)}
                  className={cn(
                    "rounded-md px-3 py-1 font-medium transition-colors",
                    mode === m ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-800",
                  )}
                >
                  {m === "pct" ? "% of sale" : "Amount"}
                </button>
              ))}
            </div>
          </>
        }
        footer={
          overrideNum != null
            ? `Using your exclusion of ${pct(exclusion, 1)}. Clear the box to go back to the observed figure.`
            : observedExclusion != null
              ? `Exclusion ${pct(observedExclusion, 1)} is observed: the share of flown gross that is not Basic fare, on the ${pct(t?.deflator_coverage_pct, 0)} of flown lines that print a fare breakdown.`
              : "No flown line prints a fare breakdown, so no exclusion can be observed — type one to see eligible flown."
        }
      >
        <CohortMatrix
          rows={d?.cohorts ?? []}
          months={d?.flown_months ?? []}
          asOfYm={asOfYm}
          exclusionPct={exclusion}
          mode={mode}
        />
      </Panel>

      <SectionLabel hint="Travel basis · PLB period">Flown &amp; slabs</SectionLabel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <FlownByMonthChart data={d?.flown_by_month ?? []} />
        <PlbSlabPanel airline={d?.plb_airline ?? null} lines={d?.plb_lines ?? []} loading={busy} />
      </div>

      <SectionLabel hint="Click an airline to focus the board">By airline</SectionLabel>

      <Panel
        flush
        loading={busy}
        title="Flown by airline"
        subtitle="Selecting an airline also opens its PLB slab progress above."
      >
        {!busy && !d?.by_airline.length ? (
          <EmptyState icon={CircleDashed}>No sale in this window.</EmptyState>
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full min-w-max text-xs">
              <thead>
                <tr>
                  <th className={`${TH} text-left`}>Airline</th>
                  <th className={`${TH} text-right`}>Sold</th>
                  <th className={`${TH} text-right`}>Flown</th>
                  <th className={`${TH} text-left w-48`}>Flown share</th>
                  <th className={`${TH} text-right`}>Not yet flown</th>
                  <th className={`${TH} text-right`}>No travel date</th>
                  <th className={`${TH} text-right`}>Commissionable</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(d?.by_airline ?? []).map((a) => {
                  const active = a.airline_id != null && filters.airline.length === 1 && filters.airline[0] === a.airline_id;
                  return (
                    <tr
                      key={String(a.airline_id)}
                      className={cn(
                        a.airline_id != null && "cursor-pointer hover:bg-brand-50/60",
                        active && "bg-brand-50",
                      )}
                      onClick={() =>
                        a.airline_id != null && setFilters({ ...filters, airline: [a.airline_id] })
                      }
                    >
                      <td className={`${TD} font-medium text-gray-900`}>{a.airline}</td>
                      <td className={`${TD} text-right text-gray-900`} title={rupees(a.sold)}>{inrCompact(a.sold)}</td>
                      <td className={`${TD} text-right text-gray-900`} title={rupees(a.flown)}>{inrCompact(a.flown)}</td>
                      <td className={TD}>
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 flex-1 rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className="h-full rounded-full bg-emerald-600"
                              style={{ width: `${Math.min(100, Math.max(0, a.flown_pct))}%` }}
                            />
                          </div>
                          <span className="w-10 text-right font-medium text-gray-700">{pct(a.flown_pct, 0)}</span>
                        </div>
                      </td>
                      <td className={`${TD} text-right text-gray-700`}>{inrCompact(a.unflown)}</td>
                      <td className={`${TD} text-right text-gray-400`}>{inrCompact(a.no_travel_date)}</td>
                      <td className={`${TD} text-right text-gray-700`}>{pct(a.deflator_pct, 1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="text-[11px] text-gray-400 text-center pt-1">
        Flown is inferred from the travel date the statement printed. A no-show or a
        cancellation shows only once its refund is loaded.
      </p>
    </div>
  );
}
