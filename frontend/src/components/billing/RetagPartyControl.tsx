"use client";

// Move a ticket to a different billing party, from the Sold Tickets tab.
//
// A ticket's bill-to party used to be decided once — at upload, or by the LCC
// resolver's name matching — and nothing could change it. That is the wrong
// number of chances: the resolver guesses from a passenger name, and an
// employee who booked personally must be invoiced direct, not through their
// employer. This is the correction.
//
// ONLY CUSTOMER AND CORPORATE. An agency claims tickets through its STATEMENT
// (the backend scopes on ticket_statements.agency_id, never the ticket's own
// customer_agency_id), so tagging a ticket to an agency would make it vanish
// from every screen rather than move. Deliberately not offered.
//
// A re-tagged ticket LEAVES the list you are looking at — that is the point, and
// it is why every success says where the ticket went.

import { useState, useEffect, useCallback, useMemo } from "react";
import { Loader2 } from "lucide-react";
import api from "@/lib/api";
import LccPartyPicker, { type PartyOption } from "@/components/statements/lcc/LccPartyPicker";

type Kind = "customer" | "corporate";
type Option = PartyOption<Kind>;

type CustomerRow = {
  id: number; first_name: string | null; last_name: string | null;
  company: string | null; corporate_id: number | null; is_active: boolean;
};
type CorporateRow = { id: number; company: string | null; is_active: boolean };

/** The corporate a person in Employee Master works for.
 *
 *  `customers.corporate_id` already records this, so a ticket naming an employee
 *  already implies who normally pays. Held per customer id so the Corporate
 *  column can offer "their employer" without asking the user to name it again. */
export type Employer = { id: number; name: string };

export type RetagResult = {
  updated: number;
  lcc_rows_updated: number;
  customer_type: string | null;
  party_name: string | null;
  untagged: boolean;
};

/** The parties a ticket can be moved to, loaded once per screen.
 *
 *  Exported so a page can hoist it above a table and share one fetch across
 *  every row instead of each control loading its own copy. */
export function usePartyOptions() {
  const [options, setOptions] = useState<Option[]>([]);
  const [employerOf, setEmployerOf] = useState<Map<number, Employer>>(new Map());
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [corp, cust] = await Promise.allSettled([
        api.get<CorporateRow[]>("/corporates/", { params: { limit: 1000 } }),
        api.get<CustomerRow[]>("/customers/", { params: { limit: 1000 } }),
      ]);
      if (cancelled) return;
      const out: Option[] = [];
      const corpName = new Map<number, string>();
      // Neither endpoint filters is_active; a retired party should not be offered.
      if (corp.status === "fulfilled") {
        for (const c of corp.value.data.filter(x => x.is_active)) {
          const label = c.company || `Corporate #${c.id}`;
          corpName.set(c.id, label);
          out.push({ value: c.id, label, sublabel: "Corporate", kind: "corporate" });
        }
      }
      const employers = new Map<number, Employer>();
      if (cust.status === "fulfilled") {
        for (const c of cust.value.data.filter(x => x.is_active)) {
          const name = `${c.first_name ?? ""} ${c.last_name ?? ""}`.trim() || `Customer #${c.id}`;
          out.push({ value: c.id, label: name, sublabel: c.company || "Direct customer", kind: "customer" });
          // An employer is offered even if the corporate row itself is inactive —
          // the ticket may already be billed to it, and hiding the option would
          // strand the row with no way back.
          if (c.corporate_id) {
            employers.set(c.id, {
              id: c.corporate_id,
              name: corpName.get(c.corporate_id) ?? c.company ?? "their corporate",
            });
          }
        }
      }
      setOptions(out);
      setEmployerOf(employers);
      setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  return { options, employerOf, loaded };
}

/** Send a re-tag. Throws the axios error so the caller can surface the detail. */
export async function retagTickets(
  ticketIds: number[], opt: Option | null,
): Promise<RetagResult> {
  // Mirrors lib/customerType.ts::buildTagPayload — exactly one id travels, and it
  // is the one matching the chosen type. The server re-derives this too; sending
  // it correctly just means the two never argue.
  const body = opt === null
    ? { ticket_ids: ticketIds, customer_type: null, customer_id: null, corporate_id: null }
    : opt.kind === "corporate"
      ? { ticket_ids: ticketIds, customer_type: "corporate", corporate_id: opt.value, customer_id: null }
      : { ticket_ids: ticketIds, customer_type: "direct", customer_id: opt.value, corporate_id: null };
  const { data } = await api.patch<RetagResult>("/tickets/billing-party", body);
  return data;
}

export default function RetagPartyControl({
  ticketIds, options, value, valueKind, disabled, disabledReason,
  size = "sm", allowClear = false, onDone, onError,
}: {
  ticketIds: number[];
  options: Option[];
  /** The party currently on the ticket, so the picker opens showing it. */
  value: number | null;
  valueKind?: Kind;
  disabled?: boolean;
  /** Shown as the control's tooltip when disabled — say WHY, not just that. */
  disabledReason?: string;
  size?: "sm" | "md";
  /** Offer "no party at all". Off by default: clearing re-arms passenger-name
   *  matching, which can make one ticket visible to several parties at once. */
  allowClear?: boolean;
  onDone: (r: RetagResult) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  const change = useCallback(async (opt: Option | null) => {
    if (busy || disabled || ticketIds.length === 0) return;
    setBusy(true);
    try {
      onDone(await retagTickets(ticketIds, opt));
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      onError(typeof d === "string" ? d : "Could not move these tickets.");
    } finally { setBusy(false); }
  }, [busy, disabled, ticketIds, onDone, onError]);

  if (busy) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" /> Moving…
      </span>
    );
  }

  return (
    <span title={disabled ? disabledReason : "Change who this ticket is billed to"}>
      <LccPartyPicker<Kind>
        size={size}
        options={options}
        value={value}
        valueKind={valueKind}
        disabled={disabled}
        allowClear={allowClear}
        onChange={change}
        placeholder="Bill to…"
        searchPlaceholder="Search customers and corporates…"
        emptyLabel="No customers or corporates yet — add them under User master."
      />
    </span>
  );
}

/** WHO PAYS: the passenger's employer, or the passenger directly.
 *
 *  Separate from the party picker because they are separate answers. Who flew is
 *  a fact about the ticket; who pays is a decision, and the same employee can be
 *  billed either way. `corporate_id` is what carries that decision — set, the
 *  ticket belongs to Corporate Billing; cleared, to Customer Billing. So flipping
 *  this moves the row off the screen you are on, which is why the caller refetches
 *  and says where it went.
 *
 *  Only ever a choice when the ticket names a person AND that person has an
 *  employer. Everything else states the position rather than offering one. */
export function RetagPayerControl({
  ticketId, customerId, corporateId, employerOf, disabled, disabledReason,
  onDone, onError,
}: {
  ticketId: number;
  customerId: number | null;
  corporateId: number | null;
  employerOf: Map<number, Employer>;
  disabled?: boolean;
  disabledReason?: string;
  onDone: (r: RetagResult) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const employer = customerId ? employerOf.get(customerId) : undefined;

  const change = useCallback(async (mode: "corporate" | "direct") => {
    if (busy || disabled || !customerId) return;
    setBusy(true);
    try {
      const body = mode === "corporate" && employer
        ? { ticket_ids: [ticketId], customer_type: "corporate", customer_id: customerId, corporate_id: employer.id }
        : { ticket_ids: [ticketId], customer_type: "direct", customer_id: customerId, corporate_id: null };
      const { data } = await api.patch<RetagResult>("/tickets/billing-party", body);
      onDone(data);
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      onError(typeof d === "string" ? d : "Could not change who this is billed to.");
    } finally { setBusy(false); }
  }, [busy, disabled, customerId, employer, ticketId, onDone, onError]);

  if (busy) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" /> Moving…
      </span>
    );
  }

  // Billed to a company with nobody named — there is no passenger to bill instead.
  if (!customerId) {
    return (
      <span className="text-[10px] text-gray-400">
        {corporateId ? "Billed to the company" : "—"}
      </span>
    );
  }

  if (!employer) {
    return (
      <span className="text-[10px] text-gray-400" title="This person has no corporate in Employee Master">
        Direct
      </span>
    );
  }

  return (
    <select
      value={corporateId ? "corporate" : "direct"}
      disabled={disabled}
      onChange={(e) => change(e.target.value as "corporate" | "direct")}
      title={disabled ? disabledReason
        : corporateId
          ? "The company pays — this ticket shows in Corporate Billing"
          : "The passenger pays — this ticket shows in Customer Billing"}
      className="w-full border border-gray-200 rounded-lg px-2 py-1 text-[11px] bg-white focus:outline-none focus:ring-1 focus:ring-sky-400 disabled:bg-gray-50 disabled:text-gray-400"
    >
      <option value="corporate">{employer.name}</option>
      <option value="direct">Direct</option>
    </select>
  );
}

/** The bulk bar shown above the table when rows are ticked. */
export function RetagBulkBar({
  count, options, busy, onApply,
}: {
  count: number;
  options: Option[];
  busy: boolean;
  onApply: (opt: Option) => void;
}) {
  const [pick, setPick] = useState<Option | null>(null);
  const label = useMemo(() => `${count} ticket${count === 1 ? "" : "s"} selected`, [count]);

  if (count === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-sky-200 bg-sky-50/60 px-3 py-2">
      <span className="text-[11px] font-semibold text-sky-900">{label}</span>
      <span className="text-[11px] text-sky-700">· move to</span>
      <div className="min-w-56">
        <LccPartyPicker<Kind>
          size="sm"
          options={options}
          value={pick?.value ?? null}
          valueKind={pick?.kind}
          allowClear={false}
          onChange={(o) => setPick(o)}
          placeholder="Pick a customer or corporate…"
        />
      </div>
      <button
        type="button"
        disabled={!pick || busy}
        onClick={() => pick && onApply(pick)}
        className="rounded-lg bg-sky-600 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
      >
        {busy ? "Moving…" : "Apply"}
      </button>
      <span className="text-[10px] text-sky-700/80">
        Already-billed rows are skipped.
      </span>
    </div>
  );
}
