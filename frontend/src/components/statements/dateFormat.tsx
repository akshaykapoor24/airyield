"use client";

// The declared date format — one question, asked the same way on Vendors → Statements (Third
// Party GDS, StatementUploadWizard) and Internal Statement (tickets/upload).
//
// A sheet writes "05/08/2026" as 5 Aug or 8 May depending on who made it, so the upload asks
// how each date column is written. The backend reads text dates in that order and no other,
// and puts the dates Excel stored with day and month swapped back in it, row by row against
// the statement period (services/excel_dates.py). The answer is filled in from what the file
// itself shows (`/detect-date-formats`, services/date_format_detect.py), else from the
// party's last upload — and a choice the user makes is never filled in over (`useDateFormats`).

import { useMemo, useState } from "react";
import { CalendarDays, Loader2 } from "lucide-react";
import { formatDay } from "@/lib/statementPeriod";

/** The order a date column is written in — the backend's flat_statement.DATE_ORDERS. */
export type DateOrder = "DMY" | "MDY" | "YMD";
export type DateField = { field: string; header: string };
export type DateFormats = Record<string, DateOrder>;

export const DATE_ORDERS: { value: DateOrder; label: string; example: string }[] = [
  { value: "DMY", label: "DD-MM-YYYY", example: "05/08/2026 is 05 Aug 2026" },
  { value: "MDY", label: "MM-DD-YYYY", example: "05/08/2026 is 08 May 2026" },
  { value: "YMD", label: "YYYY-MM-DD", example: "2026/08/05 is 05 Aug 2026" },
];
export const orderLabel = (o: DateOrder | null | undefined) =>
  DATE_ORDERS.find((d) => d.value === o)?.label ?? "—";

/** `/detect-date-formats`: the order one date column is written in, as far as the file shows
 *  it (backend services/date_format_detect.py). */
export type DetectedFormat = DateField & {
  column: string | null;               // the file column read; null when none was recognised
  order: DateOrder | null;             // null: the file does not settle it
  votes: Record<DateOrder, number>;    // written dates that fit only that order
  swapped: number;                     // Excel dates that fit the period only read day-first
  text_dates: number;                  // dates written as text
  example: { value: string; read: string } | null;
};

/** How one declared date column read in the format chosen for it — `/save-preview`'s `dates`
 *  on Third Party GDS, counted off the extracted rows on Internal Statement. */
export type DatesRead = DateField & {
  format: DateOrder | null;
  mapped: boolean;
  read: number;
  first: string | null;
  last: string | null;
  unreadable: number;
  cells: { index: number; value: string | null }[];   // the cells that did not fit
};

/** Why the file reads as its detected order, in a phrase. */
export function detectionEvidence(d: DetectedFormat): string {
  const parts: string[] = [];
  const n = d.order ? d.votes[d.order] : 0;
  if (n) {
    parts.push(`${n.toLocaleString("en-IN")} of its written dates fit only this way`
      + (d.example ? ` ("${d.example.value}" is ${formatDay(d.example.read)})` : ""));
  }
  if (d.order === "DMY" && d.swapped) {
    parts.push(`${d.swapped.toLocaleString("en-IN")} Excel date${d.swapped === 1 ? "" : "s"} fall in the `
      + "statement period only read day-first");
  }
  return parts.join("; ");
}

/** "4 fit DD-MM-YYYY, 3 fit MM-DD-YYYY" — the votes of a file that does not settle it. */
export function votesText(d: DetectedFormat): string {
  const parts = DATE_ORDERS.filter((o) => d.votes[o.value] > 0).map((o) => `${d.votes[o.value]} fit ${o.label}`);
  return parts.length ? parts.join(", ") : "its dates read the same every way";
}

/** One date column's written order — three choices, all visible at once. */
export function DateOrderPicker({ label, value, onChange }: {
  label: string; value: DateOrder | undefined; onChange: (o: DateOrder) => void;
}) {
  return (
    <div role="radiogroup" aria-label={`${label} date format`}
      className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
      {DATE_ORDERS.map((o) => {
        const on = value === o.value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`px-2.5 py-1 rounded-md text-[11px] font-semibold tabular-nums transition-colors ${
              on ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export type FormatNote = { tone: "ok" | "info" | "warn"; text: string };

/** Whose dates these are, in the notes: "this agency's last upload", "this vendor". */
export type FormatWords = { lastUpload: string; who: string };

/**
 * The format of each declared date column: what the user chose, else what the file shows
 * (`detected`), else the party's last upload's (`last`), else — when every date in the
 * column is a real Excel date, which the format cannot change — DD-MM-YYYY, said so.
 * Anything else is left for the user to choose.
 */
export function useDateFormats(fields: DateField[], detected: Record<string, DetectedFormat> | null,
  last: Partial<DateFormats> | null, detecting: boolean, words: FormatWords) {
  const [chosen, setChosen] = useState<DateFormats>({});

  const auto = useMemo(() => {
    const out: Record<string, { order: DateOrder; source: "file" | "last" | "moot" }> = {};
    for (const f of fields) {
      const d = detected?.[f.field];
      const prev = last?.[f.field];
      if (d?.order) out[f.field] = { order: d.order, source: "file" };
      else if (prev && DATE_ORDERS.some((o) => o.value === prev)) out[f.field] = { order: prev, source: "last" };
      else if (d?.column && d.text_dates === 0) out[f.field] = { order: "DMY", source: "moot" };
    }
    return out;
  }, [fields, detected, last]);

  const formats = useMemo(() => {
    const out: DateFormats = {};
    for (const f of fields) {
      const o = chosen[f.field] ?? auto[f.field]?.order;
      if (o) out[f.field] = o;
    }
    return out;
  }, [fields, chosen, auto]);

  const missing = fields.filter((f) => !formats[f.field]);
  /** Every format filled in, none by hand — what lets an upload start on its own. */
  const isAuto = fields.length > 0 && fields.every((f) => !chosen[f.field] && !!auto[f.field]);

  /** A format the user chose. A column with no answer at all takes it too — a sheet usually
   *  writes every date the same way — and stays one click from changing. */
  const choose = (field: string, order: DateOrder) =>
    setChosen((p) => {
      const n: DateFormats = { ...p, [field]: order };
      for (const f of fields) if (!n[f.field] && !auto[f.field]) n[f.field] = order;
      return n;
    });

  /** The line under a column's choice: where its value came from, and what the file says —
   *  including when the file disagrees with a format chosen by hand. */
  const note = (f: DateField): FormatNote | null => {
    const d = detected?.[f.field];
    const mine = chosen[f.field];
    if (mine) {
      return d?.order && d.order !== mine
        ? { tone: "warn", text: `This file reads as ${orderLabel(d.order)} — ${detectionEvidence(d)}. Check your choice.` }
        : null;
    }
    const prev = last?.[f.field];
    switch (auto[f.field]?.source) {
      case "file":
        return { tone: "ok", text: `Detected from the file — ${detectionEvidence(d!)}.`
          + (prev && prev !== d!.order ? ` ${words.lastUpload} used ${orderLabel(prev)}.` : "") };
      case "last":
        return { tone: "ok", text: `As in ${words.lastUpload.charAt(0).toLowerCase()}${words.lastUpload.slice(1)} — check it.`
          + (d?.column && d.text_dates === 0
            ? ` Every ${f.header} in this file is a real Excel date, so it doesn't change how this file reads.`
            : d && d.text_dates > 0 ? " The file itself doesn't settle it." : "") };
      case "moot":
        return { tone: "info", text: `Every ${f.header} in this file is a real Excel date, so the format doesn't `
          + `change how it reads — set it to how ${words.who} writes dates.` };
    }
    if (detecting) return { tone: "info", text: "Reading the file's dates…" };
    if (d?.text_dates) {
      return { tone: "warn", text: `The file doesn't settle it (${votesText(d)}) — choose how ${words.who} writes dates.` };
    }
    if (d && !d.column) {
      return { tone: "warn", text: `No ${f.header} column was recognised in the file — choose how ${words.who} writes dates.` };
    }
    return null;
  };

  return { formats, choose, note, missing, complete: missing.length === 0, isAuto, reset: () => setChosen({}) };
}

const NOTE_TONE: Record<FormatNote["tone"], string> = {
  ok: "text-emerald-600", warn: "text-amber-600", info: "text-slate-500",
};

/** The upload step's question: per date column, the three choices, how a date reads in the
 *  one chosen, and where the choice came from. `stacked` puts each column's name above its
 *  choices, for a narrow panel. */
export function DateFormatSection({ fields, formats, onChoose, note, detecting, stacked = false }: {
  fields: DateField[];
  formats: DateFormats;
  onChoose: (field: string, o: DateOrder) => void;
  note: (f: DateField) => FormatNote | null;
  detecting: boolean;
  stacked?: boolean;
}) {
  return (
    <>
      <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
        <CalendarDays className="w-3.5 h-3.5 text-slate-400" />
        Date format in your sheet <span className="text-red-500">*</span>
        {detecting && <Loader2 className="w-3 h-3 animate-spin text-slate-400" />}
      </p>
      <p className="text-[11px] text-slate-400 mt-0.5">
        Every sheet writes dates its own way — 05/08/2026 is 5 Aug in one and 8 May in another. It is
        read off the file where the file shows it; check it, or choose. Its dates are read that way and
        no other.
      </p>
      <div className="mt-2.5 space-y-2.5">
        {fields.map((f) => {
          const n = note(f);
          const example = formats[f.field]
            ? DATE_ORDERS.find((o) => o.value === formats[f.field])?.example
            : "not chosen yet";
          return (
            <div key={f.field}>
              {stacked ? (
                <>
                  <p className="text-[11px] font-medium text-slate-600 mb-1">{f.header}</p>
                  <DateOrderPicker label={f.header} value={formats[f.field]} onChange={(o) => onChoose(f.field, o)} />
                  <p className="text-[11px] text-slate-400 mt-1">{example}</p>
                </>
              ) : (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-[11px] font-medium text-slate-600 w-28 shrink-0">{f.header}</span>
                  <DateOrderPicker label={f.header} value={formats[f.field]} onChange={(o) => onChoose(f.field, o)} />
                  <span className="text-[11px] text-slate-400">{example}</span>
                </div>
              )}
              {n && <p className={`text-[11px] mt-1 ${stacked ? "" : "sm:ml-[7.75rem]"} ${NOTE_TONE[n.tone]}`}>{n.text}</p>}
            </div>
          );
        })}
      </div>
    </>
  );
}

/** Per declared column: how many dates read, from when to when, and how many didn't — the
 *  format changeable in place. */
export function DatesReadList({ dates, formats, onChange }: {
  dates: DatesRead[]; formats: DateFormats; onChange: (field: string, o: DateOrder) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
      {dates.map((d) => (
        <div key={d.field} className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-700">{d.header}</span>
          <DateOrderPicker label={d.header} value={formats[d.field]} onChange={(o) => onChange(d.field, o)} />
          <span className="text-slate-500">
            {!d.mapped ? "not mapped"
              : d.read === 0 ? "no dates read"
              : <>{d.read.toLocaleString("en-IN")} ·{" "}
                  <strong className="text-slate-700">
                    {d.first === d.last ? formatDay(d.first) : `${formatDay(d.first)} – ${formatDay(d.last)}`}
                  </strong></>}
            {d.unreadable > 0 && (
              <span className="text-orange-700"> · {d.unreadable.toLocaleString("en-IN")} not read</span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
