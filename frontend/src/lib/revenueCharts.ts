// Chart tokens for the Total Revenue board.
//
// SEPARATE FROM lib/accrual.ts, AND NOT A WIDENING OF IT. `SERIES` there is a two-step
// single-hue blue ramp — confirmed/provisional — which is exactly right for an ordered
// pair and carries no information at all across six unrelated statement types. Six
// identities need six hues, and the two files answer different questions; merging them
// would mean the accrual board's ordered pair and this board's categorical set share one
// definition and drift into each other.
//
// THE HUES ARE VALIDATED, NOT CHOSEN. Run against the six checks at
// `--mode light`, surface #fcfcfb:
//
//   Lightness band      PASS   all six inside L 0.43–0.77
//   Chroma floor        PASS   all six >= 0.1
//   CVD separation      PASS   worst adjacent pair ΔE 9.1 (protan), target >= 8
//   Normal-vision floor PASS   worst adjacent pair ΔE 19.6, floor >= 15
//   Contrast vs surface WARN   three hues below 3:1 — relief required
//
// The contrast WARN is not dismissable: it obligates visible labels or a table view.
// Both ship — every donut slice is direct-labelled with its share, and the airline
// matrix below the charts is the table. Do not remove either and leave the palette.
//
// ORDER IS THE CVD-SAFETY MECHANISM, not a preference. Assigning by fixed slot means a
// filter that removes NDC never repaints LCC: colour follows the entity, never its rank.
// A seventh statement type folds into "Other" rather than getting a generated hue.
//
// LIGHT ONLY, deliberately. This app ships no dark mode — no `prefers-color-scheme` in
// globals.css and no `dark:` utility anywhere in components/ — so a dark column here
// would be tokens nothing renders. The validated dark steps for these six hues are
// #3987e5 #d95926 #199e70 #c98500 #d55181 #008300, in the same order, if that changes.

/** One hue per statement type, in the order the Statements hub lists them. */
export const SOURCE_COLOR: Record<string, string> = {
  bsp: "#2a78d6",            // blue
  ndc: "#eb6834",            // orange
  "lcc-detailed": "#1baf7a", // aqua
  "tp-gds": "#eda100",       // yellow
  "tp-lcc": "#e87ba4",       // magenta
  "tp-api": "#008300",       // green
};

/** The family a source belongs to, for the grouped cards. Mirrors the backend's
 *  SOURCE_CATEGORY, which reads it off the report registry. */
export const SOURCE_CATEGORY: Record<string, string> = {
  bsp: "BSP",
  ndc: "BSP",
  "lcc-detailed": "LCC",
  "tp-gds": "Third Party",
  "tp-lcc": "Third Party",
  "tp-api": "Third Party",
};

export const CATEGORY_ORDER = ["BSP", "LCC", "Third Party"] as const;

/** Incentive types get the same slots, by rank within the current filter rather than by
 *  a fixed identity — there is no stable order to eleven incentive types and the chart
 *  shows one filter at a time. Past five they fold into a neutral "Other", which is the
 *  rule: a sixth slice is never a generated hue. */
export const INCENTIVE_COLORS = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
] as const;
export const OTHER_COLOR = "#94a3b8";
export const MAX_INCENTIVE_SLICES = 5;

/** Recessive grid and axis ink, shared with the accrual board so the two dashboards
 *  read as one system. Imported rather than re-declared. */
export { AXIS_TICK, GRID_STROKE } from "@/lib/accrual";

/** A 2px surface gap between adjacent fills — stacked segments and donut slices alike.
 *  White doing the separating, rather than a stroke drawn around each mark. */
export const MARK_GAP = { stroke: "#ffffff", strokeWidth: 2 };

// The card frame shared by every chart on the three revenue boards. Matches Panel in
// components/dashboard/ui/Board.tsx, so a chart card and a table panel sit side by side
// without one looking borrowed from another page.
export const CARD = "bg-white rounded-2xl ring-1 ring-line shadow-sm p-5";
export const CARD_TITLE = "font-display text-[15px] font-semibold text-gray-900";
export const CARD_NOTE = "text-xs leading-relaxed text-gray-500";
