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
import { CORPORATE_TYPES, GSTIN_RE, PAN_RE, type PartyKind } from "@/lib/party";

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

export const IMPORT_FIELDS: Record<PartyKind, ImportField[]> = {
  customer: [
    { key: "first_name", label: "First Name", type: "text", required: true, aliases: ["firstname", "fname", "given_name", "name"] },
    { key: "last_name", label: "Last Name", type: "text", aliases: ["lastname", "lname", "surname"] },
    {
      key: "company", label: "Company", type: "text",
      aliases: ["corporate", "employer", "organisation", "organization", "firm", "company_name"],
      hint: "Matched to Corporate Master by name; no match stays individual / direct",
    },
    { key: "title", label: "Title", type: "text", aliases: ["salutation", "designation"] },
    { key: "phone", label: "Phone / Contact", type: "text", aliases: ["contact", "mobile", "phone_no", "contact_no", "telephone"] },
    { key: "email", label: "Email", type: "text", aliases: ["email_id", "mail", "email_address"] },
    ...TAX_AND_BILLING_FIELDS,
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
    { key: "state", label: "State", type: "text", aliases: ["region"] },
    { key: "pincode", label: "Pincode", type: "text", aliases: ["pin", "pin_code", "postal_code", "zip", "zipcode"] },
    { key: "country", label: "Country", type: "text" },
    ...TAX_AND_BILLING_FIELDS,
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
  return errors;
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
  return payload;
}
