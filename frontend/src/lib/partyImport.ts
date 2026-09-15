// The Excel import behind Employee Master and Corporate Master: what our columns
// are, how to guess which of the user's columns is which, and what makes a row
// valid. Everything here is pure — the wizard that drives it lives in
// components/party/PartyUploadModal.tsx.
//
// WHY THE FILE IS PARSED IN THE BROWSER. The mapping and review steps need the
// user's headers and their data before anything is saved, and a round trip per
// keystroke to re-preview a file the browser already holds buys nothing. The
// server sees the reviewed rows once, as JSON, at Confirm & Save
// (/{resource}/bulk-create) — and re-validates every one of them, because
// nothing a browser sends is trusted.
//
// The older one-shot /{resource}/bulk-upload endpoint still exists and still
// works; it is what this replaces in the UI, and it keeps serving the templates.

import * as XLSX from "xlsx";
import {
  CORPORATE_TYPES, GSTIN_RE, MARKUP_CATEGORIES, PAN_RE,
  type CategoryMarkups, type MarkupCategory, type MarkupType, type Party, type PartyKind,
} from "@/lib/party";

// ── Field spec ───────────────────────────────────────────────────────────────

export type ImportFieldType = "text" | "number" | "choice" | "boolean";

export type ImportField = {
  /** Payload key — what the API receives. */
  key: string;
  label: string;
  type: ImportFieldType;
  required?: boolean;
  /**
   * Extra header spellings to auto-match, normalised the same way headers are.
   * `key` itself is always tried first, so it never needs repeating here.
   */
  aliases?: string[];
  /** choice only — the stored value and what the review dropdown shows. */
  options?: { value: string; label: string }[];
  /** Shown under the field name in the mapping step. */
  hint?: string;
  /** Starts a titled section in the mapping step when it differs from the field before. */
  group?: string;
};

const MARKUP_TYPE_OPTIONS = [
  { value: "percentage", label: "Percentage (%)" },
  { value: "fixed", label: "Fixed (₹)" },
];
const BILLING_TYPE_OPTIONS = [
  { value: "reseller", label: "Reseller" },
  { value: "agency", label: "Agency" },
];

/** Shared by both kinds, in the order they appear in the mapping and review steps. */
const TAX_AND_BILLING_FIELDS: ImportField[] = [
  {
    key: "gst_registered", label: "GST Registration", type: "boolean",
    aliases: ["gst_registration", "gst_status", "registered", "gst_reg"],
    hint: "Registered / Unregistered",
  },
  { key: "gst_no", label: "GST No", type: "text", aliases: ["gstin", "gst_number", "gst"] },
  { key: "pan_no", label: "PAN No", type: "text", aliases: ["pan", "pan_number"] },
  {
    key: "markup_type", label: "Markup Type", type: "choice",
    options: MARKUP_TYPE_OPTIONS, aliases: ["markup"],
  },
  { key: "markup_value", label: "Markup Value", type: "number", aliases: ["markup_amount", "markup_val"] },
  {
    key: "billing_type", label: "Billing Type", type: "choice",
    options: BILLING_TYPE_OPTIONS, aliases: ["billing"],
  },
];

/**
 * The optional per-category markup, as a TYPE + VALUE pair per category — the same shape as
 * the default Markup Type / Markup Value above, and the same column names the server's
 * template writes (party_markup.CATEGORY_COLUMNS): AIR_MARKUP_TYPE, AIR_MARKUP_VALUE, ….
 * A pair rather than one "5%" cell, because Excel turns a typed "5%" into 0.05.
 *
 * These are flat here so the mapping and review steps need nothing new; toPayload folds
 * them into the `category_markups` object the API takes. Files from before these columns
 * existed simply leave them unmapped.
 */
export const CATEGORY_FIELD_KEYS = MARKUP_CATEGORIES.map(({ value, label }) => ({
  slug: value, label, typeKey: `${value}_markup_type`, valueKey: `${value}_markup_value`,
}));

const CATEGORY_ALIASES: Partial<Record<MarkupCategory, string[]>> = {
  air: ["flight", "airline"],
  car: ["cab"],
};

const CATEGORY_MARKUP_FIELDS: ImportField[] = CATEGORY_FIELD_KEYS.flatMap(({ slug, label, typeKey, valueKey }) => [
  {
    key: typeKey, label: `${label} Markup Type`, type: "choice" as const, options: MARKUP_TYPE_OPTIONS,
    group: "Markup by category — optional, blank uses the default markup",
    aliases: (CATEGORY_ALIASES[slug] ?? []).map((a) => `${a}_markup_type`),
  },
  {
    key: valueKey, label: `${label} Markup Value`, type: "number" as const,
    group: "Markup by category — optional, blank uses the default markup",
    aliases: (CATEGORY_ALIASES[slug] ?? []).map((a) => `${a}_markup_value`),
  },
]);

export const IMPORT_FIELDS: Record<PartyKind, ImportField[]> = {
  customer: [
    { key: "first_name", label: "First Name", type: "text", required: true, aliases: ["firstname", "fname", "given_name", "name"] },
    { key: "last_name", label: "Last Name", type: "text", aliases: ["lastname", "lname", "surname"] },
  { key: "employee_code", label: "Employee Code", type: "text",
    aliases: ["emp_code", "employee_id", "staff_code", "emp_id", "payroll_id"] },
    {
      key: "company", label: "Company", type: "text",
      aliases: ["corporate", "employer", "organisation", "organization", "firm", "company_name"],
      hint: "Matched to Corporate Master by name; no match stays individual / direct",
    },
    { key: "title", label: "Title", type: "text", aliases: ["salutation", "designation"] },
    { key: "phone", label: "Phone / Contact", type: "text", aliases: ["contact", "mobile", "phone_no", "contact_no", "telephone"] },
    { key: "email", label: "Email", type: "text", aliases: ["email_id", "mail", "email_address"] },
    ...TAX_AND_BILLING_FIELDS,
    ...CATEGORY_MARKUP_FIELDS,
  ],
  corporate: [
    {
      key: "company", label: "Corporate Name", type: "text", required: true,
      aliases: ["corporate", "corporate_name", "name", "organisation", "organization", "firm", "company_name"],
    },
    {
      key: "corporate_type", label: "Corporate Type", type: "choice",
      options: CORPORATE_TYPES, aliases: ["type", "entity_type", "legal_form", "constitution"],
    },
    { key: "phone", label: "Phone / Contact", type: "text", aliases: ["contact", "mobile", "phone_no", "contact_no", "telephone"] },
    { key: "email", label: "Email", type: "text", aliases: ["email_id", "mail", "email_address"] },
    { key: "address", label: "Address", type: "text", aliases: ["address_1", "address_line_1", "street", "registered_address"] },
    { key: "city", label: "City", type: "text", aliases: ["town"] },
    // Required: for an Unregistered corporate it is all place of supply has to go on.
    { key: "state", label: "State", type: "text", required: true, aliases: ["region"] },
    { key: "pincode", label: "Pincode", type: "text", aliases: ["pin", "pin_code", "postal_code", "zip", "zipcode"] },
    { key: "country", label: "Country", type: "text" },
    ...TAX_AND_BILLING_FIELDS,
    ...CATEGORY_MARKUP_FIELDS,
  ],
};

// ── Value normalising ────────────────────────────────────────────────────────

/** Headers and free-text choice values reduce to the same slug shape. */
export function normalizeKey(value: string): string {
  return String(value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

const TRUTHY = new Set(["registered", "yes", "true", "y", "1"]);

/**
 * Spellings people actually type for a corporate's legal form.
 * Mirrors _CORPORATE_TYPE_ALIASES in backend/app/api/v1/corporates.py — the
 * server re-normalises anyway, so a miss here is a blank the user fills in at
 * review, never a wrong value that gets saved.
 */
const CORPORATE_TYPE_ALIASES: Record<string, string> = {
  sole_proprietorship: "proprietorship", proprietary_firm: "proprietorship",
  proprietor: "proprietorship", proprietary: "proprietorship",
  proprietorship_proprietary_firm: "proprietorship",
  partnership_firm: "partnership",
  limited_liability_partnership: "llp", llp_limited_liability_partnership: "llp",
  pvt_ltd: "private_limited", private_ltd: "private_limited", private_limited_company: "private_limited",
  public_ltd: "public_limited", public_limited_company: "public_limited",
  one_person_company: "opc", one_person_company_opc: "opc",
  hindu_undivided_family: "huf", huf_hindu_undivided_family: "huf",
  ngo: "society", society_ngo: "society",
  psu: "government", government_psu: "government", govt: "government",
};

/** A raw cell → the value a choice field stores, or "" when nothing matches. */
export function normalizeChoice(field: ImportField, raw: string): string {
  const slug = normalizeKey(raw);
  if (!slug) return "";
  const options = field.options ?? [];
  if (options.some((o) => o.value === slug)) return slug;
  if (field.key === "corporate_type") {
    const aliased = CORPORATE_TYPE_ALIASES[slug];
    if (aliased) return aliased;
  }
  // Last resort: the label as displayed ("Percentage (%)" → percentage).
  const byLabel = options.find((o) => normalizeKey(o.label) === slug);
  return byLabel ? byLabel.value : "";
}

/** A raw cell → the string the review grid holds for this field. */
export function normalizeCell(field: ImportField, raw: string): string {
  const value = String(raw ?? "").trim();
  if (!value) return "";
  switch (field.type) {
    case "boolean":
      return TRUTHY.has(value.toLowerCase()) ? "true" : "false";
    case "choice":
      return normalizeChoice(field, value);
    case "number":
      return value;
    default:
      return field.key === "gst_no" || field.key === "pan_no" ? value.toUpperCase() : value;
  }
}

// ── Reading the workbook ─────────────────────────────────────────────────────

export type ParsedSheet = {
  /** Column headers, in sheet order. Blank and duplicate headers are made unique. */
  columns: string[];
  /** One entry per data row: header → raw cell text. */
  rows: Record<string, string>[];
  /**
   * The 1-based sheet line each entry of `rows` came from, parallel to it.
   * Carried explicitly because blank rows are dropped: deriving the number from
   * the array index would misname every row after the first gap, and the number
   * is only useful if it points at the line the user can actually go and look at.
   */
  rowNumbers: number[];
  /** 1-based sheet row the header was found on. */
  headerRow: number;
  sheetName: string;
};

/** Header rows are not always row 1 — files often open with a title or a blank. */
function findHeaderRow(grid: string[][]): number {
  for (let i = 0; i < Math.min(grid.length, 5); i++) {
    const filled = (grid[i] ?? []).filter((c) => String(c ?? "").trim() !== "").length;
    if (filled >= 2) return i;
  }
  return 0;
}

/** Blank headers get a position name; repeats get a suffix, so no column is lost. */
function uniqueHeaders(raw: string[]): string[] {
  const seen = new Map<string, number>();
  return raw.map((cell, i) => {
    const base = String(cell ?? "").trim() || `Column ${i + 1}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base} (${n})`;
  });
}

export function parseWorkbook(data: ArrayBuffer): ParsedSheet {
  const wb = XLSX.read(data, { type: "array" });
  const sheetName = wb.SheetNames[0];
  if (!sheetName) throw new Error("This file has no sheets.");
  const ws = wb.Sheets[sheetName];
  // raw:false so dates and numbers arrive as the text the user sees in Excel.
  const grid = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, raw: false, defval: "" });
  if (!grid.length) throw new Error("This sheet is empty.");

  const headerIdx = findHeaderRow(grid);
  const columns = uniqueHeaders(grid[headerIdx] ?? []);
  if (!columns.length) throw new Error("No column headers found in the first few rows.");

  const rows: Record<string, string>[] = [];
  const rowNumbers: number[] = [];
  for (let i = headerIdx + 1; i < grid.length; i++) {
    const cells = grid[i] ?? [];
    if (cells.every((c) => String(c ?? "").trim() === "")) continue;   // skip blank rows
    const row: Record<string, string> = {};
    columns.forEach((col, c) => { row[col] = String(cells[c] ?? "").trim(); });
    rows.push(row);
    rowNumbers.push(i + 1);
  }
  return { columns, rows, rowNumbers, headerRow: headerIdx + 1, sheetName };
}

// ── Auto-mapping ─────────────────────────────────────────────────────────────

/**
 * Best guess at which sheet column feeds which of our fields.
 *
 * Exact slug match first for EVERY field, then a contains pass — so a sheet with
 * both "Name" and "Company Name" gives "Name" to first_name on the exact pass
 * instead of losing it to a loose match made earlier in the field order. A column
 * is claimed once; ambiguity is left for the user to resolve in the mapping step.
 */
export function autoMap(fields: ImportField[], columns: string[]): Record<string, string> {
  const map: Record<string, string> = {};
  const taken = new Set<string>();
  const slugs = new Map(columns.map((c) => [c, normalizeKey(c)]));

  const claim = (field: ImportField, match: (colSlug: string, candidate: string) => boolean) => {
    if (map[field.key]) return;
    const candidates = [field.key, ...(field.aliases ?? [])];
    for (const col of columns) {
      if (taken.has(col)) continue;
      const colSlug = slugs.get(col) ?? "";
      if (!colSlug) continue;
      if (candidates.some((cand) => match(colSlug, cand))) {
        map[field.key] = col;
        taken.add(col);
        return;
      }
    }
  };

  for (const field of fields) claim(field, (colSlug, cand) => colSlug === cand);
  for (const field of fields) {
    claim(field, (colSlug, cand) =>
      cand.length >= 3 && (colSlug.includes(cand) || cand.includes(colSlug))
    );
  }
  return map;
}

// ── Rows and validation ──────────────────────────────────────────────────────

export type ReviewRow = {
  /** Sheet row number, so an error names the line the user can go and look at. */
  sheetRow: number;
  /** Field key → the value as it will be saved. Edited in place during review. */
  values: Record<string, string>;
  /** Excluded rows are kept visible but not sent. */
  included: boolean;
};

export function applyMapping(
  fields: ImportField[],
  mapping: Record<string, string>,
  sheet: ParsedSheet,
): ReviewRow[] {
  return sheet.rows.map((row, i) => {
    const values: Record<string, string> = {};
    for (const field of fields) {
      const col = mapping[field.key];
      values[field.key] = col ? normalizeCell(field, row[col] ?? "") : "";
    }
    // No registration given but a GSTIN is: that row is registered. Left blank it would be
    // sent as Unregistered and toPayload would throw the GSTIN away. Mirrors
    // corporates.py::_is_registered.
    if ("gst_registered" in values && !values.gst_registered && values.gst_no?.trim()) {
      values.gst_registered = "true";
    }
    return { sheetRow: sheet.rowNumbers[i], values, included: true };
  });
}

/** Field key → why that cell is wrong. Empty object means the row can be saved. */
export function validateRow(fields: ImportField[], values: Record<string, string>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const value = (values[field.key] ?? "").trim();
    if (field.required && !value) {
      errors[field.key] = `${field.label} is required.`;
      continue;
    }
    if (!value) continue;
    if (field.type === "number" && isNaN(Number(value))) {
      errors[field.key] = `${field.label} must be a number.`;
    }
    if (field.key === "pan_no" && !PAN_RE.test(value.toUpperCase())) {
      errors[field.key] = "PAN must look like ABCDE1234F.";
    }
  }
  // GST is a pair, not a field: a number is required when — and only when — the
  // row says registered, which is why it cannot be checked in the loop above.
  const registered = (values.gst_registered ?? "") === "true";
  const gstNo = (values.gst_no ?? "").trim().toUpperCase();
  if (registered && !GSTIN_RE.test(gstNo)) {
    errors.gst_no = "A registered party needs a valid 15-character GSTIN (e.g. 27ABCDE1234F1Z5).";
  }
  // Each category is a pair too. Half of one would be saved as nothing at all, and the
  // category would quietly bill at the default — so it is flagged rather than dropped.
  for (const { label, typeKey, valueKey } of CATEGORY_FIELD_KEYS) {
    if (!(typeKey in values) && !(valueKey in values)) continue;
    const type = (values[typeKey] ?? "").trim();
    const value = (values[valueKey] ?? "").trim();
    if (value && !type) errors[typeKey] = `Pick Percentage or Fixed for the ${label} markup.`;
    if (type && !value) errors[valueKey] = `Enter the ${label} markup value, or clear its type.`;
  }
  return errors;
}

// ── Duplicates ───────────────────────────────────────────────────────────────
//
// THE SAME RULE AS backend/app/services/party_dedupe.py, run early so a duplicate is a
// red cell in the review grid rather than a line in the post-mortem. The server still
// applies it — this cannot be trusted and is not the enforcement — but a user who is
// told at Review can fix the file, and one told at Done cannot.
//
// The wording differs from the server's on purpose. There, a duplicate is a row that was
// REJECTED and the sentence has to say what happened to it; here nothing has been saved
// yet and the sentence has to say what to change.
//
// An employee is their NAME under an EMPLOYER, and nothing else: phone, email, GSTIN and
// PAN are all inherited from the corporate (lib/party.ts INHERITED_FIELDS), so every
// employee of one company shares them by design. A corporate is its NAME or its GSTIN,
// either alone.

/** `"  Acme   Pvt Ltd "` → `"acme pvt ltd"`. Mirrors party_dedupe.name_key. */
export function nameKey(value: string | null | undefined): string {
  return String(value ?? "").trim().toLowerCase().split(/\s+/).join(" ");
}

/** A GSTIN as it is stored — upper, unpadded. Mirrors party_dedupe.code_key. */
export function codeKey(value: string | null | undefined): string {
  return String(value ?? "").trim().toUpperCase();
}

/** Not a separator anyone can type, so two key parts can never run together. */
const KEY_SEP = " ";

/**
 * WHO THEY WORK FOR, as one comparable string — party_dedupe.employer_key.
 *
 * A linked employee is keyed by the corporate's id, an unlinked one by the free text
 * they named, and `name:` (individual / direct) is a real answer rather than a blank.
 */
function employerKey(corporateId: number | null | undefined, company: string | null | undefined): string {
  return corporateId != null ? `corp:${corporateId}` : `name:${nameKey(company)}`;
}

/**
 * The person identity — party_dedupe.CustomerDuplicates.key. The EMPLOYEE CODE is part of
 * it, which is what lets two genuine namesakes at one employer both save once each has a
 * code; without it this flagged a file the server would have accepted.
 */
function customerKey(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
  corporateId: number | null | undefined,
  company: string | null | undefined,
  employeeCode: string | null | undefined,
): string {
  return ["person", nameKey(`${firstName ?? ""} ${lastName ?? ""}`), employerKey(corporateId, company),
    codeKey(employeeCode)].join(KEY_SEP);
}

/**
 * The name under an employer, whatever the code — party_dedupe.CustomerDuplicates.named_key.
 * Every employee holds it; only a row WITHOUT a code is checked against it, so an uncoded
 * row cannot slip in beside a coded namesake.
 */
function namedKey(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
  corporateId: number | null | undefined,
  company: string | null | undefined,
): string {
  return ["named", nameKey(`${firstName ?? ""} ${lastName ?? ""}`), employerKey(corporateId, company)].join(KEY_SEP);
}

/** An Employee Code is its own identity, workspace-wide. "" when there is no code. */
function employeeCodeKey(employeeCode: string | null | undefined): string {
  const code = codeKey(employeeCode);
  return code ? `emp_code${KEY_SEP}${code}` : "";
}

type CorporateFacet = { facet: "name" | "gstin"; field: string; key: string; value: string };

/** Every identity a corporate occupies. A blank name or GSTIN occupies none. */
function corporateFacets(company: string | null | undefined, gstNo: string | null | undefined): CorporateFacet[] {
  const out: CorporateFacet[] = [];
  const name = nameKey(company);
  if (name) out.push({ facet: "name", field: "company", key: `name${KEY_SEP}${name}`, value: name });
  const gst = codeKey(gstNo);
  if (gst) out.push({ facet: "gstin", field: "gst_no", key: `gstin${KEY_SEP}${gst}`, value: gst });
  return out;
}

/** How a message names the employer. Blank is a state, so it gets named too. */
function employerPhrase(company: string): string {
  const label = company.trim();
  return label ? `under ${label}` : "as an individual / direct customer";
}

export type DuplicateContext = {
  /** Identity key → how to name whoever already holds it. */
  existing: Map<string, string>;
  /**
   * Customers only: normalised corporate name → its id, so an imported row is keyed by
   * the corporate the server will LINK it to rather than by the text it was typed as.
   * Lowest id wins on a tie, matching api/v1/customers.py::_corporate_name_map.
   */
  corporateIds: Map<string, number>;
};

/**
 * Index the master as it stands, for the review grid to check rows against.
 *
 * `corporates` is only read for `kind === "customer"` — it is what resolves an imported
 * row's COMPANY column to an employer id. For a corporate import, `master` is itself the
 * corporate list and the second argument is ignored.
 */
export function buildDuplicateContext(
  kind: PartyKind,
  master: Party[],
  corporates: Party[],
): DuplicateContext {
  const corporateIds = new Map<string, number>();
  for (const c of [...corporates].sort((a, b) => a.id - b.id)) {
    const key = nameKey(c.company);
    if (key && !corporateIds.has(key)) corporateIds.set(key, c.id);
  }

  const existing = new Map<string, string>();
  for (const p of [...master].sort((a, b) => a.id - b.id)) {
    if (kind === "customer") {
      const label = `${p.first_name ?? ""} ${p.last_name ?? ""}`.trim();
      const key = customerKey(p.first_name, p.last_name, p.corporate_id, p.company, p.employee_code);
      if (!existing.has(key)) existing.set(key, label);
      const codeK = employeeCodeKey(p.employee_code);
      if (codeK && !existing.has(codeK)) existing.set(codeK, label);
      const namedK = namedKey(p.first_name, p.last_name, p.corporate_id, p.company);
      if (!existing.has(namedK)) existing.set(namedK, codeK ? `${label} (${codeKey(p.employee_code)})` : label);
    } else {
      const label = (p.company ?? "").trim() || "an unnamed corporate";
      for (const { key } of corporateFacets(p.company, p.gst_no)) {
        if (!existing.has(key)) existing.set(key, label);
      }
    }
  }
  return { existing, corporateIds };
}

/**
 * Field key → why that cell duplicates something, per row, parallel to `rows`.
 *
 * Merged over `baseErrors` by the caller, so a duplicate reads like any other bad cell.
 * Only rows that will actually be SENT can take an identity — the server never sees an
 * unticked or already-invalid row, so neither does this, and the two stay in step on
 * which of two identical rows is the one that survives (the first).
 *
 * `ctx` is null while the master is still loading, or when it could not be read; the
 * check is then skipped entirely rather than reporting a clean file it never verified.
 */
export function duplicateRowErrors(
  kind: PartyKind,
  rows: ReviewRow[],
  baseErrors: Record<string, string>[],
  ctx: DuplicateContext | null,
): Record<string, string>[] {
  const out: Record<string, string>[] = rows.map(() => ({}));
  if (!ctx) return out;

  const claimed = new Map<string, number>();     // key → the sheet row that took it first

  rows.forEach((row, i) => {
    if (!row.included || Object.keys(baseErrors[i]).length > 0) return;

    if (kind === "customer") {
      const company = (row.values.company ?? "").trim();
      const corporateId = ctx.corporateIds.get(nameKey(company)) ?? null;
      const code = codeKey(row.values.employee_code);
      const key = customerKey(row.values.first_name, row.values.last_name, corporateId, company, code);
      const codeK = employeeCodeKey(code);
      // Person first, then code — the order CustomerDuplicates.check reports them in.
      const heldBy = claimed.get(key);
      if (heldBy != null) {
        out[i].first_name = `Same name and employer as row ${heldBy} of this file. ` +
          "If they are different people, give each an Employee Code.";
        return;
      }
      if (ctx.existing.has(key)) {
        out[i].first_name = `Already in Employee Master ${employerPhrase(company)}. ` +
          "If this is a different person, give them an Employee Code.";
        return;
      }
      if (codeK && claimed.has(codeK)) {
        out[i].employee_code = `Employee Code ${code} is also on row ${claimed.get(codeK)} of this file.`;
        return;
      }
      if (codeK && ctx.existing.has(codeK)) {
        out[i].employee_code = `Employee Code ${code} is already used in Employee Master, on ${ctx.existing.get(codeK)}.`;
        return;
      }
      const namedK = namedKey(row.values.first_name, row.values.last_name, corporateId, company);
      if (!code && ctx.existing.has(namedK)) {
        out[i].first_name = `Already in Employee Master ${employerPhrase(company)}, as ${ctx.existing.get(namedK)}. ` +
          "Give this one an Employee Code of its own.";
        return;
      }
      if (!code && claimed.has(namedK)) {
        out[i].first_name = `Same name and employer as row ${claimed.get(namedK)} of this file. ` +
          "Give each of them an Employee Code.";
        return;
      }
      claimed.set(key, row.sheetRow);
      if (codeK) claimed.set(codeK, row.sheetRow);
      if (!claimed.has(namedK)) claimed.set(namedK, row.sheetRow);
      return;
    }

    // An Unregistered row's GSTIN is dropped before it is saved (toPayload), so it
    // occupies no identity and cannot be anyone's duplicate.
    const facets = corporateFacets(
      row.values.company,
      row.values.gst_registered === "true" ? row.values.gst_no : null,
    );
    for (const { facet, field, key } of facets) {
      const heldBy = claimed.get(key);
      if (heldBy != null) {
        out[i][field] = facet === "name"
          ? `Same corporate name as row ${heldBy} of this file.`
          : `Same GST No as row ${heldBy} of this file.`;
        return;
      }
      if (ctx.existing.has(key)) {
        out[i][field] = facet === "name"
          ? "Already in Corporate Master."
          : `This GST No is already in Corporate Master, on ${ctx.existing.get(key)}.`;
        return;
      }
    }
    // Claimed only once the whole row is clear, so a row rejected on its GSTIN does not
    // leave its NAME taken and blame the wrong line for the next one.
    for (const { key } of facets) if (!claimed.has(key)) claimed.set(key, row.sheetRow);
  });

  return out;
}

/** The row as the API wants it: trimmed, typed, and blanks as null. */
export function toPayload(fields: ImportField[], values: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of fields) {
    const value = (values[field.key] ?? "").trim();
    if (field.type === "boolean") {
      payload[field.key] = value === "true";
    } else if (field.type === "number") {
      payload[field.key] = value ? Number(value) : null;
    } else {
      payload[field.key] = value || null;
    }
  }
  // Unregistered never carries a GST number, matching the Add/Edit form and the
  // server, which clears it either way.
  if (payload.gst_registered !== true) payload.gst_no = null;
  // The flat category pairs → the one object the API stores. null, not {}, when none.
  const categoryMarkups: CategoryMarkups = {};
  for (const { slug, typeKey, valueKey } of CATEGORY_FIELD_KEYS) {
    const type = payload[typeKey];
    const value = payload[valueKey];
    delete payload[typeKey];
    delete payload[valueKey];
    if ((type === "percentage" || type === "fixed") && typeof value === "number" && !Number.isNaN(value)) {
      categoryMarkups[slug] = { type: type as MarkupType, value };
    }
  }
  payload.category_markups = Object.keys(categoryMarkups).length ? categoryMarkups : null;
  return payload;
}
