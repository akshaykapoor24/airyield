"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Calendar, ChevronDown, FilePlus, Layers, Lock, Search, Tag, X } from "lucide-react";
import { AIRLINE_AGENCIES, type StatementType } from "@/lib/ticketFields";
import api from "@/lib/api";
import { agencyLabel, type AgencyRow } from "@/lib/counterparty";
import { partyName, type Party } from "@/lib/party";
import { CUSTOMER_TYPES, CUSTOMER_TYPE_LABEL, CUSTOMER_TYPE_MASTER, type CustomerTag } from "@/lib/customerType";

export type StatementOption = {
  batch_id:       string;
  statement_name: string | null;
  statement_type: StatementType;
  agency:         string;
  valid_from:     string;
  valid_to:       string;
  ticket_count:   number;
  file_name:      string;
};

export const NEW_STATEMENT = "__new__";

const LABEL = "block text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1";

function fmt(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function TypePill({ type }: { type: StatementType }) {
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 ${
      type === "AIRLINE" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>
      {type}
    </span>
  );
}

/**
 * One field for the whole filing decision: type a name and the ticket starts a
 * new statement; pick a row and it joins that one.
 *
 * Typing always means "new" — selecting an existing statement is an explicit
 * click. That keeps the two outcomes predictable instead of guessing from a
 * name collision, and the mode pill above the input says which is active.
 */
function StatementNameCombo({
  name, target, options, onPickExisting, onTypeName,
}: {
  name: string;
  target: string;
  options: StatementOption[];
  onPickExisting: (o: StatementOption) => void;
  onTypeName: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // Typing filters the list; the chevron browses everything. Without this a user
  // who typed a new name could never reach the existing statements below it.
  const [browseAll, setBrowseAll] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const isNew = target === NEW_STATEMENT;
  // While an existing statement is selected the box shows its name, so filtering
  // on that text would hide every other option. Only free text filters.
  const q = isNew && !browseAll ? name.trim().toLowerCase() : "";
  const filtered = q
    ? options.filter((o) =>
        (o.statement_name ?? "").toLowerCase().includes(q) ||
        o.agency.toLowerCase().includes(q))
    : options;

  return (
    <div ref={ref}>
      <div className="flex items-center gap-2 mb-1">
        <label className={LABEL + " mb-0"}>
          <Tag className="w-3 h-3 inline mr-1" />
          Statement Name
        </label>
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold ${
          isNew ? "bg-emerald-50 text-emerald-700" : "bg-blue-50 text-blue-700"}`}>
          {isNew ? <><FilePlus className="w-2.5 h-2.5" /> NEW</>
                 : <><Layers className="w-2.5 h-2.5" /> EXISTING</>}
        </span>
      </div>

      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={name}
          maxLength={500}
          placeholder="Type a new name, or pick an existing statement…"
          onChange={(e) => { setBrowseAll(false); onTypeName(e.target.value); }}
          onFocus={() => setOpen(true)}
          className="w-full border border-gray-200 bg-white rounded-lg pl-3 pr-16 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
          {name && (
            <button
              type="button"
              title="Clear"
              onClick={() => { setBrowseAll(false); onTypeName(""); inputRef.current?.focus(); }}
              className="p-1 rounded hover:bg-gray-100 text-gray-400"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            type="button"
            title="Browse statements"
            onClick={() => { setBrowseAll(true); setOpen((o) => !o); inputRef.current?.focus(); }}
            className="p-1 rounded hover:bg-gray-100 text-gray-400"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>

        {open && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 min-w-[340px] bg-white border border-gray-200 rounded-lg shadow-xl">
            {isNew && (
              <div className="px-3 py-2.5 border-b border-gray-100 flex items-center gap-2 text-sm">
                <FilePlus className="w-4 h-4 shrink-0 text-emerald-600" />
                {name.trim() ? (
                  <span className="text-gray-700 truncate">
                    Creates <span className="font-semibold text-[#1e3a5f]">{name.trim()}</span>
                  </span>
                ) : (
                  <span className="text-gray-400">Type a name, or leave blank for an auto name</span>
                )}
              </div>
            )}

            <p className="px-3 pt-2 pb-1 text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              {q ? "Matching statements" : "Add to an existing statement"}
            </p>

            <ul className="max-h-72 overflow-y-auto pb-1">
              {options.length === 0 ? (
                <li className="px-3 py-3 text-xs text-gray-400 italic">
                  No statements yet — this ticket will start the first one.
                </li>
              ) : filtered.length === 0 ? (
                <li className="px-3 py-3 text-xs text-gray-400 italic">
                  No statement matches “{name.trim()}” — saving creates a new one.{" "}
                  <button
                    type="button"
                    onClick={() => setBrowseAll(true)}
                    className="not-italic text-blue-600 hover:underline font-medium"
                  >
                    Show all
                  </button>
                </li>
              ) : filtered.map((o) => (
                <li key={o.batch_id}>
                  <button
                    type="button"
                    onClick={() => { onPickExisting(o); setOpen(false); }}
                    className={`w-full text-left px-3 py-2 hover:bg-blue-50 border-l-2 ${
                      o.batch_id === target ? "bg-blue-50 border-blue-500" : "border-transparent"}`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <TypePill type={o.statement_type} />
                      <span className="text-xs font-semibold text-gray-800 truncate">
                        {o.statement_name || o.agency}
                      </span>
                      <span className="ml-auto text-[10px] text-gray-500 bg-gray-100 rounded-full px-1.5 py-0.5 shrink-0">
                        {plural(o.ticket_count, "ticket")}
                      </span>
                    </span>
                    <span className="block mt-0.5 pl-9 text-[10px] text-gray-400 truncate">
                      {o.agency} · {fmt(o.valid_from)} – {fmt(o.valid_to)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}



/** Searchable agency select for the new-statement case. */
/** Picks the party for the chosen customer type. Reuses AgencySelect's shell so
 *  the filing row keeps one visual language; only the list and the label change.
 *  A direct customer is never marked invalid — a walk-in may have no record. */
function CustomerPartySelect({
  tag, setTag, touched,
}: {
  tag: CustomerTag; setTag: (t: CustomerTag) => void; touched: boolean;
}) {
  const [agencies,   setAgencies]   = useState<AgencyRow[]>([]);
  const [corporates, setCorporates] = useState<Party[]>([]);
  const [customers,  setCustomers]  = useState<Party[]>([]);
  const [loaded,     setLoaded]     = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, c, d] = await Promise.allSettled([
        api.get<AgencyRow[]>("/agencies/", { params: { limit: 1000 } }),
        api.get<Party[]>("/corporates/", { params: { limit: 1000 } }),
        api.get<Party[]>("/customers/", { params: { limit: 1000 } }),
      ]);
      if (cancelled) return;
      // Neither endpoint filters is_active by default.
      if (a.status === "fulfilled") setAgencies(a.value.data.filter(x => x.is_active));
      if (c.status === "fulfilled") setCorporates(c.value.data.filter(x => x.is_active));
      if (d.status === "fulfilled") setCustomers(d.value.data.filter(x => x.is_active));
      setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  const kind = tag.customerType;
  const label = kind === "agency" ? "Agency" : kind === "corporate" ? "Corporate" : "Customer";
  const options =
      kind === "agency"    ? agencies.map(agencyLabel)
    : kind === "corporate" ? corporates.map(corpLabel)
    : kind === "direct"    ? customers.map(partyName)
    : [];

  const current =
      kind === "agency"    ? (agencies.find(a => a.id === tag.agencyId)    ? agencyLabel(agencies.find(a => a.id === tag.agencyId)!) : "")
    : kind === "corporate" ? (corporates.find(c => c.id === tag.corporateId) ? corpLabel(corporates.find(c => c.id === tag.corporateId)!) : "")
    : kind === "direct"    ? (customers.find(c => c.id === tag.customerId)  ? partyName(customers.find(c => c.id === tag.customerId)!)  : tag.partyName)
    : "";

  const pick = (v: string) => {
    if (kind === "agency") {
      const a = agencies.find(x => agencyLabel(x) === v);
      setTag({ ...tag, agencyId: a?.id ?? null, partyName: a?.name ?? v });
    } else if (kind === "corporate") {
      const c = corporates.find(x => corpLabel(x) === v);
      setTag({ ...tag, corporateId: c?.id ?? null, partyName: c ? ((c.company || "").trim() || partyName(c)) : v });
    } else {
      const c = customers.find(x => partyName(x) === v);
      setTag({ ...tag, customerId: c?.id ?? null, partyName: v });
    }
  };

  if (!kind) {
    return (
      <div>
        <label className={LABEL}><Building2 className="w-3 h-3 inline mr-1" /> Customer</label>
        <div className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-400 bg-gray-50">
          Pick a customer type first
        </div>
      </div>
    );
  }

  if (loaded && options.length === 0) {
    return (
      <div>
        <label className={LABEL}><Building2 className="w-3 h-3 inline mr-1" /> {label}</label>
        <div className="w-full border border-amber-200 bg-amber-50 rounded-lg px-3 py-2 text-[11px] text-amber-800">
          None yet — add them in{" "}
          <a href={CUSTOMER_TYPE_MASTER[kind].href} className="font-semibold underline">
            {CUSTOMER_TYPE_MASTER[kind].label}
          </a>
          {kind === "direct" && "; or leave blank for a walk-in"}
        </div>
      </div>
    );
  }

  return (
    <AgencySelect
      agency={current}
      setAgency={pick}
      options={options}
      // A walk-in legitimately has no record, so Direct never shows as invalid.
      invalid={touched && kind !== "direct" && !current}
      label={label}
      placeholder={loaded ? "— select —" : "loading…"}
    />
  );
}

function corpLabel(c: Party): string {
  const n = partyName(c);
  return c.company ? `${c.company} — ${n}` : n;
}

function AgencySelect({
  agency, setAgency, options, invalid,
  label = "Agency", placeholder = "— select —",
}: {
  agency: string; setAgency: (v: string) => void; options: string[]; invalid?: boolean;
  label?: string; placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // The supplier master holds one row per branch, so a name repeats — "Riya
  // Travel" comes back 14 times. This control stores the NAME, so those rows are
  // indistinguishable once picked: listing them all is noise, and a name-keyed
  // list would collide. Collapse to distinct names, first occurrence wins.
  const unique = useMemo(() => [...new Set(options)], [options]);
  const filtered = unique.filter((a) => a.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div ref={ref}>
      <label className={LABEL}>
        <Building2 className="w-3 h-3 inline mr-1" />
        {label} <span className="text-red-500">*</span>
      </label>
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={`w-full border rounded-lg px-3 py-2 text-sm text-left flex items-center justify-between pr-8 focus:outline-none focus:ring-2 focus:ring-blue-400 ${
            invalid ? "border-red-300 bg-red-50" : "border-gray-200 bg-white"}`}
        >
          <span className={agency ? "text-gray-800 truncate" : "text-gray-400"}>
            {agency || placeholder}
          </span>
          <ChevronDown className="w-4 h-4 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </button>
        {open && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 min-w-[240px] bg-white border border-gray-200 rounded-lg shadow-xl">
            <div className="p-2 border-b border-gray-100">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search agency…"
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
                />
              </div>
            </div>
            <ul className="max-h-56 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-2 text-xs text-gray-400 italic">No agencies found</li>
              ) : filtered.map((a) => (
                <li key={a}>
                  <button
                    type="button"
                    onClick={() => { setAgency(a); setOpen(false); setQuery(""); }}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-blue-50 ${
                      a === agency ? "bg-blue-50 text-blue-700 font-semibold" : "text-gray-700"}`}
                  >
                    {a}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Where the punched ticket goes, and — for a new statement — the metadata it needs.
 *
 * Filing into an existing statement inherits its type, agency and validity from
 * the server side, so those inputs give way to a read-only summary. That is not
 * just cosmetic: the append endpoint takes the statement's own type, so an
 * editable control here would be a lie.
 */
export default function TicketFilingCard({
  target, setTarget, statements,
  ticketType, setTicketType,
  agency, setAgency, agencyOptions,
  statementName, setStatementName,
  validFrom, setValidFrom, validTo, setValidTo,
  touched,
  // Customer mode (Customer data → Statement → Create Ticket). Swaps the vendor
  // pair — Ticket Type B2B|AIRLINE plus the vendor agency — for the CUSTOMER
  // pair: who the ticket was sold to. Everything else about filing is unchanged,
  // including the ability to punch this ticket into a statement that already
  // exists rather than spawning a one-ticket statement for it.
  customerMode = false, tag, setTag,
}: {
  target: string; setTarget: (v: string) => void;
  statements: StatementOption[];
  ticketType: StatementType; setTicketType: (v: StatementType) => void;
  agency: string; setAgency: (v: string) => void; agencyOptions: string[];
  statementName: string; setStatementName: (v: string) => void;
  validFrom: string; setValidFrom: (v: string) => void;
  validTo: string; setValidTo: (v: string) => void;
  touched: boolean;
  customerMode?: boolean;
  tag?: CustomerTag;
  setTag?: (t: CustomerTag) => void;
}) {
  const isNew = target === NEW_STATEMENT;
  const selected = statements.find((s) => s.batch_id === target);
  // Mirrors the server's fallback so the placeholder shows the name that will
  // actually be saved when the field is left blank.
  // Mirrors the server's fallback, so the hint shows the name that will actually
  // be saved. In customer mode the server derives it from the CUSTOMER.
  const derivedName = customerMode
    ? (tag?.partyName && validFrom
        ? `${CUSTOMER_TYPE_LABEL[tag.customerType ?? "direct"]} - ${tag.partyName} - ${validFrom}` : "")
    : (agency && validFrom ? `${ticketType} - ${agency} - ${validFrom}` : "");
  const dateError = touched && validFrom && validTo && validTo < validFrom;
  const dateCls = (v: string, bad?: boolean) =>
    `w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
      bad || (touched && !v) ? "border-red-300 bg-red-50" : "border-gray-200 bg-white"}`;

  return (
    // No overflow-hidden: the pickers inside open as absolute panels and would be
    // clipped by it. The header rounds its own top corners instead.
    <div className="bg-white border border-gray-200 rounded-xl relative z-20">
      <div className="px-5 py-3 border-b border-gray-100 rounded-t-xl flex items-center gap-2.5" style={{ background: "#1e3a5f" }}>
        <Layers className="w-4 h-4 text-white/80" />
        <div>
          <h2 className="text-sm font-semibold text-white">Filing</h2>
          <p className="text-[11px] text-white/60">
            {customerMode
              // This is one hand-punched ticket, not a statement — but it still
              // has to land in one, so the row below either starts a new
              // statement or files it into an existing one.
              ? "Who you sold this ticket to, and which statement it lands in"
              : "Which statement this ticket belongs to"}
          </p>
        </div>
      </div>

      <div className="px-5 py-4">
        {/* One row: the name combo decides new-vs-existing, and the rest of the
            statement metadata only applies when it is new. */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 items-start">
          <div className="xl:col-span-2">
            <StatementNameCombo
              name={statementName}
              target={target}
              options={statements}
              onPickExisting={(o) => {
                setTarget(o.batch_id);
                setStatementName(o.statement_name || o.agency);
              }}
              onTypeName={(v) => { setTarget(NEW_STATEMENT); setStatementName(v); }}
            />
            {isNew && !statementName.trim() && (
              <p className="text-[10px] text-gray-400 mt-1 truncate">
                {derivedName
                  ? `Blank → “${derivedName}”.`
                  : customerMode
                    ? "Blank → named from the customer type, customer and start date."
                    : "Blank → named from type, agency and start date."}
              </p>
            )}
          </div>

          {isNew ? (
            <>
              <div>
                <label className={LABEL}>
                  {customerMode ? "Customer Type" : "Ticket Type"} <span className="text-red-500">*</span>
                </label>
                {customerMode && tag && setTag ? (
                  <div className="flex rounded-lg border border-gray-200 overflow-hidden text-[11px] font-medium">
                    {CUSTOMER_TYPES.map((t) => (
                      <button
                        key={t.key}
                        type="button"
                        // Changing the type invalidates every id under it.
                        onClick={() => setTag({
                          customerType: t.key, agencyId: null, corporateId: null,
                          customerId: null, partyName: "",
                        })}
                        className={`flex-1 py-2 px-1 leading-tight transition-colors border-r border-gray-200 last:border-r-0 ${
                          tag.customerType === t.key
                            ? "bg-[#1e3a5f] text-white"
                            : "bg-white text-gray-600 hover:bg-gray-50"}`}
                      >
                        {t.short}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm font-medium">
                    {(["B2B", "AIRLINE"] as StatementType[]).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setTicketType(t)}
                        className={`flex-1 py-2 transition-colors ${
                          ticketType === t
                            ? "bg-[#1e3a5f] text-white"
                            : "bg-white text-gray-600 hover:bg-gray-50"}`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                {customerMode && tag && setTag ? (
                  <CustomerPartySelect tag={tag} setTag={setTag} touched={touched} />
                ) : (
                  <AgencySelect
                    agency={agency}
                    setAgency={setAgency}
                    options={ticketType === "AIRLINE" ? [...AIRLINE_AGENCIES] : agencyOptions}
                    invalid={touched && !agency}
                  />
                )}
              </div>

              {/* Each date gets its own grid cell — a nested 2-up split leaves the
                  native date input too narrow for "dd-mm-yyyy" plus its picker. */}
              <div>
                <label className={LABEL}>
                  <Calendar className="w-3 h-3 inline mr-1" />
                  Valid From <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={validFrom}
                  onChange={(e) => setValidFrom(e.target.value)}
                  onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
                  className={dateCls(validFrom)}
                />
              </div>
              <div>
                <label className={LABEL}>
                  <Calendar className="w-3 h-3 inline mr-1" />
                  Valid To <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={validTo}
                  min={validFrom || undefined}
                  onChange={(e) => setValidTo(e.target.value)}
                  onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
                  className={dateCls(validTo, !!dateError)}
                />
              </div>
            </>
          ) : (
            <div className="xl:col-span-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                ["Ticket Type", selected?.statement_type ?? "—"],
                ["Agency", selected?.agency ?? "—"],
                ["Valid From", fmt(selected?.valid_from ?? "")],
                ["Valid To", fmt(selected?.valid_to ?? "")],
              ].map(([label, value]) => (
                <div key={label}>
                  <label className={LABEL}>{label}</label>
                  <p className="px-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-sm text-gray-700 truncate">
                    {value}
                  </p>
                </div>
              ))}
              <p className="col-span-2 sm:col-span-4 flex items-center gap-1.5 text-[11px] text-gray-400">
                <Lock className="w-3 h-3" />
                Inherited from the statement — the ticket is filed under its type, agency and validity.
              </p>
            </div>
          )}
        </div>

        {dateError && (
          <p className="text-[11px] text-red-500 mt-2">Valid to must be on or after valid from</p>
        )}
      </div>
    </div>
  );
}
