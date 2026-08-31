"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS_TICK, GRID_STROKE, SERIES, type OverviewResponse } from "@/lib/accrual";
import { inrCompact, pct, rupees } from "@/lib/money";

/**
 * Which airlines carry the accrual, and how few of them it takes.
 *
 * A textbook Pareto puts a cumulative-% line on a second y-axis. That is a
 * dual-axis chart: the two scales are aligned arbitrarily and the crossing point
 * reads as meaningful when it is not. The cumulative figure is genuinely useful
 * here, so it stays — as a printed column beside each bar, on no axis at all.
 *
 * Every bar is the same colour. Shading them darker-where-bigger would encode bar
 * length twice and spend the only free channel on information the length already
 * carries.
 */
export default function AirlineContribution({
  rows,
}: {
  rows: OverviewResponse["by_airline"];
}) {
  // Rows can come back with a zero accrual across the board — an airline may have
  // flown revenue and earn nothing on it. Plotting a row of empty bars and
  // claiming "N airlines account for 80%" of nothing would be worse than saying
  // there is nothing to show.
  const total = rows.reduce((s, r) => s + r.accrual, 0);
  if (!rows.length || total === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900">Accrual by airline</h2>
        <div className="h-65 flex flex-col items-center justify-center text-center px-6">
          <p className="text-sm text-gray-400">Nothing accrued in this period.</p>
          {!!rows.length && (
            <p className="text-xs text-gray-400 mt-1">
              {rows.length} carriers flew, but none of them earned a PLB — check the
              exceptions beside this.
            </p>
          )}
        </div>
      </div>
    );
  }

  // How many airlines make up 80% of the accrual — the sentence a commercial head
  // actually wants out of a Pareto.
  const eighty = rows.findIndex((r) => r.cumulative_pct >= 80);
  const concentration = eighty >= 0 ? eighty + 1 : rows.length;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-900">Accrual by airline</h2>
      <p className="text-xs text-gray-500 mb-4">
        Top {rows.length} carriers.{" "}
        <span className="font-medium text-gray-700">
          {concentration} {concentration === 1 ? "airline" : "airlines"}
        </span>{" "}
        account for 80% of it.
      </p>

      <div className="flex gap-3">
        <div className="flex-1 min-w-0">
          <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 30)}>
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ top: 0, right: 12, left: 0, bottom: 4 }}
              barCategoryGap="26%"
            >
              <CartesianGrid stroke={GRID_STROKE} horizontal={false} />
              <XAxis
                type="number"
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={{ stroke: GRID_STROKE }}
                tickFormatter={(v) => inrCompact(Number(v))}
              />
              <YAxis
                type="category"
                dataKey="airline"
                width={150}
                tick={{ ...AXIS_TICK, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                cursor={{ fill: "#f8fafc" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload as OverviewResponse["by_airline"][number];
                  return (
                    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                      <p className="font-semibold text-gray-900 mb-1">{d.airline}</p>
                      <p className="text-gray-600">
                        Accrued <span className="font-semibold text-gray-900">{rupees(d.accrual)}</span>
                      </p>
                      <p className="text-gray-600">
                        Flown <span className="font-semibold text-gray-900">{rupees(d.flown)}</span>
                      </p>
                      <p className="text-gray-400 mt-1">
                        {pct(d.share_pct, 1)} of the total · {pct(d.cumulative_pct, 1)} cumulative
                      </p>
                    </div>
                  );
                }}
              />
              <Bar
                dataKey="accrual" fill={SERIES.accrual} maxBarSize={20}
                radius={[0, 4, 4, 0]} isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* The cumulative column — the Pareto's second variable, printed rather
            than plotted on an invented second axis. */}
        <div
          className="w-16 shrink-0 flex flex-col justify-around pb-1"
          style={{ minHeight: Math.max(200, rows.length * 30) }}
        >
          <p className="text-[9px] uppercase tracking-wide text-gray-400 font-semibold text-right">
            Cum.
          </p>
          {rows.map((r) => (
            <p key={r.airline} className="text-[10px] text-gray-500 tabular-nums text-right">
              {pct(r.cumulative_pct, 0)}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
