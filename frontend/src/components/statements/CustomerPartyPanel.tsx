"use client";

// The statement-details panel for a CUSTOMER statement.
//
// Replaces the Internal Statement panel's "Statement Type: B2B | AIRLINE" toggle
// and its vendor-agency dropdown. That pair asks which SHAPE the file has and
// which vendor it came from — the buying side's questions. On the selling side
// the only question that matters is who the tickets were sold to, so this asks
// that instead, and the answer is what the commission run prices against.
//
// "Direct Customer" deliberately does not require picking anyone: a walk-in with
// no record in Employee Master is still neither an agency nor a corporate, and
// that alone is enough to match a common deal.

import { useEffect, useState } from "react";
import Link from "next/link";
import { Calendar, CheckCircle, FileText, Lock, Tag, Users } from "lucide-react";
import api from "@/lib/api";
import { agencyLabel, type AgencyRow } from "@/lib/counterparty";
import { corporateLabel, partyName, type Party } from "@/lib/party";
import { AgencyDropdown } from "@/components/tickets/StatementFormPanel";
import {
  CUSTOMER_TYPES, CUSTOMER_TYPE_MASTER, isTagComplete,
  type CustomerTag, type CustomerType,
} from "@/lib/customerType";

export default function CustomerPartyPanel({
  tag, setTag,
  statementName, setStatementName,
  validFrom, setValidFrom,
  validTo, setValidTo,
  touched, lockedReason,
}: {
  tag: CustomerTag; setTag: (t: CustomerTag) => void;
  statementName: string; setStatementName: (v: string) => void;
  validFrom: string; setValidFrom: (v: string) => void;
  validTo: string; setValidTo: (v: string) => void;
  touched: boolean;
  lockedReason?: string | null;
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
      // Neither endpoint filters is_active; a retired party should not be offered
      // for a new statement.
      if (a.status === "fulfilled") setAgencies(a.value.data.filter(x => x.is_active));
      if (c.status === "fulfilled") setCorporates(c.value.data.filter(x => x.is_active));
      if (d.status === "fulfilled") setCustomers(d.value.data.filter(x => x.is_active));
      setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  const locked = !!lockedReason;
  const complete = isTagComplete(tag) && validFrom !== "" && validTo !== "" && validTo >= validFrom;
  const fieldCls = (val: string) =>
    `w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
      touched && !val.trim() ? "border-red-300 bg-red-50" : "border-gray-200 bg-white"
    }`;
  const dateError = touched && validFrom && validTo && validTo < validFrom;

  // Agencies MUST be labelled name — branch · channel: one vendor is onboarded
  // once per branch AND once per channel, so a bare name shows duplicate options.
  const partyOptions =
    tag.customerType === "agency"    ? agencies.map(agencyLabel)
  : tag.customerType === "corporate" ? corporates.map(corporateLabel)
  : tag.customerType === "direct"    ? customers.map(partyName)
  : [];

  const pickParty = (label: string) => {
    if (tag.customerType === "agency") {
      const a = agencies.find(x => agencyLabel(x) === label);
      setTag({ ...tag, agencyId: a?.id ?? null, partyName: a?.name ?? label });
    } else if (tag.customerType === "corporate") {
      const c = corporates.find(x => corporateLabel(x) === label);
      setTag({ ...tag, corporateId: c?.id ?? null, partyName: c ? corpName(c) : label });
    } else {
      const c = customers.find(x => partyName(x) === label);
      setTag({ ...tag, customerId: c?.id ?? null, partyName: label });
    }
  };

  const currentLabel =
    tag.customerType === "agency"
      ? (agencies.find(a => a.id === tag.agencyId) ? agencyLabel(agencies.find(a => a.id === tag.agencyId)!) : "")
  : tag.customerType === "corporate"
      ? (corporates.find(c => c.id === tag.corporateId) ? corporateLabel(corporates.find(c => c.id === tag.corporateId)!) : "")
  : tag.customerType === "direct"
      ? (customers.find(c => c.id === tag.customerId) ? partyName(customers.find(c => c.id === tag.customerId)!) : tag.partyName)
      : "";

  const derivedName = tag.partyName && validFrom
    ? `${labelFor(tag.customerType)} - ${tag.partyName} - ${validFrom}` : "";

  const emptyMaster = loaded && tag.customerType && partyOptions.length === 0;

  return (
    <div className="bg-white border border-gray-200 rounded-xl h-fit sticky top-4">
      <div className="px-5 py-4 border-b border-gray-100 rounded-t-xl" style={{ background: "#1e3a5f" }}>
        <div className="flex items-center gap-2.5">
          <FileText className="w-4 h-4 text-white/80" />
          <h2 className="text-sm font-semibold text-white">Statement Details</h2>
        </div>
        <p className="text-xs text-white/60 mt-1">Who were these tickets sold to?</p>
      </div>

      <div className="px-5 py-5 space-y-4">
        {locked && (
          <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
            <Lock className="w-3.5 h-3.5 shrink-0 mt-px" />
            <span>{lockedReason}</span>
          </div>
        )}

        {/* Customer Type */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Users className="w-3.5 h-3.5 inline mr-1" />
            Customer Type <span className="text-red-500">*</span>
          </label>
          <div className="grid grid-cols-3 rounded-lg border border-gray-200 overflow-hidden text-xs font-medium">
            {CUSTOMER_TYPES.map(t => (
              <button
                key={t.key}
                type="button"
                disabled={locked}
                // Changing the type invalidates every id under it.
                onClick={() => setTag({
                  customerType: t.key, agencyId: null, corporateId: null, customerId: null, partyName: "",
                })}
                className={`py-2 px-1 transition-colors border-r border-gray-200 last:border-r-0 disabled:cursor-not-allowed ${
                  tag.customerType === t.key
                    ? "bg-[#1e3a5f] text-white"
                    : "bg-white text-gray-600 hover:bg-gray-50 disabled:text-gray-400"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          {touched && !tag.customerType && (
            <p className="text-[11px] text-red-500 mt-1">Customer type is required</p>
          )}
        </div>

        {/* The party itself */}
        {tag.customerType && (
          emptyMaster ? (
            <div className="px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
              No {tag.customerType === "agency" ? "agencies" : tag.customerType === "corporate" ? "corporates" : "customers"} yet.{" "}
              <Link href={CUSTOMER_TYPE_MASTER[tag.customerType].href} className="font-semibold underline">
                Add them in {CUSTOMER_TYPE_MASTER[tag.customerType].label}
              </Link>
              {tag.customerType === "direct" && " — or leave this blank for a walk-in."}
            </div>
          ) : (
            <AgencyDropdown
              agency={currentLabel}
              setAgency={pickParty}
              agencyOptions={partyOptions}
              // A direct customer may legitimately have no master record, so its
              // picker never shows the required-field error.
              touched={touched && tag.customerType !== "direct"}
              fieldCls={fieldCls}
              disabled={locked}
              label={tag.customerType === "agency" ? "Agency" : tag.customerType === "corporate" ? "Corporate" : "Customer (optional)"}
              placeholder={loaded ? "— Select —" : "Loading…"}
            />
          )
        )}

        {/* Statement Name */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Tag className="w-3.5 h-3.5 inline mr-1" /> Statement Name
          </label>
          <input
            type="text" value={statementName} disabled={locked} maxLength={500}
            placeholder={derivedName || "e.g. July sales — Lords Delhi"}
            onChange={e => setStatementName(e.target.value)}
            className="w-full border border-gray-200 bg-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-60"
          />
          <p className="text-[11px] text-gray-400 mt-1">
            {statementName.trim()
              ? "Used as the statement's name in the repository."
              : derivedName ? `Leave blank to name it “${derivedName}”.`
              : "Leave blank to name it from the customer and start date."}
          </p>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Calendar className="w-3.5 h-3.5 inline mr-1" /> Statement Valid From <span className="text-red-500">*</span>
          </label>
          <input type="date" value={validFrom} disabled={locked}
            onChange={e => setValidFrom(e.target.value)}
            onClick={e => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
            className={`${fieldCls(validFrom)} disabled:opacity-60`} />
          {touched && !validFrom && <p className="text-[11px] text-red-500 mt-1">Valid from date is required</p>}
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            <Calendar className="w-3.5 h-3.5 inline mr-1" /> Statement Valid To <span className="text-red-500">*</span>
          </label>
          <input type="date" value={validTo} min={validFrom || undefined} disabled={locked}
            onChange={e => setValidTo(e.target.value)}
            onClick={e => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
            className={`${dateError ? "w-full border border-red-300 bg-red-50 rounded-lg px-3 py-2 text-sm" : fieldCls(validTo)} disabled:opacity-60`} />
          {touched && !validTo && <p className="text-[11px] text-red-500 mt-1">Valid to date is required</p>}
          {dateError && <p className="text-[11px] text-red-500 mt-1">Valid to must be on or after valid from</p>}
        </div>

        <div className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium ${
          complete ? "bg-green-50 text-green-700 border border-green-200" : "bg-gray-50 text-gray-400 border border-gray-200"
        }`}>
          <CheckCircle className={`w-4 h-4 ${complete ? "text-green-600" : "text-gray-300"}`} />
          {complete ? "Statement details complete" : "Complete all fields above"}
        </div>
      </div>
    </div>
  );
}

/** The name a corporate is FILED under — its own, never a contact's. */
function corpName(c: Party): string {
  return (c.company || "").trim() || partyName(c);
}
function labelFor(t: CustomerType | null): string {
  return t === "agency" ? "B2B" : t === "corporate" ? "Corporate" : "Direct";
}
