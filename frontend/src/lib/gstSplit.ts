/**
 * Which GST a billing line carries — CGST + SGST, or IGST.
 *
 * A DELIBERATE MIRROR of backend/app/services/billing_calc.py (`gst_taxable`,
 * `split_gst`). The browser recomputes a row live as someone types an additional
 * markup or a discount, so the same arithmetic has to exist on both sides; the
 * server stays authoritative and recomputes everything on save.
 *
 * Before this, three pages each carried their own `const GST_RATE = 0.18` and
 * two copies of the same branch (`rowCalc` + `editRowCalc`) — six implementations
 * of one tax rule, which is six places to forget when a rate moves.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE
 * ────────────────────────────────────
 * CGST + SGST and IGST are mutually exclusive. A supply inside one state carries
 * CGST and SGST at half the rate each; one that crosses a state line carries IGST
 * at the whole rate. NEVER both, and never summed — the two branches come to the
 * same money, which is exactly why a wrong one is invisible on the total and
 * still files the tax in the wrong place.
 *
 * WHICH branch applies is not decided here. The server decides it from the two
 * parties' GSTINs (see backend/app/services/place_of_supply.py) and sends the
 * answer down as `gst_treatment`, so a row that the user edits keeps the same
 * treatment the rest of its bill was raised under.
 */

/** 'cgst_sgst' and 'igst' are decided; 'unsplit' means the place of supply is not known. */
export type GstTreatment = "cgst_sgst" | "igst" | "unsplit";

export const GST_RATE = 0.18;
/** CGST and SGST are each half. 9 + 9 = 18, which is why the split costs nothing. */
export const HALF_GST_RATE = GST_RATE / 2;

export type GstSplit = {
  cgst: number;
  sgst: number;
  igst: number;
  /** The total across the heads — what goes into the line total. */
  gst: number;
  treatment: GstTreatment;
};

/** Rounded to paise. Mirrors the server's 2-dp money rounding closely enough for a preview. */
const round2 = (n: number): number => Math.round(n * 100) / 100;

/**
 * What GST is charged ON, before any rate.
 *
 * - `reseller`: the whole sale — gross + markup − discount
 * - `agency`:   the margin only — markup − discount
 * - anything else (including an unset billing type): nothing is taxable
 *
 * Clamped at zero so a discount larger than the margin — or a refund, which
 * arrives as a negative base — cannot produce negative tax.
 */
export function gstTaxable(
  base: number,
  markup: number,
  billingType: string | null | undefined,
  discount = 0,
): number {
  if (billingType === "reseller") return Math.max(0, base + markup - discount);
  if (billingType === "agency") return Math.max(0, markup - discount);
  return 0;
}

/**
 * The tax on one line, in the heads it is actually charged under.
 *
 * `treatment` comes from the API. A missing one is treated as 'unsplit': the
 * total is still reported so the row shows what is owed, but no head is claimed.
 * Defaulting an unknown to CGST + SGST would put inter-state tax in a state's
 * column with nothing on screen to say so.
 */
export function splitGst(
  base: number,
  markup: number,
  billingType: string | null | undefined,
  discount: number,
  treatment: GstTreatment | null | undefined,
): GstSplit {
  const taxable = gstTaxable(base, markup, billingType, discount);

  if (treatment === "igst") {
    const igst = round2(taxable * GST_RATE);
    return { cgst: 0, sgst: 0, igst, gst: igst, treatment: "igst" };
  }
  if (treatment === "cgst_sgst") {
    // Each head from the taxable value at 9%, NOT half of a rounded 18% total —
    // halving an odd-paise total makes CGST and SGST differ, and an invoice
    // showing CGST 9.01 against SGST 9.00 is a broken invoice.
    const half = round2(taxable * HALF_GST_RATE);
    return { cgst: half, sgst: half, igst: 0, gst: round2(half * 2), treatment: "cgst_sgst" };
  }
  return { cgst: 0, sgst: 0, igst: 0, gst: round2(taxable * GST_RATE), treatment: "unsplit" };
}

/** What the server calls a decided treatment, for a row that has one. */
export const isSplit = (t: GstTreatment | null | undefined): boolean =>
  t === "cgst_sgst" || t === "igst";

/** The server's place-of-supply explanation, as returned beside a ticket list. */
export type PlaceOfSupply = {
  treatment: GstTreatment;
  decided: boolean;
  supplier_state: string | null;
  recipient_state: string | null;
  source: string;
  note: string;
};
