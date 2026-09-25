"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  AlertOctagon, ArrowRight, CalendarClock, CalendarRange, CircleCheck, CircleDashed, Coins,
  FileWarning, Hourglass, PieChart, RefreshCw, ShieldAlert, TriangleAlert, Unlink,
} from "lucide-react";

import BoardFilterBar, { toBoardQuery, type BoardFilters } from "@/components/dashboard/BoardFilterBar";
import {
  BoardHeader, BoardTabs, EmptyState, MetaChip, Metric, Panel, SectionLabel, TD, TH,
} from "@/components/dashboard/ui/Board";
import { inrCompact, pct, rupees } from "@/lib/money";
import { defaultRange, fetchRevenueFilters } from "@/lib/revenueBoard";
import { LEVEL_META, fetchRiskSummary, type RiskLevel } from "@/lib/riskBoard";
import { cn } from "@/lib/utils";

const today = () => new Date().toISOString().slice(0, 10);
const fmtDay = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

const LEVEL_ICON = { high: AlertOctagon, medium: TriangleAlert, low: CircleCheck } as const;
const LEVEL_BAR: Record<RiskLevel, string> = {
  high: "bg-red-500", medium: "bg-amber-400", low: "bg-emerald-500",
};

function LevelChip({ level }: { level: RiskLevel }) {
  const Icon = LEVEL_ICON[level];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${LEVEL_META[level].chip}`}>
      <Icon className="w-3 h-3 shrink-0" aria-hidden />
      {LEVEL_META[level].label}
    </span>
  );
}

/**
 * The value against its two thresholds. The scale runs to 1.5× the high mark (or the
 * value, if larger), with ticks at medium and high, so "how far past the line" reads
 * without doing arithmetic.
 */
function Gauge({ value, medium, high, level }: { value: number; medium: number; high: number; level: RiskLevel }) {
  const max = Math.max(high * 1.5, value, 1);
  const at = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  return (
    <div className="relative mt-3 h-1.5 rounded-full bg-gray-100" aria-hidden>
      <div className={cn("absolute inset-y-0 left-0 rounded-full", LEVEL_BAR[level])} style={{ width: at(value) }} />
      <span className="absolute -top-0.5 h-2.5 w-px bg-amber-500" style={{ left: at(medium) }} />
      <span className="absolute -top-0.5 h-2.5 w-px bg-red-500" style={{ left: at(high) }} />
    </div>
  );
}

/** Deep link into the PLB Accrual board, pre-filtered to its leakage statuses. */
const ACCRUAL_EXCEPTIONS =
  "/dashboard/accrual?status=EXPIRED_WITH_FLOWN&status=NO_DEAL&status=NO_RATE&status=NEEDS_SPLIT";

/**
 * Risk analysis — where the income the other tabs report could fail to arrive.
 *
 * Every factor is a share of the same sale Total Revenue adds, and every threshold that
 * makes a factor medium or high comes from the server and is printed on this page, so a
 * flag can always be explained. Status colours are reserved for the level and always
 * travel with an icon and a word.
 */
export default function RiskAnalysisPage() {
  const [filters, setFilters] = useState<BoardFilters>(() => ({
    ...defaultRange(),
    as_of: today(),
    scope: "auto",
    currency: "",
    airline: [],
    segment: "",
    source: [],
  }));

  const options = useQuery({
    queryKey: ["revenue-filters", filters.scope],
    queryFn: () => fetchRevenueFilters(filters.scope),
    staleTime: 5 * 60_000,
  });
  const query = useMemo(() => toBoardQuery(filters), [filters]);
  const summary = useQuery({
    queryKey: ["risk-summary", query],
    queryFn: () => fetchRiskSummary(query),
    placeholderData: keepPreviousData,
  });

  const d = summary.data;
  const t = d?.totals;
  const busy = summary.isFetching;
  const factors = d?.factors ?? [];
  const agingMax = Math.max(1, ...(d?.unflown_aging ?? []).map((b) => b.amount));
  const counts = d?.level_counts ?? { high: 0, medium: 0, low: 0 };
  const carriers = counts.high + counts.medium + counts.low;

  const toneOf = (lv?: RiskLevel) => (lv === "high" ? "red" : lv === "medium" ? "amber" : "slate");

  return (
    <div className="space-y-4">
      <BoardTabs />

      <BoardHeader
        icon={ShieldAlert}
        title="Risk analysis"
        description="Where the revenue and income on the other tabs could fail to arrive — sale not yet flown, sale no deal covers, income that cannot be confirmed, refunds, ADMs and dependence on a single carrier."
        meta={
          <>
            {filters.date_from && filters.date_to && (
              <MetaChip icon={CalendarRange}>
                Sold {fmtDay(filters.date_from)} – {fmtDay(filters.date_to)}
              </MetaChip>
            )}
            <MetaChip icon={CalendarClock}>As of {fmtDay(d?.as_of ?? filters.as_of)}</MetaChip>
            {d?.currency && <MetaChip icon={Coins}>{d.currency}</MetaChip>}
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

      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <Metric
          hero
          icon={ShieldAlert}
          loading={busy}
          label="Airlines at high risk"
          value={`${counts.high}`}
          sub={
            d ? (
              <>
                <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-white/15 mb-2" aria-hidden>
                  {(["high", "medium", "low"] as const).map((k) =>
                    counts[k] ? (
                      <span key={k} className={LEVEL_BAR[k]} style={{ width: `${(counts[k] / Math.max(1, carriers)) * 100}%` }} />
                    ) : null,
                  )}
                </div>
                {counts.high} high · {counts.medium} medium · {counts.low} low, of {carriers} carriers with sale
              </>
            ) : null
          }
        />
        <Metric
          icon={Unlink}
          tone={toneOf(d?.overall_levels.unmatched)}
          loading={busy}
          label="Sale with no deal"
          value={inrCompact(t?.unmatched_sale ?? null)}
          progress={d?.overall_factors.unmatched ?? null}
          sub={d ? `${pct(d.overall_factors.unmatched, 1)} of issued sale earns nothing` : null}
        />
        <Metric
          icon={Hourglass}
          tone={toneOf(d?.overall_levels.undated === "high" ? "medium" : d?.overall_levels.unflown)}
          loading={busy}
          label="Not yet flown"
          value={inrCompact(t?.unflown ?? null)}
          sub={t ? `+ ${inrCompact(t.no_travel_date)} with no travel date` : null}
        />
        <Metric
          icon={FileWarning}
          tone={toneOf(d?.overall_levels.adm)}
          loading={busy}
          label="ADM exposure"
          value={inrCompact(t?.adm_exposure ?? null)}
          sub={t ? `${t.adm_count.toLocaleString("en-IN")} debit memo(s) · ACM credit ${inrCompact(t.acm_credit)}` : null}
        />
      </section>

      <SectionLabel
        hint={`Unflown & no-date on net sale ${inrCompact(t?.sold ?? null)} · the rest on issued ${inrCompact(t?.issued ?? null)}`}
      >
        Risk factors
      </SectionLabel>

      <div className={cn("grid sm:grid-cols-2 xl:grid-cols-4 gap-3 transition-opacity", busy && "opacity-60")}>
        {factors.map((f) => {
          const level = d?.overall_levels[f.key] ?? "low";
          const value = d?.overall_factors[f.key] ?? 0;
          return (
            <div key={f.key} className="flex flex-col rounded-2xl bg-white ring-1 ring-line shadow-sm p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">{f.label}</p>
                <LevelChip level={level} />
              </div>
              <p className="font-display text-[28px] font-semibold leading-none tracking-tight text-gray-900 mt-3">
                {pct(value, 1)}
              </p>
              <Gauge value={value} medium={f.medium} high={f.high} level={level} />
              <p className="text-[10px] text-gray-400 mt-1.5">Medium ≥ {f.medium}% · High ≥ {f.high}%</p>
              <p className="text-[11px] text-gray-500 mt-2 leading-snug">{f.explain}</p>
            </div>
          );
        })}
        {d && (
          <div className="flex flex-col rounded-2xl bg-white ring-1 ring-line shadow-sm p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                <PieChart className="w-3.5 h-3.5" aria-hidden /> Concentration
              </p>
              <LevelChip level={d.concentration_level} />
            </div>
            <p className="font-display text-[28px] font-semibold leading-none tracking-tight text-gray-900 mt-3">
              {pct(t?.top_airline_share_pct ?? 0, 1)}
            </p>
            <Gauge value={t?.top_airline_share_pct ?? 0} medium={40} high={60} level={d.concentration_level} />
            <p className="text-[10px] text-gray-400 mt-1.5">Medium ≥ 40% · High ≥ 60%</p>
            <p className="text-[11px] text-gray-500 mt-2 leading-snug">
              of sale on {t?.top_airline ?? "the largest carrier"}. Top three carry{" "}
              {pct(t?.top3_share_pct ?? 0, 0)}; HHI {Math.round(t?.hhi ?? 0).toLocaleString("en-IN")}.
            </p>
          </div>
        )}
      </div>

      <SectionLabel hint="Worst first">By airline</SectionLabel>

      <Panel
        flush
        loading={busy}
        title="Risk by airline"
        subtitle="Two points per high factor, one per medium. Each cell is that factor's share for the airline, shaded by its level."
        actions={
          <div className="flex items-center gap-1.5">
            {(["high", "medium", "low"] as const).map((k) => (
              <span key={k} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${LEVEL_META[k].chip}`}>
                {counts[k]} {LEVEL_META[k].label}
              </span>
            ))}
          </div>
        }
      >
        {!busy && !d?.by_airline.length ? (
          <EmptyState icon={CircleDashed}>No sale in this window.</EmptyState>
        ) : (
          <div className="max-h-[620px] overflow-auto">
            <table className="w-full min-w-max text-xs">
              <thead>
                <tr>
                  <th className={`${TH} left-0 z-[2] text-left`}>Airline</th>
                  <th className={`${TH} text-left`}>Level</th>
                  <th className={`${TH} text-right`}>Sale</th>
                  <th className={`${TH} text-right`}>Share</th>
                  {factors.map((f) => (
                    <th key={f.key} className={`${TH} text-right`} title={f.explain}>{f.label}</th>
                  ))}
                  <th className={`${TH} text-right`}>Income claimed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(d?.by_airline ?? []).map((a) => (
                  <tr key={String(a.airline_id)} className="group hover:bg-gray-50/70">
                    <td className={`${TD} sticky left-0 z-[1] bg-white group-hover:bg-gray-50 font-medium text-gray-900`}>
                      <span className="inline-flex items-center gap-2">
                        <span className={cn("h-2 w-2 rounded-full", LEVEL_BAR[a.level])} aria-hidden />
                        {a.airline}
                      </span>
                    </td>
                    <td className={TD}><LevelChip level={a.level} /></td>
                    <td className={`${TD} text-right text-gray-900`} title={rupees(a.sold)}>{inrCompact(a.sold)}</td>
                    <td className={`${TD} text-right text-gray-500`}>{pct(a.share_pct, 1)}</td>
                    {factors.map((f) => {
                      const lv = a.levels[f.key] ?? "low";
                      return (
                        <td
                          key={f.key}
                          className={cn(TD, "text-right", LEVEL_META[lv].cell, lv !== "low" && "font-semibold")}
                          title={`${f.label}: ${LEVEL_META[lv].label}`}
                        >
                          {(a.factors[f.key] ?? 0) < 0.05 ? "—" : pct(a.factors[f.key], 1)}
                        </td>
                      );
                    })}
                    <td className={`${TD} text-right text-gray-700`}>{inrCompact(a.incentive)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <SectionLabel>Exposure</SectionLabel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel
          loading={busy}
          title="Not yet flown, by how far out"
          subtitle={`Sale booked to travel after ${fmtDay(d?.as_of ?? filters.as_of)}. The further out, the longer it stays exposed to cancellation before it earns a flown incentive.`}
        >
          <ul className="space-y-4">
            {(d?.unflown_aging ?? []).map((b) => (
              <li key={b.key}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="font-medium text-gray-700">{b.label}</span>
                  <span className="font-semibold text-gray-900 tabular-nums">
                    {inrCompact(b.amount)}
                    <span className="font-normal text-gray-400"> · {b.rows.toLocaleString("en-IN")} lines</span>
                  </span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div className="h-full rounded-full bg-brand-600" style={{ width: `${(b.amount / agingMax) * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          loading={busy}
          title="Income integrity"
          subtitle="How much of the income already claimed could still move."
          footer={
            <Link
              href={ACCRUAL_EXCEPTIONS}
              className="inline-flex items-center gap-1.5 font-semibold text-brand-700 hover:text-brand-900"
            >
              PLB leakage — expired deals, zero rates, unsplit flown — on the PLB Accrual board
              <ArrowRight className="w-3.5 h-3.5" aria-hidden />
            </Link>
          }
        >
          <dl className="grid grid-cols-2 gap-3 text-xs">
            <Fact label="Income claimed" value={inrCompact(t?.incentive ?? null)} note="Priced, matched lines" />
            <Fact label="Depends on a slab" value={inrCompact(t?.slab_dependent_incentive ?? null)}
                  note="Restated if the slab is not reached" />
            <Fact label="Unconfirmable sale" value={inrCompact(t?.needs_data_sale ?? null)}
                  note="Deal pays on a figure the statement lacks" />
            <Fact label="Not priced" value={inrCompact(t?.unpriced_sale ?? null)} note="Commission never run" />
            <Fact label="Vendor under-recovery" value={inrCompact(t?.under_recovery ?? null)}
                  note={`${(t?.declared_mismatch_rows ?? 0).toLocaleString("en-IN")} line(s) where the declared net does not tie`} />
            <Fact label="Refunded" value={inrCompact(t?.refunds == null ? null : Math.abs(t.refunds))}
                  note={d ? `${pct(d.overall_factors.refund, 1)} of issued sale` : undefined} />
          </dl>
        </Panel>
      </div>
    </div>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl bg-paper ring-1 ring-line p-3">
      <dt className="text-[10px] uppercase tracking-wide text-gray-500 font-semibold">{label}</dt>
      <dd className="font-display text-lg font-semibold text-gray-900 mt-1">{value}</dd>
      {note && <dd className="text-[11px] text-gray-500 mt-0.5 leading-snug">{note}</dd>}
    </div>
  );
}
