/**
 * Workspace → Report download: API shapes, calls and the pure helpers the page and
 * its components share.
 *
 * Mirrors backend/app/api/v1/report_download.py (schemas in
 * backend/app/schemas/report_download.py). Report keys are the backend registry's
 * (services/report_download/registry.py). The tree the user ticks is built from
 * STATEMENT_NAV, so it reads exactly like Vendors → Statements, and
 * NAV_TO_REPORT_KEYS is the one place the two vocabularies meet.
 */
import api from "@/lib/api";
import { STATEMENT_NAV } from "@/lib/statements";

// ── Vocabulary ───────────────────────────────────────────────────────────────

/** Every report source, in the backend registry's sheet order. */
export const REPORT_SOURCE_KEYS = [
  "bsp", "bsp-summary", "adm", "acm", "ra", "tgq-hmpr", "ndc",
  "lcc-detailed", "lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta",
  "tp-gds", "tp-lcc", "tp-api",
] as const;

export type ReportSourceKey = (typeof REPORT_SOURCE_KEYS)[number];
export type DateBasis = "transaction" | "upload";
export type BspScope = "whole_statement" | "issue_date";
export type UndatedRows = "include" | "exclude";
export type DisplayStatus = "waiting" | "generating" | "stalled" | "ready" | "failed" | "expired";

/** Vendors → Statements `category/type` → the report sources behind it. One BSP
 *  upload is a summary + detailed pair, and the ADM / ACM / RA tab switches between
 *  three tables, so those two nav entries fan out. */
export const NAV_TO_REPORT_KEYS: Readonly<Record<string, readonly ReportSourceKey[]>> = {
  "bsp/bsp": ["bsp", "bsp-summary"],
  "bsp/adm-acm-ra": ["adm", "acm", "ra"],
  "bsp/tgq-hmpr": ["tgq-hmpr"],
  "bsp/ndc": ["ndc"],
  "lcc/statement-detailed": ["lcc-detailed"],
  "lcc/di": ["lcc-di"],
  "lcc/divided-pnr": ["lcc-divided-pnr"],
  "lcc/flown-report": ["lcc-flown-report"],
  "lcc/cta-bta": ["lcc-cta-bta"],
  "third-party/gds": ["tp-gds"],
  "third-party/lcc": ["tp-lcc"],
  "third-party/api": ["tp-api"],
};

/** Short names, identical to the workbook's sheet titles, so a chip in the history
 *  names the sheet the user will open. */
const SHEET_LABELS: Readonly<Record<ReportSourceKey, string>> = {
  "bsp": "BSP Detailed",
  "bsp-summary": "BSP Summary",
  "adm": "ADM",
  "acm": "ACM",
  "ra": "RA",
  "tgq-hmpr": "TGQ HMPR",
  "ndc": "NDC",
  "lcc-detailed": "LCC Detailed",
  "lcc-di": "LCC DI",
  "lcc-divided-pnr": "LCC Divided PNR",
  "lcc-flown-report": "LCC Flown Report",
  "lcc-cta-bta": "LCC CTA-BTA",
  "tp-gds": "TP GDS",
  "tp-lcc": "TP LCC",
  "tp-api": "TP API",
};

/** Labels for the sub-checkboxes of a nav entry that fans out to several sources.
 *  Under the "BSP" entry, "BSP" and "BSP Summary" would read as a riddle. */
const SUB_LABELS: Partial<Record<ReportSourceKey, string>> = {
  "bsp": "Detailed",
  "bsp-summary": "Summary",
};

export const BASIS_LABELS: Readonly<Record<DateBasis, string>> = {
  transaction: "Issue / transaction date",
  upload: "Upload date",
};

export const BSP_SCOPE_LABELS: Readonly<Record<BspScope, string>> = {
  whole_statement: "Whole statements overlapping the period",
  issue_date: "Only rows issued in the period",
};

/** Mirrors the backend's cap on `included_uploads` (schemas/report_download.py). */
export const MAX_INCLUDED_UPLOADS = 500;

function isKnownKey(key: string): key is ReportSourceKey {
  return (REPORT_SOURCE_KEYS as readonly string[]).includes(key);
}

export function sourceLabel(key: string): string {
  return isKnownKey(key) ? SHEET_LABELS[key] : key;
}

export function subSourceLabel(key: string, fallback: string): string {
  return (isKnownKey(key) && SUB_LABELS[key]) || fallback;
}

/** Registry order for known keys, then anything else in the order given. Filter
 *  state is kept sorted so two selections compare by value. */
export function sortSourceKeys(keys: Iterable<string>): string[] {
  const unique = Array.from(new Set(keys));
  const rank = (k: string) => (isKnownKey(k) ? REPORT_SOURCE_KEYS.indexOf(k) : REPORT_SOURCE_KEYS.length);
  return unique
    .map((k, i) => ({ k, i }))
    .sort((a, b) => rank(a.k) - rank(b.k) || a.i - b.i)
    .map(({ k }) => k);
}

// ── API shapes ───────────────────────────────────────────────────────────────

export interface SourceTypeCount {
  key: string;
  label: string;
  uploads: number;
  rows: number;
}

export interface SourceCategory {
  category: string;               // "BSP" | "LCC" | "Third Party"
  types: SourceTypeCount[];
}

export interface UploadFilters {
  date_from: string;              // YYYY-MM-DD
  date_to: string;
  basis: DateBasis;
  bsp_scope: BspScope;
  types: string[];                // report source keys, sortSourceKeys order
}

export interface UploadItem {
  source_type: string;
  category: string;
  label: string;
  upload_id: string;
  file_name: string | null;
  uploaded_at: string | null;
  status: string | null;
  reference: string | null;
  total_rows: number;
  rows_in_period: number | null;  // null = counting timed out for this type
  rows_undated: number | null;
  date_min: string | null;
  date_max: string | null;
  selectable: boolean;
  default_selected: boolean;
  possible_duplicate_of: { upload_id: string; file_name: string | null } | null;
  notes: string[];
}

export interface FindUploadsResult {
  uploads: UploadItem[];
  estimated_rows: number;
}

export interface UploadRef {
  source_type: string;
  upload_id: string;
}

export interface ReportOptions {
  include_detail_sheets: boolean;
  include_pii: boolean;
  undated_rows: UndatedRows;
}

export const DEFAULT_REPORT_OPTIONS: ReportOptions = {
  include_detail_sheets: true,
  include_pii: false,
  undated_rows: "include",
};

export interface CreateExportBody {
  title?: string;
  date_from: string;
  date_to: string;
  basis: DateBasis;
  bsp_scope: BspScope;
  source_types: string[];
  included_uploads: UploadRef[];
  unticked_uploads?: UploadRef[];
  options: ReportOptions;
}

export interface ExportListItem {
  id: number;
  title: string | null;
  status: string;
  display_status: DisplayStatus;
  stage: string | null;
  processed_rows: number;
  estimated_rows: number;
  queue_position: number | null;
  date_from: string;
  date_to: string;
  basis: DateBasis;
  source_types: string[];
  combined_rows: number | null;
  file_size: number | null;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  error_code: string | null;
  error: string | null;
}

/** What the report was requested with. Typed loosely on purpose: a report made by
 *  an older build may carry keys or options this one no longer knows, and Run again
 *  must not crash on it. */
export interface ExportParams {
  date_from?: string;
  date_to?: string;
  basis?: string;
  bsp_scope?: string;
  source_types?: string[];
  options?: Partial<Record<keyof ReportOptions, unknown>>;
}

export interface ExportSelectionItem {
  source_type: string;
  upload_id: string;
  file_name?: string | null;
  uploaded_at?: string | null;
  total_rows?: number;
}

export interface ExportRead extends ExportListItem {
  params: ExportParams | null;
  selection: { included?: ExportSelectionItem[]; unticked?: ExportSelectionItem[] } | null;
  sheet_row_counts: Record<string, number> | null;
  summary: Record<string, unknown> | null;
  file_name: string | null;
}

export interface ExportPage {
  items: ExportListItem[];
  total: number;
}

// ── API calls ────────────────────────────────────────────────────────────────

const BASE = "/report-download";

export async function getSources(): Promise<SourceCategory[]> {
  const { data } = await api.get<SourceCategory[]>(`${BASE}/sources`);
  return data;
}

export async function findUploads(filters: UploadFilters): Promise<FindUploadsResult> {
  const { data } = await api.get<FindUploadsResult>(`${BASE}/uploads`, {
    params: {
      date_from: filters.date_from,
      date_to: filters.date_to,
      basis: filters.basis,
      bsp_scope: filters.bsp_scope,
      types: filters.types.join(","),
    },
  });
  return data;
}

export async function createExport(body: CreateExportBody): Promise<ExportRead> {
  const { data } = await api.post<ExportRead>(`${BASE}/exports`, body);
  return data;
}

export async function listExports(limit: number, offset: number): Promise<ExportPage> {
  const { data } = await api.get<ExportPage>(`${BASE}/exports`, { params: { limit, offset } });
  return data;
}

export async function getExport(id: number): Promise<ExportRead> {
  const { data } = await api.get<ExportRead>(`${BASE}/exports/${id}`);
  return data;
}

export async function retryExport(id: number): Promise<ExportRead> {
  const { data } = await api.post<ExportRead>(`${BASE}/exports/${id}/retry`);
  return data;
}

export async function getDownloadUrl(id: number): Promise<{ url: string; expires_in: number }> {
  const { data } = await api.get<{ url: string; expires_in: number }>(`${BASE}/exports/${id}/download-url`);
  return data;
}

export async function deleteExport(id: number): Promise<void> {
  await api.delete(`${BASE}/exports/${id}`);
}

/** The download URL is a GCS signed URL (absolute) or, with local storage, the API's
 *  own token link. If the latter ever comes back root-relative it must resolve
 *  against the API origin, not the Next.js one, or the browser fetches a 404 page. */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const apiBase = new URL(api.defaults.baseURL ?? "/", window.location.origin);
  return new URL(url, apiBase).toString();
}

/** FastAPI's human message out of a failed request: `detail` is a string for an
 *  HTTPException and a list of `{msg}` for a request that failed validation. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  const err = e as { response?: { data?: { detail?: unknown } } };
  if (!err?.response) return fallback;
  const detail = err.response.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msg = (detail[0] as { msg?: unknown } | undefined)?.msg;
    // Pydantic prefixes a validator's own ValueError text; the rest is the sentence.
    if (typeof msg === "string" && msg.trim()) return msg.replace(/^Value error,\s*/, "");
  }
  return fallback;
}

// ── Filters and selection ────────────────────────────────────────────────────

function isoDay(d: Date): string {
  // Local calendar parts, not toISOString(): in IST midnight local is the previous
  // day in UTC, which would shift every default by one.
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The previous calendar month — what a month-end close pulls. */
export function previousMonth(today: Date = new Date()): { date_from: string; date_to: string } {
  const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const last = new Date(today.getFullYear(), today.getMonth(), 0);
  return { date_from: isoDay(first), date_to: isoDay(last) };
}

export function defaultFilters(): UploadFilters {
  return { ...previousMonth(), basis: "transaction", bsp_scope: "whole_statement", types: [...REPORT_SOURCE_KEYS] };
}

export function sameFilters(a: UploadFilters, b: UploadFilters): boolean {
  return a.date_from === b.date_from
    && a.date_to === b.date_to
    && a.basis === b.basis
    && a.bsp_scope === b.bsp_scope
    && a.types.length === b.types.length
    && a.types.every((t, i) => t === b.types[i]);
}

/** Why Find uploads cannot run yet, or null. The server re-validates everything
 *  (period span included); this only catches what is obvious before a round trip. */
export function filterProblem(f: UploadFilters): string | null {
  if (!f.date_from || !f.date_to) return "Choose both a From and a To date.";
  if (f.date_from > f.date_to) return "The From date is after the To date.";
  if (f.types.length === 0) return "Tick at least one source type.";
  return null;
}

export function uploadKey(sourceType: string, uploadId: string): string {
  return `${sourceType}::${uploadId}`;
}

export interface SelectionPreset {
  included: ReadonlySet<string>;
  unticked: ReadonlySet<string>;
}

/** Ticks per the server's `default_selected`, except where a previous report
 *  (Run again) already decided: its included files stay ticked and the files it
 *  unticked stay unticked. Uploads that are not selectable are never ticked. */
export function initialSelection(uploads: UploadItem[], preset?: SelectionPreset): Set<string> {
  const out = new Set<string>();
  for (const u of uploads) {
    if (!u.selectable) continue;
    const key = uploadKey(u.source_type, u.upload_id);
    const pick = preset?.included.has(key) ? true
      : preset?.unticked.has(key) ? false
      : u.default_selected;
    if (pick) out.add(key);
  }
  return out;
}

/** "~M rows" for the ticked uploads: rows in the period (plus undated rows unless
 *  they are excluded), or the whole upload when its counts timed out. An estimate
 *  for the user, not the server's cap check. */
export function estimateRows(uploads: UploadItem[], undated: UndatedRows): number {
  return uploads.reduce((sum, u) => {
    if (u.rows_in_period == null) return sum + u.total_rows;
    return sum + u.rows_in_period + (undated === "include" ? (u.rows_undated ?? 0) : 0);
  }, 0);
}

export interface Prefill {
  filters: UploadFilters;
  options: ReportOptions;
  title: string;
  preset: SelectionPreset;
}

/** Run again: the filters, options and ticks a previous report was made with.
 *  `allowedKeys` drops source types this build cannot list any more. */
export function prefillFromExport(exp: ExportRead, allowedKeys: ReadonlySet<string>): Prefill {
  const p = exp.params ?? {};
  const o = p.options ?? {};
  const toKeys = (items: ExportSelectionItem[] | undefined) =>
    new Set((items ?? []).map((i) => uploadKey(i.source_type, i.upload_id)));
  return {
    filters: {
      date_from: p.date_from ?? exp.date_from,
      date_to: p.date_to ?? exp.date_to,
      basis: (p.basis ?? exp.basis) === "upload" ? "upload" : "transaction",
      bsp_scope: p.bsp_scope === "issue_date" ? "issue_date" : "whole_statement",
      types: sortSourceKeys((p.source_types ?? exp.source_types).filter((k) => allowedKeys.has(k))),
    },
    options: {
      include_detail_sheets: typeof o.include_detail_sheets === "boolean"
        ? o.include_detail_sheets : DEFAULT_REPORT_OPTIONS.include_detail_sheets,
      include_pii: o.include_pii === true,
      undated_rows: o.undated_rows === "exclude" ? "exclude" : "include",
    },
    title: exp.title ?? "",
    preset: { included: toKeys(exp.selection?.included), unticked: toKeys(exp.selection?.unticked) },
  };
}

// ── Type tree ────────────────────────────────────────────────────────────────

export interface ReportTypeNode {
  id: string;                     // "bsp/adm-acm-ra"
  label: string;                  // STATEMENT_NAV label
  keys: string[];
}

export interface ReportCategoryNode {
  category: string;
  types: ReportTypeNode[];
}

/** Category → type tree in Vendors → Statements order. A source the backend lists
 *  but this build has no nav entry for is appended under its category, so a
 *  registry addition cannot silently vanish from the picker. */
export function buildTypeTree(sources: SourceCategory[] | null): ReportCategoryNode[] {
  const tree: ReportCategoryNode[] = STATEMENT_NAV.map((cat) => ({
    category: cat.label,
    types: cat.types.flatMap((t) => {
      const id = `${cat.slug}/${t.slug}`;
      const keys = NAV_TO_REPORT_KEYS[id];
      return keys ? [{ id, label: t.label, keys: [...keys] }] : [];
    }),
  }));
  const mapped = new Set(tree.flatMap((c) => c.types.flatMap((t) => t.keys)));
  for (const cat of sources ?? []) {
    for (const t of cat.types) {
      if (mapped.has(t.key)) continue;
      let node = tree.find((c) => c.category === cat.category);
      if (!node) {
        node = { category: cat.category, types: [] };
        tree.push(node);
      }
      node.types.push({ id: `source/${t.key}`, label: t.label, keys: [t.key] });
      mapped.add(t.key);
    }
  }
  return tree;
}

export function treeKeys(tree: ReportCategoryNode[]): Set<string> {
  return new Set(tree.flatMap((c) => c.types.flatMap((t) => t.keys)));
}

/** Source keys the user actually has uploads for — the default ticks. */
export function keysWithUploads(sources: SourceCategory[]): string[] {
  return sortSourceKeys(sources.flatMap((c) => c.types.filter((t) => t.uploads > 0).map((t) => t.key)));
}

// ── Status and formatting ────────────────────────────────────────────────────

export type StatusTone = "grey" | "blue" | "amber" | "green" | "red";

const STATUS_META: Readonly<Record<DisplayStatus, { label: string; tone: StatusTone; active: boolean }>> = {
  waiting: { label: "Waiting", tone: "grey", active: true },
  generating: { label: "Generating", tone: "blue", active: true },
  stalled: { label: "Stalled", tone: "amber", active: true },
  ready: { label: "Ready", tone: "green", active: false },
  failed: { label: "Failed", tone: "red", active: false },
  expired: { label: "Expired", tone: "grey", active: false },
};

/** Label and tone per display status. `active` = the history keeps polling. A
 *  status this build does not know renders grey and does not hold polling open. */
export function statusMeta(status: string): { label: string; tone: StatusTone; active: boolean } {
  return STATUS_META[status as DisplayStatus] ?? { label: status, tone: "grey", active: false };
}

/** The API serialises its UTC timestamps without a zone (TIMESTAMP columns written
 *  with utcnow). Parsed as-is they would read as local time, 5h30 early in IST. */
export function parseServerTime(value: string): Date {
  return new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
}

/** "01 Aug 2026" from a YYYY-MM-DD (or longer ISO) string, without a timezone
 *  round trip that could move a date-only value to the previous day. */
export function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return value;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const d = parseServerTime(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function formatServerDay(value: string | null | undefined): string {
  if (!value) return "—";
  const d = parseServerTime(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** Indian digit grouping, like every other count in the product. */
export function formatCount(n: number): string {
  return n.toLocaleString("en-IN");
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}
