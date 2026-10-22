// The statement period a Third Party GDS upload declares (backend services/statement_period.py)
// — shown on the upload wizard, in the "already uploaded" question and on the uploads list.
//
// Periods travel as YYYY-MM-DD strings and are read WITHOUT a timezone round trip, so
// "2026-08-01" can never show as 31 Jul. Upload times are the server's UTC without a zone
// and go through `parseServerTime`, so they show in the viewer's own time.

import { parseServerTime } from "@/lib/reportDownload";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(value: string | null | undefined): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

const dd = (n: number) => String(n).padStart(2, "0");

/** "01–07 Aug 2026", "28 Jul – 03 Aug 2026", "28 Dec 2025 – 03 Jan 2026"; "—" when unset.
 *  The same wording the API uses for `period_label`. */
export function formatPeriod(from: string | null | undefined, to: string | null | undefined): string {
  const a = parts(from), b = parts(to);
  if (!a || !b) return "—";
  const [ay, am, ad] = a, [by, bm, bd] = b;
  if (ay === by && am === bm) return `${dd(ad)}–${dd(bd)} ${MONTHS[bm - 1]} ${by}`;
  if (ay === by) return `${dd(ad)} ${MONTHS[am - 1]} – ${dd(bd)} ${MONTHS[bm - 1]} ${by}`;
  return `${dd(ad)} ${MONTHS[am - 1]} ${ay} – ${dd(bd)} ${MONTHS[bm - 1]} ${by}`;
}

/** "01 Aug 2026" for one YYYY-MM-DD day; "—" when unset or not a date. */
export function formatDay(value: string | null | undefined): string {
  const p = parts(value);
  return p ? `${dd(p[2])} ${MONTHS[p[1] - 1]} ${p[0]}` : "—";
}

/** When an upload was made, in the viewer's own time — the uploads list's wording. */
export function formatUploadedAt(value: string | null | undefined): string {
  if (!value) return "—";
  const d = parseServerTime(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

/** The same moment as a date and a time, for a table cell that shows them on two lines. */
export function uploadedAtParts(value: string | null | undefined): { date: string; time: string } | null {
  if (!value) return null;
  const d = parseServerTime(value);
  return Number.isNaN(d.getTime()) ? null : { date: d.toLocaleDateString(), time: d.toLocaleTimeString() };
}
