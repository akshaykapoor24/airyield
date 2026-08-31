"use client";

import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AXIS_TICK, GRID_STROKE, SERIES } from "@/lib/accrual";
import { inrCompact, rupees } from "@/lib/money";

/**
 * TWO charts sharing an x-axis, deliberately NOT one chart with two y-scales.
 *
 * Flown revenue runs in crores and the accrual it produces runs in lakhs — two
 * orders of magnitude apart. Plotted against a shared axis the accrual would be a
 * flat line on the floor; given its own second axis the alignment of the two
 * scales would be arbitrary, and the chart would invent a relationship the data
 * does not contain. Small multiples keep one scale per plot and let the reader do
 * the comparison honestly, month by month.
 */

const CARD = "bg-white rounded-xl border border-gray-200 p-5";
const TITLE = "text-sm font-semibold text-gray-900";

interface Point {
  ym: string;
  label: string;
  flown: number;
  accrual: number;
  confirmed: number;
  provisional: number;
}

function ChartTooltip({
  active, payload, label, note,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string;
  note?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
      <p className="font-semibold text-gray-900 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-gray-600">
          <span
            className="w-2.5 h-2.5 rounded-sm shrink-0"
            style={{ background: p.color }}
            aria-hidden
          />
          <span className="flex-1">{p.name}</span>
          <span className="font-semibold text-gray-900 tabular-nums">
            {rupees(p.value ?? 0)}
          </span>
        </p>
      ))}
      {note && <p className="text-[10px] text-gray-400 mt-1.5 max-w-[15rem]">{note}</p>}
    </div>
  );
}

export function FlownByMonthChart({ data }: { data: Point[] }) {
  const anyProvisional = data.some((d) => d.provisional !== 0);
  return (
    <div className={CARD}>
      <div className="flex items-baseline justify-between mb-1">
        <h2 className={TITLE}>Flown revenue by month</h2>
        {anyProvisional && (
          <div className="flex items-center gap-3 text-[11px] text-gray-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES.confirmed }} aria-hidden />
              Confirmed
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES.provisional }} aria-hidden />
              Provisional
            </span>
          </div>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Gross revenue the accrual is taken on. Provisional means the airline has not
        confirmed the month yet.
      </p>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={62}
            tickFormatter={(v) => inrCompact(Number(v))}
          />
          <Tooltip
            cursor={{ fill: "#f8fafc" }}
            content={<ChartTooltip />}
          />
          {/* 2px surface gap between the two stacked segments — white doing the
              separating, rather than a stroke drawn around each mark. */}
          {/* Animation off everywhere on this dashboard: bars grow from zero on
              every refetch, which turns a filter change into a flicker, and a
              chart captured mid-animation reports the wrong height. */}
          <Bar
            dataKey="confirmed" name="Confirmed" stackId="f"
            fill={SERIES.confirmed} maxBarSize={26} isAnimationActive={false}
            stroke="#fff" strokeWidth={anyProvisional ? 2 : 0}
          />
          <Bar
            dataKey="provisional" name="Provisional" stackId="f"
            fill={SERIES.provisional} maxBarSize={26} radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AccrualByMonthChart({ data }: { data: Point[] }) {
  // One series, so no legend box: the title already says what is plotted. The
  // largest month is direct-labelled; the axis carries the rest.
  const peak = data.reduce(
    (best, d) => (Math.abs(d.accrual) > Math.abs(best?.accrual ?? 0) ? d : best),
    data[0],
  );
  return (
    <div className={CARD}>
      <h2 className={TITLE}>PLB accrued by month</h2>
      <p className="text-xs text-gray-500 mb-4">
        Flown × deflator × PLB rate, for the months each deal covers.
      </p>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={data} margin={{ top: 20, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: GRID_STROKE }} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={62}
            tickFormatter={(v) => inrCompact(Number(v))}
          />
          <Tooltip cursor={{ fill: "#f8fafc" }} content={<ChartTooltip />} />
          <Bar
            dataKey="accrual" name="PLB accrued" fill={SERIES.accrual}
            maxBarSize={26} radius={[4, 4, 0, 0]} isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
      {peak && (
        <p className="text-[11px] text-gray-500 mt-1">
          Highest month: <span className="font-semibold text-gray-800">{peak.label}</span>{" "}
          at {rupees(peak.accrual)}.
        </p>
      )}
    </div>
  );
}
