// The GST schemes, shared by the Master Governance editor and My Profile.
//
// A SCHEME IS A CHOICE; WHICH OF ITS RULES APPLIES IS NOT. A business elects
// abatement or normal, and that governs every invoice it raises. Both schemes
// then span TWO rules, and in neither case does anyone pick between them:
//
//   Abatement → domestic or international, decided by where the TICKET flies
//   Normal    → agency or reseller, decided by the CUSTOMER's billing_type,
//               set when they are onboarded in User Master
//
// Mirrors SCHEME_MAP / SCHEME_LABELS in backend/app/models/gst_configuration.py.
// The backend rejects any other slug with a 422, so keep the two in step.

export type Basis = "basic_fare" | "service_charge" | "total_cost";
export type SubCategory = "domestic" | "international" | "agency" | "reseller";
export type Category = "abatement" | "normal";

export type GstScheme = {
  key: string;
  label: string;
  category: Category;
  subs: readonly SubCategory[];
  /** Why this scheme holds more than one rule, and what picks between them.
   *  Shown above the stacked editors — without it a reader assumes the two rules
   *  are alternatives they are supposed to choose from. */
  note: string;
};

export const SCHEMES: readonly GstScheme[] = [
  {
    key: "abatement", label: "Abatement", category: "abatement",
    subs: ["domestic", "international"],
    note: "Abatement deems a different slice of the fare by sector — 5% domestic and 10% international under Rule 32(3). Which one applies to a ticket follows from where it flies, so this is one scheme, not two.",
  },
  {
    key: "normal", label: "Normal", category: "normal",
    subs: ["agency", "reseller"],
    note: "Normal taxes actual consideration, and how much of it depends on the customer — an agency is taxed on its service charge alone, a reseller on the whole sale. Which one applies follows from that customer's billing type, set when they are onboarded in User Master.",
  },
] as const;

export const schemeByKey = (key: string): GstScheme | undefined =>
  SCHEMES.find(s => s.key === key);

/** What each rule is called inside its scheme. A display name, never an id. */
export const SUB_LABEL: Record<SubCategory, string> = {
  domestic: "Domestic",
  international: "International",
  agency: "Agency",
  reseller: "Reseller",
};

// Mirrors the label map in backend/app/services/gst_calc.formula_text — both
// render the same sentence to the same reader, so they must not drift.
export const BASIS_LABEL: Record<Basis, string> = {
  basic_fare: "Basic Fare",
  service_charge: "Service Charge",
  total_cost: "Total Cost (Fare + Taxes + Service Charge)",
};

/** The basis without its parenthetical, for tight spaces like a stat card. */
export const shortBasis = (basis: Basis) => BASIS_LABEL[basis].split(" (")[0];

/** The row shape `GET /gst-configurations/` returns. */
export type GstConfig = {
  id: number;
  code: string;
  name: string;
  category: Category;
  // Read against its own category: abatement is subdivided by sector, normal by
  // customer type. Nullable only because the column was backfilled by
  // gst_config_02; every live row carries one.
  sub_category: SubCategory | null;
  basis: Basis;
  taxable_value_pct: number | string;
  cgst_pct: number | string;
  sgst_pct: number | string;
  igst_pct: number | string;
  sac_code: string | null;
  valid_from: string | null;
  valid_to: string | null;
  notes: string | null;
  is_active: boolean;
  formula: string | null;
};

export const num = (v: unknown) => (v == null || v === "" ? 0 : Number(v));

/** Percentages print without trailing zeros: 9, 12.5, 0.75. */
export const pct = (v: unknown) => `${Number(num(v).toFixed(3))}%`;

export const money = (v: number) =>
  v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * The rules a scheme covers, ordered by the scheme's own `subs` — so Abatement
 * always reads Domestic before International whatever order the API returns.
 * Rules are matched by (category, sub_category), NEVER by code, so renaming a
 * code cannot break a screen. Missing rules drop out; callers should compare the
 * result's length against `scheme.subs.length` to notice one is absent rather
 * than letting a survivor pose as the whole scheme.
 */
export const rulesForScheme = (scheme: GstScheme, rows: GstConfig[]): GstConfig[] =>
  scheme.subs
    .map(sub => rows.find(r => r.category === scheme.category && r.sub_category === sub))
    .filter((r): r is GstConfig => Boolean(r));

/** True when a scheme's rules disagree on any rate — see `rateMismatch`. */
export const rateMismatch = (rules: GstConfig[]): boolean => {
  if (rules.length < 2) return false;
  const key = (r: GstConfig) => `${num(r.cgst_pct)}/${num(r.sgst_pct)}/${num(r.igst_pct)}`;
  return rules.some(r => key(r) !== key(rules[0]));
};
