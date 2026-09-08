"use client";

/**
 * The three GST cells of a billing row: CGST, SGST, IGST.
 *
 * Used by Customer Billing, Corporate Billing and Agency Billing, which are
 * three near-identical copies of the same table — one component so the tax
 * columns cannot drift apart between them.
 *
 * WHY A ZERO IS NOT PRINTED AS ₹0
 * ───────────────────────────────
 * A supply carries CGST + SGST or IGST, never both, so on every correct row two
 * of these three are zero. Printing "₹0.00" in them reads as "no tax was
 * charged" when it means "the other head carried it" — an em dash says
 * "not applicable here" and is the honest mark.
 *
 * WHEN THE PLACE OF SUPPLY IS UNKNOWN the three collapse into one spanning cell
 * showing the total, labelled. The tax IS charged and IS in the row total; what
 * is missing is only the attribution, and hiding the amount would be worse than
 * saying so.
 */

import { isSplit, type GstSplit } from "@/lib/gstSplit";

const money = (n: number): string =>
  `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/** An amount, or an em dash when this head does not apply to this supply. */
function Head({ value, applies, title }: { value: number; applies: boolean; title: string }) {
  return (
    <td
      className={`px-3 py-2 text-[11px] whitespace-nowrap ${applies ? "text-amber-600" : "text-gray-300"}`}
      title={applies ? title : "Not charged on this supply"}
    >
      {applies ? money(value) : "—"}
    </td>
  );
}

export default function GstCells({ split }: { split: GstSplit }) {
  if (!isSplit(split.treatment)) {
    return (
      <td
        colSpan={3}
        className="px-3 py-2 text-[11px] text-amber-600 whitespace-nowrap"
        title="The place of supply for this party is unknown, so this GST cannot be attributed to CGST/SGST or IGST. It is still charged and included in the row total."
      >
        {money(split.gst)}
        <span className="ml-1.5 text-[9px] font-semibold text-gray-400 uppercase tracking-wide">
          not split
        </span>
      </td>
    );
  }

  const intra = split.treatment === "cgst_sgst";
  return (
    <>
      <Head value={split.cgst} applies={intra} title="Central GST — 9% of the taxable value" />
      <Head value={split.sgst} applies={intra} title="State GST — 9% of the taxable value" />
      <Head value={split.igst} applies={!intra} title="Integrated GST — 18% on an inter-state supply" />
    </>
  );
}

/** The same three cells for a totals row, in the bolder style those use. */
export function GstTotalCells({
  cgst, sgst, igst, gst, treatment,
}: { cgst: number; sgst: number; igst: number; gst: number; treatment: GstSplit["treatment"] }) {
  if (!isSplit(treatment)) {
    return (
      <td colSpan={3} className="px-3 py-2 text-[11px] text-amber-700 whitespace-nowrap">
        {money(gst)}
        <span className="ml-1.5 text-[9px] font-semibold text-gray-400 uppercase">not split</span>
      </td>
    );
  }
  const intra = treatment === "cgst_sgst";
  return (
    <>
      <td className={`px-3 py-2 text-[11px] whitespace-nowrap ${intra ? "text-amber-700" : "text-gray-300"}`}>
        {intra ? money(cgst) : "—"}
      </td>
      <td className={`px-3 py-2 text-[11px] whitespace-nowrap ${intra ? "text-amber-700" : "text-gray-300"}`}>
        {intra ? money(sgst) : "—"}
      </td>
      <td className={`px-3 py-2 text-[11px] whitespace-nowrap ${intra ? "text-gray-300" : "text-amber-700"}`}>
        {intra ? "—" : money(igst)}
      </td>
    </>
  );
}
