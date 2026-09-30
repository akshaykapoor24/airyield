"use client";

// The Agency field on a third-party statement upload (Vendors data → Statements → Third
// Party: GDS, LCC, API). Shared by the one-shot UploadModal and StatementUploadWizard so the
// two can never list, label or resolve an agency differently.
//
// THE LIST IS THE USER'S OWN AGENCY MASTER (User master → Agency Master), the same list an
// incoming B2B deal picks its Supplier Name from (lib/vendorAgency.ts). It used to be the
// platform-admin Supplier master, which is ~2,500 vendors the user never onboarded.
//
// WHAT IS SENT DOES NOT CHANGE. The upload still carries a SUPPLIER id — the supplier-master
// row the agency was copied from — because that is what the statement is attributed to and
// what the B2B deal carries too (backend api/v1/deals.py::_resolve_vendor_agency), so the
// commission matcher never learns the picker changed. An agency typed in by hand has no such
// row until the platform admin approves it: it is still listed, so the user can see it and
// why it cannot be used yet, but `agency.supplier_id` is null and the caller refuses it.

import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import LccPartyPicker, { type PartyOption } from "@/components/statements/lcc/LccPartyPicker";
import { type VendorAgency, loadVendorAgencies } from "@/lib/vendorAgency";

/** Why `agency` cannot be uploaded against, or null when it can. */
export function agencyBlockReason(agency: VendorAgency | null): string | null {
  if (!agency) {
    return "Select the agency this statement came from — the file itself doesn't name your consolidator.";
  }
  if (agency.supplier_id == null) {
    return `${agency.name} is awaiting approval in the supplier master. Statements can be uploaded against it once your platform admin approves it.`;
  }
  return null;
}

export default function StatementAgencyField({ value, onChange, className }: {
  value: VendorAgency | null;
  onChange: (agency: VendorAgency | null) => void;
  className?: string;
}) {
  const [agencies, setAgencies] = useState<VendorAgency[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadVendorAgencies()
      .then(setAgencies)
      .catch(() => toast.error("Failed to load your Agency Master."))
      .finally(() => setLoaded(true));
  }, []);

  // Inactive agencies are left out of a new pick, as on the B2B deal form. Label = name,
  // sublabel = branch · code · channel: one vendor is onboarded once per branch and per
  // channel, so a label stopping at the name would render identical options.
  const active = useMemo(
    () => agencies.filter((a) => a.is_active).sort((x, y) =>
      x.name.localeCompare(y.name) || (x.branch_name || x.branch_code).localeCompare(y.branch_name || y.branch_code)),
    [agencies],
  );
  const options: PartyOption<"agency">[] = useMemo(
    () => active.map((a) => ({
      value: a.id,
      label: a.name,
      sublabel: [a.branch_name, a.branch_code, a.channels, a.supplier_id == null ? "Awaiting approval" : null]
        .filter(Boolean).join(" · "),
      kind: "agency" as const,
    })),
    [active],
  );

  const pending = value != null && value.supplier_id == null;

  return (
    <div className={`rounded-lg border border-slate-200 bg-slate-50/60 px-3.5 py-3 ${className ?? ""}`}>
      <label className="text-xs font-semibold text-slate-700 block mb-1.5">
        Agency <span className="text-red-500">*</span>
      </label>
      <LccPartyPicker
        options={options}
        value={value?.id ?? null}
        onChange={(o) => onChange(o ? active.find((a) => a.id === o.value) ?? null : null)}
        disabled={active.length === 0}
        placeholder={active.length ? "Select the consolidator who sent this…" : "Agency Master is empty"}
        searchPlaceholder="Search your Agency Master…"
        emptyLabel="No agencies yet — add them under User master → Agency Master."
      />
      <p className="text-[11px] text-slate-400 mt-1.5">
        Who sent you this statement. The file doesn&apos;t say, and Commission income needs
        it to find the right B2B deal. Names come from User master → Agency Master, the same
        list a B2B deal picks its supplier from — pick the right branch, since each one is its
        own contract.
      </p>
      {pending && (
        <p className="text-[11px] text-amber-600 mt-2">{agencyBlockReason(value)}</p>
      )}
      {loaded && active.length === 0 && (
        <p className="text-[11px] text-amber-600 mt-2">
          Your Agency Master is empty. Onboard the consolidator under User master → Agency
          Master before uploading.
        </p>
      )}
    </div>
  );
}
