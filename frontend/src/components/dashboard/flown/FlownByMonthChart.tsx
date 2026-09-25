"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AXIS_TICK, GRID_STROKE, SERIES } from "@/lib/accrual";
import { inrCompact, rupees } from "@/lib/money";
import { CARD, CARD_NOTE, CARD_TITLE } from "@/lib/revenueCharts";
import type { FlownMonthPoint } from "@/lib/salesFlown";

/**
 * What flew in each travel month, whatever month it was sold in.
 *
 * One measure, two states: flown (up to "as of") and booked (after it). They are one
 * hue two steps apart — the accrual board's confirmed/provisional pair — because the
 * pair is ordered, not two identities. A legend names both; the tooltip says which.
 */
export default function FlownByMonthChart({ data }: { data: FlownMonthPoint[] }) {
  const anyFuture = data.some((d) => d.future);
  return (
    <section className={CARD}>
      <div className="flex items-baseline justify-between mb-1">
        <h2 className={CARD_TITLE}>Flown by travel month</h2>
        <div className="flex items-center gap-2.5 text-[11px] text-gray-500">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES.confirmed }} aria-hidden />
            Flown
          </span>
          {anyFuture && (
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES.provisional }} aria-hidden />
              Booked, not yet flown
            </span>
          )}
        </div>
      </div>
      <p className={`${CARD_NOTE} mb-4`}>
        Gross by the month it travels, for travel dates inside the window. This is what a
        flown-based incentive is measured on.
      </p>
      {data.length ? (
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={62}
                   tickFormatter={(v) => inrCompact(Number(v))} />
            <Tooltip
              cursor={{ fill: "#f8fafc" }}
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as FlownMonthPoint | undefined;
                if (!active || !p) return null;
                return (
                  <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                    <p className="font-semibold text-gray-900">{p.label}</p>
                    <p className="text-gray-600">
                      {p.future ? "Booked" : "Flown"}:{" "}
                      <span className="font-semibold text-gray-900">{rupees(p.flown)}</span>
                    </p>
                    <p className="text-gray-400">{p.rows.toLocaleString("en-IN")} lines</p>
                  </div>
                );
              }}
            />
            <Bar dataKey="flown" maxBarSize={26} radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.ym} fill={d.future ? SERIES.provisional : SERIES.confirmed} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p className="text-sm text-gray-500 py-16 text-center">
          No line in this window carries a travel date.
        </p>
      )}
    </section>
  );
}
