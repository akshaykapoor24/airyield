"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, Building2, DollarSign, Plane, RefreshCw, TriangleAlert,
} from "lucide-react";
import toast from "react-hot-toast";

import KpiTile from "@/components/dashboard/KpiTile";
import {
  defaultRange, fetchIncomeFilters, fetchIncomeFreshness, fetchIncomeSummary,
  rebuildIncomeBoard, type AirlinePoint, type IncomeBasis, type IncomeScope,
  type SupplierPoint,
} from "@/lib/incomeBoard";
import { inrCompact, pct, rupees } from "@/lib/money";

/**
 * Realized commission income, by carrier and by consolidator.
 *
 * THIS IS NOT THE ACCRUAL BOARD. /dashboard/accrual answers "what will we earn if the
 * slabs hold" and is a forecast; this answers "what have the statements we have loaded
 * actually earned us". The two are never added together, and the only reference to
 * accrual here is a link, deliberately.
 *
 * TWO RULES THE SCREEN KEEPS. A null incentive renders as an em dash with the row count
 * beside it, never as ₹0 — "we could not confirm what you are owed" is a different
 * statement from "you are owed nothing". And IATA commission has its own tile: it is a
 * separate entitlement and adding it to the incentive would overstate income.
 */
export default function IncomeBoardPage() {
  const [scope, setScope] = useState<IncomeScope>("mine");
  const [basis, setBasis] = useState<IncomeBasis>("issue");
  const [range] = useState(defaultRange);
  const qc = useQueryClient();

  const filters = useQuery({
    queryKey: ["income-filters", scope],
    queryFn: () => fetchIncomeFilters(scope),
    staleTime: 5 * 60_000,
  });

  const query = { scope, basis, ...range, top: 10 };
  const summary = useQuery({
    queryKey: ["income-summary", query],
    queryFn: () => fetchIncomeSummary(query),
    placeholderData: keepPreviousData,
  });

  const freshness = useQuery({
    queryKey: ["income-freshness"],
    queryFn: fetchIncomeFreshness,
    staleTime: 60_000,
  });

  const rebuild = useMutation({
    mutationFn: rebuildIncomeBoard,
    onSuccess: (r) => {
      const n = Object.values(r.rows_by_source).reduce((a, b) => a + b, 0);
      toast.success(`Rebuilt ${n.toLocaleString("en-IN")} rows from ${r.batches} batches`);
      if (r.failed.length) toast.error(`${r.failed.length} batch(es) failed — see server logs`);
      qc.invalidateQueries({ queryKey: ["income-summary"] });
      qc.invalidateQueries({ queryKey: ["income-freshness"] });
      qc.invalidateQueries({ queryKey: ["income-filters"] });
    },
    onError: () => toast.error("Rebuild failed"),
  });

  const d = summary.data;
  const t = d?.totals;
  const busy = summary.isFetching;
  const fr = freshness.data;

  const maxMonth = useMemo(
    () => Math.max(1, ...(d?.by_month ?? []).map((m) => Math.abs(m.incentive ?? 0))),
    [d],
  );

  return (
    <div className="space-y-4">
      <header className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center shrink-0">
          <DollarSign className="w-5 h-5 text-emerald-600" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
            Dashboard
          </p>
          <h1 className="text-xl font-bold text-gray-900">Commission income</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            What the statements you have loaded have actually earned. Forecast income
            from unreached slabs lives on{" "}
            <a href="/dashboard/accrual" className="text-brand-600 hover:underline">
              PLB Accrual
            </a>
            , and the two are never added together.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {filters.data?.can_view_agency && (
            <Toggle
              value={scope}
              onChange={(v) => setScope(v as IncomeScope)}
              options={[
                { value: "mine", label: "My uploads" },
                { value: "agency", label: "Whole agency" },
              ]}
            />
          )}
          <Toggle
            value={basis}
            onChange={(v) => setBasis(v as IncomeBasis)}
            options={[
              { value: "issue", label: "Sales basis" },
              { value: "travel", label: "Travel basis" },
            ]}
          />
        </div>
      </header>

      {/* A wrong income board is worse than no income board, so staleness blocks
          rather than whispers. */}
      {fr && !fr.ok && (
        <div className="rounded-xl ring-1 ring-amber-300 bg-amber-50 p-4 flex items-start gap-3">
          <TriangleAlert className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" aria-hidden />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-amber-900">
              This board is behind the statements that have been priced.
            </p>
            <p className="text-xs text-amber-800 mt-0.5">
              {fr.never_total > 0 && `${fr.never_total} priced batch(es) have never been projected. `}
              {fr.stale_total > 0 && `${fr.stale_total} batch(es) were re-priced after their last projection. `}
              Figures below exclude them.
            </p>
          </div>
          <button
            onClick={() => rebuild.mutate()}
            disabled={rebuild.isPending}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5
                       text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-60"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${rebuild.isPending ? "animate-spin" : ""}`} aria-hidden />
            {rebuild.isPending ? "Rebuilding…" : "Rebuild now"}
          </button>
        </div>
      )}

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiTile
          hero
          loading={busy}
          label="Vendor income earned"
          value={inrCompact(t?.vendor_income ?? null)}
          sub={
            t && t.needs_data_rows > 0 ? (
              <span className="text-amber-700">
                {t.needs_data_rows.toLocaleString("en-IN")} row(s) could not be confirmed
                — not counted as zero
              </span>
            ) : (
              <span className="text-gray-500">
                {(t?.rows ?? 0).toLocaleString("en-IN")} priced lines
              </span>
            )
          }
        />
        <KpiTile
          loading={busy}
          label="IATA commission"
          value={inrCompact(t?.iata_commission ?? null)}
          sub={<span className="text-gray-500">Separate entitlement — not added above</span>}
        />
        <KpiTile
          loading={busy}
          label="Gross revenue"
          value={inrCompact(t?.gross_revenue ?? null)}
          sub={<span className="text-gray-500">Sales and refunds only, excludes memos</span>}
        />
        <KpiTile
          loading={busy}
          tone={t && (t.debit_memo_amount ?? 0) > 0 ? "warning" : "default"}
          label="ADM exposure"
          value={inrCompact(t?.debit_memo_amount ?? null)}
          sub={
            <span className="text-gray-500">
              ACM back: {inrCompact(t?.credit_memo_amount ?? null)}
            </span>
          }
        />
        <KpiTile
          loading={busy}
          tone={t && t.unmatched_rows > 0 ? "warning" : "default"}
          label="Unmatched lines"
          value={(t?.unmatched_rows ?? 0).toLocaleString("en-IN")}
          sub={<span className="text-gray-500">No deal matched — income not claimed</span>}
        />
        <KpiTile
          loading={busy}
          label="Unattributed carrier"
          value={(t?.unattributed_airline_rows ?? 0).toLocaleString("en-IN")}
          sub={<span className="text-gray-500">Unknown income, not zero income</span>}
        />
        <KpiTile
          loading={busy}
          label="Unattributed consolidator"
          value={(t?.unattributed_supplier_rows ?? 0).toLocaleString("en-IN")}
          sub={<span className="text-gray-500">Third-party batches with no supplier link</span>}
        />
        <KpiTile
          loading={busy}
          label="Slab-dependent lines"
          value={(t?.slab_dependent_rows ?? 0).toLocaleString("en-IN")}
          sub={<span className="text-gray-500">May restate as volume accrues</span>}
        />
      </section>

      <section className="rounded-xl bg-white border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900">
          Income by month{" "}
          <span className="font-normal text-gray-500">
            ({basis === "travel" ? "travel date" : "issue date"})
          </span>
        </h2>
        <div className="mt-4 flex items-end gap-2 h-36">
          {(d?.by_month ?? []).map((m) => {
            const v = m.incentive ?? 0;
            const h = Math.round((Math.abs(v) / maxMonth) * 100);
            return (
              <div key={m.ym} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                <span className="text-[10px] text-gray-500 tabular-nums">
                  {v ? inrCompact(v) : "—"}
                </span>
                <div
                  className={`w-full rounded-t ${v < 0 ? "bg-red-400" : "bg-emerald-500"}`}
                  style={{ height: `${Math.max(h, 2)}%` }}
                  title={`${m.label}: ${rupees(m.incentive, 2)} over ${m.rows} lines`}
                />
                <span className="text-[10px] text-gray-500 truncate w-full text-center">
                  {m.label}
                  {m.has_slab_dependent && <span title="Contains slab-dependent lines">*</span>}
                </span>
              </div>
            );
          })}
          {!busy && !(d?.by_month ?? []).length && <Empty />}
        </div>
      </section>

      <div className="grid lg:grid-cols-2 gap-4">
        <RankPanel
          icon={<Plane className="w-4 h-4 text-brand-600" aria-hidden />}
          title="By airline"
          note="BSP and LCC income. Grouped on the resolved carrier id, never the printed name."
          rows={d?.by_airline ?? []}
          busy={busy}
          render={(a: AirlinePoint) => ({
            key: String(a.airline_id ?? "none"),
            name: a.airline,
            meta: `${a.rows.toLocaleString("en-IN")} lines`,
            value: a.incentive,
            share: a.share_pct,
            warn: a.airline_id === null,
          })}
        />
        <RankPanel
          icon={<Building2 className="w-4 h-4 text-accent-500" aria-hidden />}
          title="By consolidator (B2B supplier)"
          note="Third-party statements. One row is one branch — branches bill separately."
          rows={d?.by_supplier ?? []}
          busy={busy}
          render={(s: SupplierPoint) => ({
            key: String(s.supplier_id ?? "none"),
            name: s.supplier,
            meta: [s.supplier_code, s.branch, s.match_quality === "name" ? "name match" : null]
              .filter(Boolean)
              .join(" · ") || `${s.rows} lines`,
            value: s.incentive,
            share: s.share_pct,
            warn: s.supplier_id === null || s.match_quality === "name",
          })}
        />
      </div>

      <section className="rounded-xl bg-white border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">By source</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {(d?.by_source ?? []).map((s) => (
            <div key={s.source} className="rounded-lg ring-1 ring-gray-200 p-3">
              <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                {s.label}
              </p>
              <p className="text-lg font-bold text-gray-900 mt-1">
                {s.incentive == null ? "—" : inrCompact(s.incentive)}
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                {s.rows.toLocaleString("en-IN")} lines
                {s.needs_data_rows > 0 && ` · ${s.needs_data_rows} unconfirmed`}
              </p>
            </div>
          ))}
          {!busy && !(d?.by_source ?? []).length && <Empty />}
        </div>
      </section>
    </div>
  );
}

function Toggle({
  value, onChange, options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="inline-flex rounded-lg ring-1 ring-gray-200 bg-white p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
            value === o.value ? "bg-brand-600 text-white" : "text-gray-600 hover:bg-gray-50"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function RankPanel<T>({
  icon, title, note, rows, busy, render,
}: {
  icon: React.ReactNode;
  title: string;
  note: string;
  rows: T[];
  busy: boolean;
  render: (r: T) => {
    key: string; name: string; meta: string;
    value: number | null; share: number; warn?: boolean;
  };
}) {
  return (
    <section className="rounded-xl bg-white border border-gray-200 p-5">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      </div>
      <p className="text-[11px] text-gray-500 mt-0.5">{note}</p>
      <ul className="mt-3 space-y-2">
        {rows.map((r) => {
          const x = render(r);
          return (
            <li key={x.key} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  {x.warn && (
                    <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" aria-hidden />
                  )}
                  <p className="text-sm text-gray-900 truncate">{x.name}</p>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-brand-500"
                    style={{ width: `${Math.max(x.share, 1)}%` }}
                  />
                </div>
                <p className="text-[11px] text-gray-500 mt-0.5 truncate">{x.meta}</p>
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm font-semibold text-gray-900 tabular-nums">
                  {x.value == null ? "—" : inrCompact(x.value)}
                </p>
                <p className="text-[11px] text-gray-500 tabular-nums">{pct(x.share, 1)}</p>
              </div>
            </li>
          );
        })}
        {!busy && !rows.length && <Empty />}
      </ul>
    </section>
  );
}

function Empty() {
  return (
    <p className="text-xs text-gray-400 py-6 text-center w-full">
      Nothing projected yet. Run commission on a statement, or use Rebuild above.
    </p>
  );
}
