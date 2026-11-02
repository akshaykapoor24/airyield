// Internal Statement's upload for files of any size — backend api/v1/internal_imports.py and
// services/internal_import.py. The file is uploaded once; a worker reads it into rows kept on
// the server, the review pages through them, and a worker saves the statement. The browser never
// holds the file's lines.

import api from "@/lib/api";
import type { DetectedFormat } from "@/components/statements/dateFormat";
import type { TicketExtractionPreview, TicketRow } from "@/lib/ticketFields";

export type ImportStatus = "uploaded" | "parsing" | "ready" | "saving" | "saved" | "failed";
export type ImportPhase = "queued" | "reading" | "checking" | "writing" | "saving" | null;

/** The upload step's answer: the columns as /upload/extract gives them, and the date format. */
export type ImportHead = {
  import_id: string;
  preview: TicketExtractionPreview;
  date_formats: { period_label: string | null; fields: DetectedFormat[] };
};

/** How one date column reads — the page's DatesRead, counted on the server. `key` is the field
 *  read: "doc_date" when the file has only a Doc Date for its Booking Date. */
export type ImportDates = {
  field: string; key: string; read: number; first: string | null; last: string | null;
  unreadable: number; cells: { index: number; value: string | null }[];
};

/** The duplicates box — the same shape POST /upload/duplicates answers. */
export type ImportDuplicates = {
  total: number; duplicates: number; duplicates_amount: string; new: number;
  statements: {
    batch_id: string; statement_name: string | null; file_name: string | null;
    period_label: string; uploaded_at: string | null; matched: number;
  }[];
  lines: {
    doc_no: string | null; ticket_number: string | null; pax_name: string | null;
    booked_date: string | null; travel_date: string | null; total_amt: number | string | null;
    index: number; batch_id: string;
  }[];
  rows: { index: number; batch_id: string }[];
  can_save: boolean;
  reason: string | null;
};

export type ImportSummary = {
  rows: number; kept: number; removed: number; bad_dates: number; edited: number;
  too_long: number;
  long_fields: { field: string; limit: number; rows: number }[];
  /** The most characters each text field holds — the grid marks a longer value. */
  limits: Record<string, number>;
  period: { from: string; to: string } | null;
  dates: ImportDates[];
  /** "All vendors": "<Supplier Name>|GDS" → lines. */
  suppliers: { group: string; count: number }[];
  duplicates: ImportDuplicates;
};

export type ImportResult = {
  batch_id: string; created_count: number; no_vendor: number;
  duplicates: Omit<ImportDuplicates, "rows" | "can_save" | "reason"> | null;
};

export type ImportJob = {
  import_id: string;
  status: ImportStatus;
  phase: ImportPhase;
  total_rows: number;
  processed_rows: number;
  error: string | null;
  file_name: string;
  sheet_name: string | null;
  header_row: number | null;
  batch_id: string | null;
  result: ImportResult | null;
  read: {
    warnings?: string[];
    date_fix?: TicketExtractionPreview["date_fix"];
    /** The ticket fields the file filled — the review grid's columns. */
    filled?: string[];
  };
  /** Seconds the job has waited for a worker to pick it up. */
  queued_for: number;
  /** Under review only. */
  summary?: ImportSummary;
};

export type ImportRow = {
  row_no: number; data: TicketRow; duplicate_of: string | null;
  bad_date: boolean; too_long: boolean; excluded: boolean; edited: boolean;
};

/** The review's tabs (backend internal_import.VIEWS). */
export type ImportView = "all" | "duplicates" | "dates" | "long" | "edited" | "removed";

export type ImportPage = { total: number; page: number; size: number; rows: ImportRow[] };

export type ImportSaveBody = {
  statement_name: string | null;
  statement_category?: string | null;
  agency?: string | null;
  customer_type?: string | null;
  customer_agency_id?: number | null;
  corporate_id?: number | null;
  customer_id?: number | null;
  multi_vendor?: boolean;
  /** "All vendors": supplier group → "agency:<id>" | "airline" | "". */
  vendor_picks?: Record<string, string>;
};

/** A row edit: `values` sets fields (blank clears one); `excluded` removes or puts back. */
export type ImportEdit = { values?: Record<string, string | number | null>; excluded?: boolean };

export function importApi(apiBase: string) {
  const base = `${apiBase}/imports`;
  return {
    create: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (await api.post<ImportHead>(base, form)).data;
    },
    reread: async (id: string, sheet: string | null, headerRow: number | null) =>
      (await api.post<ImportHead>(`${base}/${id}/read`, { sheet_name: sheet, header_row: headerRow })).data,
    parse: async (id: string, columnMap: Record<string, string>, dateFormats: Record<string, string> | null) =>
      (await api.post<ImportJob>(`${base}/${id}/parse`, { column_map: columnMap, date_formats: dateFormats })).data,
    get: async (id: string) => (await api.get<ImportJob>(`${base}/${id}`)).data,
    /** As `get`; "All vendors": duplicates counted among the lines of the suppliers in `groups`. */
    summary: async (id: string, groups: string[] | null) =>
      (await api.post<ImportJob>(`${base}/${id}/summary`, { groups })).data,
    rows: async (id: string, params: { view: ImportView; q: string; page: number; size: number }) =>
      (await api.get<ImportPage>(`${base}/${id}/rows`, { params })).data,
    edit: async (id: string, rowNo: number, body: ImportEdit) =>
      (await api.patch<ImportRow>(`${base}/${id}/rows/${rowNo}`, body)).data,
    bulk: async (id: string, rowNos: number[], body: ImportEdit) =>
      (await api.post<{ rows: ImportRow[] }>(`${base}/${id}/rows/bulk`, { row_nos: rowNos, ...body })).data.rows,
    addRow: async (id: string) => (await api.post<ImportRow>(`${base}/${id}/rows`)).data,
    save: async (id: string, body: ImportSaveBody) => (await api.post<ImportJob>(`${base}/${id}/save`, body)).data,
    discard: async (id: string) => { await api.delete(`${base}/${id}`); },
  };
}

/** Where the worker is, in words. */
export function importPhaseText(job: ImportJob): string {
  const n = (v: number) => v.toLocaleString("en-IN");
  if (job.phase === "queued") return job.status === "saving" ? "Waiting to save…" : "Waiting to read the file…";
  if (job.phase === "reading") return "Reading the file…";
  if (job.phase === "checking") {
    return job.status === "saving" ? "Checking for tickets already loaded…" : "Checking for duplicates…";
  }
  if (job.phase === "writing") return `Preparing the review — ${n(job.processed_rows)} of ${n(job.total_rows)} rows`;
  if (job.phase === "saving") return `Saving tickets — ${n(job.processed_rows)} of ${n(job.total_rows)}`;
  return job.status === "saving" ? "Saving…" : "Reading…";
}

/** 0–100 once the worker can count, else null (a bar that only moves). */
export function importProgress(job: ImportJob): number | null {
  if ((job.phase === "writing" || job.phase === "saving") && job.total_rows > 0) {
    return Math.min(100, Math.round((job.processed_rows / job.total_rows) * 100));
  }
  return null;
}
