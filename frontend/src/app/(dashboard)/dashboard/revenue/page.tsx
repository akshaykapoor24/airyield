"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck, CalendarRange, Clock, Coins, Globe2, Layers, Package, Receipt, RefreshCw,
  TriangleAlert, Users, Wallet,
} from "lucide-react";
import toast from "react-hot-toast";

import {
  BoardHeader, BoardTabs, MetaChip, Metric, Notice, Panel, SectionLabel,
} from "@/components/dashboard/ui/Board";
import AirlineDrawer from "@/components/dashboard/revenue/AirlineDrawer";
import AirlineMatrix from "@/components/dashboard/revenue/AirlineMatrix";
import RevenueFilterBar, {
  type RevenueFilters,
} from "@/components/dashboard/revenue/RevenueFilterBar";
import NotCountedPanel from "@/components/dashboard/revenue/NotCountedPanel";
import SourceCards from "@/components/dashboard/revenue/SourceCards";
import MixDonut, { type Slice } from "@/components/dashboard/revenue/charts/MixDonut";
import {
  IncentiveByMonthChart, SaleByMonthChart,
} from "@/components/dashboard/revenue/charts/ByMonthCharts";
import { fetchIncomeFreshness, rebuildIncomeBoard } from "@/lib/incomeBoard";
import { inrCompact, pct, rupees } from "@/lib/money";
import {
  INCENTIVE_COLORS, MAX_INCENTIVE_SLICES, SOURCE_COLOR,
} from "@/lib/revenueCharts";
import {
  defaultRange, fetchIncentiveTypes, fetchRevenueFilters, fetchRevenueSummary,
  SOURCE_SHORT, type AirlineRevenuePoint, type RevenueQuery,
} from "@/lib/revenueBoard";

/**
 * Total Revenue — what the loaded statements sold, and what that sale earned.
 *
 * THIS IS NOT THE COMMISSION INCOME BOARD. /dashboard/income answers "what have the
 * statements we have PRICED earned us" and counts only priced lines; this answers "what
 * did we sell", which includes every statement in the workspace whether or not anybody
 * has run commission on it. The two read the same projection through two predicates, so
 * a carrier's gross cannot mean one thing here and another there — but the headline
 * figures are different questions and are never added together.
 *
 * TWO RULES THE SCREEN KEEPS, both of which are ways of not lying about a total.
 * Twelve statement types cover six businesses — a TGQ ticket is its BSP row, a memo
 * counts through the BSP row it was raised against, a flown line is its LCC booking — so
 * only the six that ARE the sale are added, and what was held out is reported with its
 * reason rather than quietly dropped. And totals are per currency, never converted:
 * the board picks one, says which, and says what that left behind.
 */
export default function TotalRevenuePage() {
  const [filters, setFilters] = useState<RevenueFilters>(() => ({
    ...defaultRange(),
    basis: "issue",
    scope: "auto",
    currency: "",
    airline: [],
    supplier: [],
    source: [],
    category: [],
  }));
  const [open, setOpen] = useState<AirlineRevenuePoint | null>(null);
  const qc = useQueryClient();

  const options = useQuery({
    queryKey: ["revenue-filters", filters.scope],
    queryFn: () => fetchRevenueFilters(filters.scope),
    staleTime: 5 * 60_000,
  });

  const query: RevenueQuery = useMemo(() => ({
    scope: filters.scope,
    basis: filters.basis,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    airline: filters.airline.length ? filters.airline : undefined,
    supplier: filters.supplier.length ? filters.supplier : undefined,
    source: filters.source.length ? filters.source : undefined,
    category: filters.category.length ? filters.category : undefined,
    currency: filters.currency || undefined,
    top: 25,
  }), [filters]);

  const summary = useQuery({
    queryKey: ["revenue-summary", query],
    queryFn: () => fetchRevenueSummary(query),
    // The board updates in place on a filter change instead of flashing empty.
    placeholderData: keepPreviousData,
  });

  // Its own query, not part of /summary: a LATERAL over a JSONB column is the most
  // expensive read on the board, and this card is one of several.
  const incentives = useQuery({
    queryKey: ["revenue-incentive-types", query],
    queryFn: () => fetchIncentiveTypes(query),
    placeholderData: keepPreviousData,
  });

  // Shared with the Commission income tab — one projection, so one freshness answer.
  const freshness = useQuery({
    queryKey: ["income-freshness", filters.scope],
    queryFn: fetchIncomeFreshness,
    staleTime: 60_000,
  });

  const rebuild = useMutation({
    mutationFn: rebuildIncomeBoard,
    onSuccess: (r) => {
      const n = Object.values(r.rows_by_source).reduce((a, b) => a + b, 0);
      toast.success(`Rebuilt ${n.toLocaleString("en-IN")} lines from ${r.batches} uploads`);
      if (r.failed.length) toast.error(`${r.failed.length} upload(s) failed — see server logs`);
      ["revenue-summary", "revenue-incentive-types", "revenue-filters",
       "income-freshness", "income-summary"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] }));
    },
    onError: () => toast.error("Rebuild failed"),
  });

  const d = summary.data;
  const t = d?.totals;
  const busy = summary.isFetching;
  const fr = freshness.data;

  const saleSlices: Slice[] = (d?.by_source ?? []).map((s) => ({
    key: s.source,
    label: SOURCE_SHORT[s.source] ?? s.label,
    value: s.sale ?? 0,
    color: SOURCE_COLOR[s.source] ?? "#94a3b8",
  }));

  const incentiveSlices: Slice[] = (incentives.data ?? []).map((i, idx) => ({
    key: i.incentive_type,
    label: i.incentive_type,
    value: i.amount ?? 0,
    color: INCENTIVE_COLORS[idx] ?? "#94a3b8",
  }));

  const otherCurrencies = Object.entries(d?.other_currencies ?? {});

  const fmtDay = (iso: string) =>
    new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const yieldPct = t?.sale && t.incentive ? (t.incentive / t.sale) * 100 : null;

  return (
    <div className="space-y-4">
      <BoardTabs />

      <BoardHeader
        icon={Receipt}
        title="Total Revenue"
        description="What your loaded statements sold, and what that sale earned. Only the six types that ARE the sale are added — the ones that restate them are shown beside each airline, never inside the total."
        meta={
          <>
            {filters.date_from && filters.date_to && (
              <MetaChip icon={CalendarRange}>
                {fmtDay(filters.date_from)} – {fmtDay(filters.date_to)}
              </MetaChip>
            )}
            <MetaChip icon={Clock}>{filters.basis === "travel" ? "Travel basis" : "Sales basis"}</MetaChip>
            {d?.currency && <MetaChip icon={Coins}>{d.currency}</MetaChip>}
            {d?.scope && (
              <MetaChip icon={Users}>{d.scope === "agency" ? "Whole agency" : "My uploads"}</MetaChip>
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

      <RevenueFilterBar value={filters} onChange={setFilters} options={options.data} />

      {/* A wrong board is worse than no board, so staleness blocks rather than whispers.
          Shared with Commission income: same table, same banner, one Rebuild. */}
      {fr && !fr.ok && (
        <Notice
          icon={TriangleAlert}
          title="This board is behind the statements that have been loaded."
          action={
            <button
              onClick={() => rebuild.mutate()}
              disabled={rebuild.isPending}
              className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5
                         text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-60"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${rebuild.isPending ? "animate-spin" : ""}`} aria-hidden />
              {rebuild.isPending ? "Rebuilding…" : "Rebuild now"}
            </button>
          }
        >
          {fr.never_total > 0 && `${fr.never_total} upload(s) have never been projected. `}
          {fr.stale_total > 0 && `${fr.stale_total} upload(s) changed after their last projection. `}
          Figures below exclude them.
        </Notice>
      )}

      {/* KPI band */}
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <Metric
          hero
          icon={Wallet}
          loading={busy}
          label={`Total sale${d?.currency ? ` · ${d.currency}` : ""}`}
          value={inrCompact(t?.sale ?? null)}
          sub={
            t ? (
              <>
                {t.sale_rows.toLocaleString("en-IN")} lines across six statement types.
                {t.not_counted_rows > 0 && (
                  <span className="block mt-0.5 opacity-80">
                    {inrCompact(t.not_counted_sale)} held out — {t.not_counted_rows.toLocaleString("en-IN")} lines
                    that restate another statement, or never were a sale.
                  </span>
                )}
              </>
            ) : null
          }
        />
        <Metric
          icon={Coins}
          tone="emerald"
          loading={busy}
          label="Commission earned"
          value={inrCompact(t?.incentive ?? null)}
          sub={yieldPct != null ? `${pct(yieldPct, 2)} of sale` : t ? "Nothing priced yet" : null}
        />
        <Metric
          icon={BadgeCheck}
          tone="slate"
          loading={busy}
          label="IATA commission"
          value={inrCompact(t?.iata_commission ?? null)}
          sub="Separate entitlement — not added to commission earned"
        />
        <Metric
          icon={Clock}
          tone={t && t.unpriced_rows > 0 ? "amber" : "slate"}
          loading={busy}
          label="Not yet priced"
          value={(t?.unpriced_rows ?? 0).toLocaleString("en-IN")}
          progress={t && t.sale_rows ? (t.unpriced_rows / t.sale_rows) * 100 : null}
          sub="Lines whose sale counts and whose commission has not been run"
        />
      </section>

      {!!otherCurrencies.length && (
        <Notice tone="slate" icon={Globe2} title={`Showing ${d?.currency} only`}>
          Totals are never converted or added across currencies, so{" "}
          {otherCurrencies.map(([c, n], i) => (
            <span key={c}>
              {i > 0 && ", "}
              <strong>{n.toLocaleString("en-IN")}</strong> {c} line{n === 1 ? "" : "s"}
            </span>
          ))}{" "}
          {otherCurrencies.length === 1 ? "is" : "are"} not in the figures above. Switch
          currency in the filter row to see them.
        </Notice>
      )}

      <SectionLabel hint="By statement family and type">Composition</SectionLabel>

      <SourceCards
        categories={d?.by_category ?? []}
        sources={d?.by_source ?? []}
        loading={busy}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <MixDonut
          title="Sale mix"
          note="What the total is made of. For comparing sizes, read the table below."
          slices={saleSlices}
          loading={busy}
          empty="No sale in this period."
        />
        <MixDonut
          title="Commission mix"
          note="Which incentive earned it — PLB, Super PLB, transaction fee and the rest."
          slices={incentiveSlices}
          fold={MAX_INCENTIVE_SLICES}
          loading={incentives.isFetching}
          empty="Nothing priced in this period. Run commission on a statement."
        />
      </div>

      <SectionLabel hint={filters.basis === "travel" ? "By travel month" : "By sale month"}>Trend</SectionLabel>

      {/* Two plots, one y-scale each. Sale runs in crores and the incentive it earns
          runs in lakhs — see ByMonthCharts for why that is never one chart. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <SaleByMonthChart data={d?.by_month ?? []} />
        <IncentiveByMonthChart data={d?.by_month ?? []} />
      </div>

      <SectionLabel hint="Click an airline for its detail">Breakdown</SectionLabel>

      <AirlineMatrix
        rows={d?.by_airline ?? []}
        onOpen={setOpen}
        loading={busy}
      />

      <NotCountedPanel rows={d?.not_counted ?? []} />

      {(!!d?.by_product.length || !!d?.by_supplier.length) && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {!!d?.by_product.length && (
            <Panel
              title="Third Party API, by product"
              subtitle={
                <>
                  An aggregator file carries hotel, flight, train, bus and car bookings side
                  by side. These rows name no carrier, so they are absent from the airline
                  table — <em>not carrier-attributed</em>, which is different from a carrier
                  that could not be resolved.
                </>
              }
            >
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {d.by_product.map((p) => (
                  <div key={p.product ?? "none"} className="rounded-xl bg-paper ring-1 ring-line p-3">
                    <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                      <Package className="w-3 h-3" aria-hidden />
                      {p.product ?? "No category"}
                    </p>
                    <p className="font-display text-lg font-semibold text-gray-900 mt-1">{inrCompact(p.sale)}</p>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      {p.rows.toLocaleString("en-IN")} bookings · {p.share_pct.toFixed(0)}%
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {!!d?.by_supplier.length && (
            <Panel
              title="By consolidator"
              subtitle="Third-party statements only. One row is one branch — branches bill separately."
              actions={<Layers className="w-4 h-4 text-gray-300" aria-hidden />}
            >
              <ul className="space-y-3">
                {d.by_supplier.map((s) => (
                  <li key={String(s.supplier_id ?? "none")} className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 truncate">{s.supplier}</p>
                      <div className="mt-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.max(s.share_pct, 1)}%`,
                            background: SOURCE_COLOR["tp-gds"],
                          }}
                        />
                      </div>
                      <p className="text-[11px] text-gray-500 mt-0.5 truncate">
                        {[s.supplier_code, s.branch].filter(Boolean).join(" · ") ||
                          `${s.rows.toLocaleString("en-IN")} lines`}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold text-gray-900 tabular-nums">
                        {inrCompact(s.sale)}
                      </p>
                      <p className="text-[11px] text-gray-500 tabular-nums">
                        {s.incentive == null ? "—" : rupees(s.incentive)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}

      {t && (t.unattributed_airline_rows > 0 || t.undated_rows > 0) && (
        <p className="text-[11px] text-gray-400 text-center pt-2">
          {t.unattributed_airline_rows > 0 &&
            `${t.unattributed_airline_rows.toLocaleString("en-IN")} line(s) carry a carrier the airline master could not resolve. `}
          {t.undated_rows > 0 &&
            `${t.undated_rows.toLocaleString("en-IN")} line(s) print a date no pattern could read, so they are in the totals but in no month.`}
        </p>
      )}

      {open?.airline_id != null && (
        <AirlineDrawer
          airlineId={open.airline_id}
          airlineName={open.airline}
          query={query}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}
