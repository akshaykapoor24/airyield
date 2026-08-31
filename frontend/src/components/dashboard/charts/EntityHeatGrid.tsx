"use client";

import { HEAT_RAMP, type OverviewResponse } from "@/lib/accrual";
import { dashIfZero, inrCompact, rupees } from "@/lib/money";

/**
 * Accrual by entity × airline.
 *
 * A matrix, so magnitude gets a sequential ramp: one hue, light to dark, with a
 * scale legend. It is not colour-only — every cell prints its own value, so the
 * table IS the accessible view of itself and the shading is a reading aid on top.
 * Five bins, not a continuous gradient: past about seven, adjacent classes blur.
 */

const BINS = HEAT_RAMP.length;

export default function EntityHeatGrid({
  rows,
  airlines,
}: {
  rows: OverviewResponse["by_entity"];
  airlines: string[];
}) {
  if (!rows.length || !airlines.length) return null;

  const max = Math.max(
    ...rows.flatMap((r) => airlines.map((a) => Math.abs(r.by_airline[a] ?? 0))),
    1,
  );
  const bin = (v: number) => {
    const n = Math.abs(v);
    if (n < max * 0.01) return -1;              // effectively nothing — no fill
    return Math.min(BINS - 1, Math.floor((n / max) * BINS));
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start justify-between gap-4 mb-1">
        <h2 className="text-sm font-semibold text-gray-900">Accrual by entity and airline</h2>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[10px] text-gray-400">Low</span>
          {HEAT_RAMP.map((c, i) => (
            <span
              key={c}
              className="w-4 h-3 rounded-[2px]"
              style={{ background: c }}
              title={`${inrCompact((max * i) / BINS)} – ${inrCompact((max * (i + 1)) / BINS)}`}
              aria-hidden
            />
          ))}
          <span className="text-[10px] text-gray-400">{inrCompact(max)}</span>
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Where each entity&apos;s supplier income comes from.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-xs">
          <thead>
            <tr>
              <th className="text-left font-semibold text-gray-500 uppercase tracking-wide text-[10px] pb-2 pr-3">
                Entity
              </th>
              {airlines.map((a) => (
                <th
                  key={a}
                  className="px-1.5 pb-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wide text-right"
                >
                  <span className="block max-w-[5.5rem] truncate" title={a}>{a}</span>
                </th>
              ))}
              <th className="pl-3 pb-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wide text-right">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.entity}>
                <td className="font-semibold text-gray-800 pr-3 py-0.5 whitespace-nowrap">
                  {r.entity}
                </td>
                {airlines.map((a) => {
                  const v = r.by_airline[a] ?? 0;
                  const b = bin(v);
                  return (
                    <td key={a} className="px-0.5 py-0.5">
                      {/* 2px gap between adjacent fills comes from the cell padding,
                          not a border drawn around each tile. */}
                      <div
                        className="rounded-[3px] px-2 py-1.5 text-right tabular-nums"
                        style={{
                          background: b < 0 ? "transparent" : HEAT_RAMP[b],
                          // Ink stays a text token; the fill carries the magnitude.
                          color: b >= BINS - 1 ? "#fff" : "#334155",
                        }}
                        title={`${r.entity} · ${a} — ${rupees(v)}`}
                      >
                        {dashIfZero(v, inrCompact)}
                      </div>
                    </td>
                  );
                })}
                <td
                  className="pl-3 py-0.5 text-right font-semibold text-gray-900 tabular-nums whitespace-nowrap"
                  title={rupees(r.accrual)}
                >
                  {inrCompact(r.accrual)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
