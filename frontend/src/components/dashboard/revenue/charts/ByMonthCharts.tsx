"use client";

import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { inrCompact, rupees } from "@/lib/money";
import {
  AXIS_TICK, CARD, CARD_NOTE, CARD_TITLE, GRID_STROKE, MARK_GAP, SOURCE_COLOR,
} from "@/lib/revenueCharts";
import { SALE_SOURCES, SOURCE_SHORT, type MonthPoint } from "@/lib/revenueBoard";

/**
 * TWO charts sharing an x-axis, deliberately NOT one chart with two y-scales.
 *
 * Sale runs in crores and the incentive it earns runs in lakhs — two orders of
 * magnitude apart. Plotted against a shared axis the incentive would be a flat line on
 * the floor; given its own second axis, the alignment of the two scales would be
 * arbitrary and the chart would invent a relationship the data does not contain. Small
 * multiples keep one scale per plot and let the reader do the comparison honestly,
 * month by month. (The same rule, and the same reason, as MonthlyCharts.tsx.)
 */

function MonthTooltip({
  active, payload, label, note,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string;
  note?: string;
}) {
  if (!active || !payload?.length) return null;
  const shown = payload.filter((p) => p.value);
  const total = shown.reduce((a, p) => a + (p.value ?? 0), 0);
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
      <p className="font-semibold text-gray-900 mb-1">{label}</p>
      {shown.map((p) => (
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
      {shown.length > 1 && (
        <p className="flex items-center gap-2 text-gray-900 border-t border-gray-100 mt-1 pt-1">
          <span className="flex-1 font-semibold">Total</span>
          <span className="font-semibold tabular-nums">{rupees(total)}</span>
        </p>
      )}
      {note && <p className="text-[10px] text-gray-400 mt-1.5 max-w-[15rem]">{note}</p>}
    </div>
  );
}

export function SaleByMonthChart({ data }: { data: MonthPoint[] }) {
  // One key per source, flattened off `by_source` so a stacked segment can address it.
  // Every source gets a key even where the month is zero — a missing key makes recharts
  // drop the segment, and an absent segment reads as a gap rather than as nothing sold.
  const rows = data.map((m) => ({
    label: m.label,
    ...Object.fromEntries(SALE_SOURCES.map((s) => [s, m.by_source[s] ?? 0])),
  }));
  const present = SALE_SOURCES.filter((s) => data.some((m) => m.by_source[s]));

  return (
    <section className={CARD}>
      <div className="flex items-baseline justify-between mb-1">
        <h2 className={CARD_TITLE}>Sale by month</h2>
        {present.length > 1 && (
          <div className="flex flex-wrap items-center gap-2.5 text-[11px] text-gray-500">
            {present.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-sm"
                  style={{ background: SOURCE_COLOR[s] }}
                  aria-hidden
                />
                {SOURCE_SHORT[s]}
              </span>
            ))}
          </div>
        )}
      </div>
      <p className={`${CARD_NOTE} mb-4`}>
        Gross as the statement prints it, stacked by type. A refund subtracts.
      </p>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                  barCategoryGap="28%">
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false}
                 axisLine={{ stroke: GRID_STROKE }} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={62}
                 tickFormatter={(v) => inrCompact(Number(v))} />
          <Tooltip cursor={{ fill: "#f8fafc" }} content={<MonthTooltip />} />
          {present.map((s, i) => (
            <Bar
              key={s}
              dataKey={s}
              name={SOURCE_SHORT[s]}
              stackId="sale"
              fill={SOURCE_COLOR[s]}
              maxBarSize={26}
              isAnimationActive={false}
              // 2px of surface between segments, and a rounded cap on the top one only
              // — the data-end, anchored to the baseline.
              {...(present.length > 1 ? MARK_GAP : {})}
              radius={i === present.length - 1 ? [4, 4, 0, 0] : undefined}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

export function IncentiveByMonthChart({ data }: { data: MonthPoint[] }) {
  const rows = data.map((m) => ({ label: m.label, incentive: m.incentive ?? 0 }));
  const peak = rows.reduce(
    (best, d) => (Math.abs(d.incentive) > Math.abs(best?.incentive ?? 0) ? d : best),
    rows[0],
  );
  const anyUnpriced = data.some((m) => m.incentive == null && m.sale);

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>Commission earned by month</h2>
      <p className={`${CARD_NOTE} mb-4`}>
        What the priced lines earned. Its own scale — an incentive runs two orders of
        magnitude below the sale it sits on.
      </p>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={rows} margin={{ top: 20, right: 8, left: 0, bottom: 0 }}
                  barCategoryGap="28%">
          <CartesianGrid stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false}
                 axisLine={{ stroke: GRID_STROKE }} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={62}
                 tickFormatter={(v) => inrCompact(Number(v))} />
          <Tooltip cursor={{ fill: "#f8fafc" }} content={<MonthTooltip />} />
          {/* One series, so no legend box: the title already names what is plotted. */}
          <Bar dataKey="incentive" name="Commission earned" fill={SOURCE_COLOR.bsp}
               maxBarSize={26} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      {peak && (
        <p className="text-[11px] text-gray-500 mt-1">
          Highest month: <span className="font-semibold text-gray-800">{peak.label}</span>{" "}
          at {rupees(peak.incentive)}.
          {anyUnpriced && " Months with unpriced statements read low until they are run."}
        </p>
      )}
    </section>
  );
}
