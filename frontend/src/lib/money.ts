/**
 * Indian money formatting.
 *
 * The product prices, settles and accrues in rupees, and the reports it replaces
 * use Indian digit grouping — 85900397 reads as 8,59,00,397, not 85,900,397.
 * `Intl.NumberFormat("en-IN")` does the lakh/crore grouping natively.
 *
 * `formatCurrency` in lib/utils.ts is the general helper and now defaults to INR;
 * this module adds the shapes a dashboard needs — compact tiles, signed deltas,
 * percentages — so pages stop hand-rolling a `fmt` each time.
 */

const GROUPED = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const GROUPED_2 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const CRORE = 1e7;
const LAKH = 1e5;

/** `8,59,00,397` — plain grouped digits, no symbol. For table cells. */
export function inr(value: number | null | undefined, decimals = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return (decimals ? GROUPED_2 : GROUPED).format(value);
}

/** `₹8,59,00,397` — grouped digits with the symbol. For totals and labels. */
export function rupees(value: number | null | undefined, decimals = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `₹${inr(value, decimals)}`;
}

/**
 * `₹8.59 Cr` / `₹12.4 L` / `₹8,400` — for KPI tiles and axis ticks, where the
 * magnitude matters and the last four digits do not. Crore and lakh rather than
 * M/K: this is what the audience reads without translating.
 */
export function inrCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const n = Math.abs(value);
  if (n >= CRORE) return `${sign}₹${(n / CRORE).toFixed(2)} Cr`;
  if (n >= LAKH) return `${sign}₹${(n / LAKH).toFixed(1)} L`;
  if (n >= 1000) return `${sign}₹${GROUPED.format(Math.round(n))}`;
  return `${sign}₹${n.toFixed(0)}`;
}

/** `+₹4.2 L` / `−₹1.1 Cr` — a change, where the direction is the point. */
export function inrDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value === 0) return "no change";
  return `${value > 0 ? "+" : "−"}${inrCompact(Math.abs(value))}`;
}

/**
 * `81.18%`. Values arrive as percentages already (81.18), never as fractions —
 * matching the API, where deflator_pct and plb_rate_pct are both out of 100.
 */
export function pct(value: number | null | undefined, decimals = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** A dash for a zero the sheet would leave blank, so "nothing accrued" reads as
 *  nothing rather than as a computed zero. */
export function dashIfZero(
  value: number | null | undefined,
  format: (v: number) => string = inr,
): string {
  if (value == null || Number.isNaN(value) || Math.abs(value) < 0.5) return "—";
  return format(value);
}

/** `2026-04` → `Apr 26`, the column header the source workbook uses. */
export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  return `${d.toLocaleString("en-GB", { month: "short" })} ${y.slice(2)}`;
}
