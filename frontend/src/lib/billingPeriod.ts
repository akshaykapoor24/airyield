// The default period a new invoice is raised for, read off the tickets on it.
//
// Same logic as the copies inside customers/[id]/page.tsx and corporates/[id]/page.tsx,
// shared here for Agency Invoicing (billing/agency/[id]/page.tsx).

/**
 * A ticket's date as `YYYY-MM-DD`, or "" when it cannot be read.
 *
 * `ticket_date` is a String(50) carried straight from whatever spreadsheet the ticket
 * arrived on, so it is not reliably a date at all. This mirrors
 * backend/app/services/billing_calc.py::safe_date, which is the function that decides
 * which tickets a date filter keeps.
 *
 * NEVER FALL BACK TO `new Date(s)`. JavaScript reads "03/04/2026" as 4 March, the US
 * month-first order; the backend reads the same string as 3 April (day-first). This value
 * ends up as the period printed on an invoice, so anything that does not match the
 * explicit patterns below is "".
 */
export function ticketDateISO(raw: string | null): string {
  if (!raw) return "";
  const s = raw.trim();
  if (!s) return "";

  // A real calendar date, or "". Date.parse is no use as a validator here: it happily
  // rolls 2026-02-31 over into 3 March, so the parts are checked back out of the Date.
  const build = (y: number, mo: number, d: number): string => {
    if (!(y >= 1900 && y <= 2999) || mo < 1 || mo > 12 || d < 1 || d > 31) return "";
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return "";
    return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  };

  // Year-first: the ISO prefix every LCC-projected row carries, and the slash variant.
  const ymd = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/.exec(s);
  if (ymd) return build(Number(ymd[1]), Number(ymd[2]), Number(ymd[3]));

  // Day-first d/m/y, matching the backend. Two-digit years are 20xx.
  const dmy = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/.exec(s);
  if (dmy) {
    const year = dmy[3].length === 2 ? 2000 + Number(dmy[3]) : Number(dmy[3]);
    return build(year, Number(dmy[2]), Number(dmy[1]));
  }
  return "";
}

/**
 * The span the selected tickets actually cover — the truest period for their bill.
 * Plain string comparison is correct because every value is `YYYY-MM-DD`; no Date
 * objects, so no timezone can shift a boundary.
 */
export function periodFromTickets(
  rows: { ticket_date: string | null }[],
): { from: string; to: string; undated: number } {
  const dates = rows.map((t) => ticketDateISO(t.ticket_date)).filter(Boolean).sort();
  return {
    from: dates[0] ?? "",
    to: dates[dates.length - 1] ?? "",
    undated: rows.length - dates.length,
  };
}
