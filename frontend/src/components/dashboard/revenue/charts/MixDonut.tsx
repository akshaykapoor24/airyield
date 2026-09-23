"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { inrCompact, rupees } from "@/lib/money";
import { CARD, CARD_NOTE, CARD_TITLE, MARK_GAP, OTHER_COLOR } from "@/lib/revenueCharts";

export interface Slice {
  key: string;
  label: string;
  value: number;
  color: string;
}

/**
 * A donut for a MIX — "what is this total made of" — and nothing else.
 *
 * A donut answers composition and answers nothing else well: it cannot compare two
 * slices of similar size, it cannot show change, and it cannot rank. Where the question
 * is "which is bigger", the stacked column and the airline matrix beside it are the
 * chart. That is why every slice is DIRECT-LABELLED with its share and its value
 * written out: the angle is the picture, the label is the reading, and three of the six
 * palette hues sit below 3:1 contrast on white, so the label is also the relief the
 * palette's contrast warning obligates.
 *
 * `fold` caps the slice count. A seventh identity is never a generated hue — it folds
 * into a neutral "Other", which is both the palette rule and the honest rendering: a
 * slice too small to see is a slice nobody can read.
 */
export default function MixDonut({
  title,
  note,
  slices,
  fold = 0,
  empty = "Nothing to show for this filter.",
  loading,
}: {
  title: string;
  note: string;
  slices: Slice[];
  /** 0 = show them all. Otherwise keep the top N and fold the rest into "Other". */
  fold?: number;
  empty?: string;
  loading?: boolean;
}) {
  // Magnitudes: a donut cannot draw a negative slice, and a refund-heavy month would
  // otherwise render an arc pointing the wrong way with no sign anywhere on screen.
  // Signed values stay on the column chart, where a bar can go below the axis.
  const ordered = [...slices]
    .map((s) => ({ ...s, value: Math.abs(s.value) }))
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value);

  const cap = fold || ordered.length;
  const shown = ordered.slice(0, cap);
  const rest = ordered.slice(cap);
  const data = rest.length
    ? [...shown, {
        key: "__other",
        label: `Other (${rest.length})`,
        value: rest.reduce((a, s) => a + s.value, 0),
        color: OTHER_COLOR,
      }]
    : shown;

  const total = data.reduce((a, s) => a + s.value, 0);

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>{title}</h2>
      <p className={`${CARD_NOTE} mb-3`}>{note}</p>

      {!data.length ? (
        <p className="text-xs text-gray-400 py-10 text-center">
          {loading ? " " : empty}
        </p>
      ) : (
        <div className="flex items-center gap-4">
          <ResponsiveContainer width="55%" height={190}>
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius={48}
                outerRadius={82}
                // Animation off everywhere on this dashboard: slices grow from zero on
                // every refetch, which turns a filter change into a flicker.
                isAnimationActive={false}
                {...MARK_GAP}
              >
                {data.map((s) => (
                  <Cell key={s.key} fill={s.color} />
                ))}
              </Pie>
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload as Slice;
                  return (
                    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                      <p className="font-semibold text-gray-900">{p.label}</p>
                      <p className="text-gray-600 tabular-nums">
                        {rupees(p.value)} · {((p.value / total) * 100).toFixed(1)}%
                      </p>
                    </div>
                  );
                }}
              />
            </PieChart>
          </ResponsiveContainer>

          {/* The legend is not optional: with two or more series, identity is never
              carried by colour alone. It doubles as the direct-label layer. */}
          <ul className="flex-1 min-w-0 space-y-1.5">
            {data.map((s) => (
              <li key={s.key} className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-sm shrink-0"
                  style={{ background: s.color }}
                  aria-hidden
                />
                <span className="text-xs text-gray-700 flex-1 min-w-0 truncate">
                  {s.label}
                </span>
                <span className="text-[11px] text-gray-500 tabular-nums shrink-0">
                  {((s.value / total) * 100).toFixed(0)}%
                </span>
                <span className="text-xs font-semibold text-gray-900 tabular-nums shrink-0 w-16 text-right">
                  {inrCompact(s.value)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
