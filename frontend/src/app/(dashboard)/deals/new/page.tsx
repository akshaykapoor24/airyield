"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired, requireFields } from "@/lib/requiredFields";
import {
  IEFieldValue,
  INCENTIVE_TYPES, INCLUSIONS_EXCLUSIONS,
  CONTINENTS, COUNTRY_GROUPS,
  SelectField, SearchSelectField, MultiSearchSelectField, DateField, TabBar, SectionCard,
  IncentiveTabContent, InclExclTabContent, incentiveEntryToForm,
} from "@/components/deals/IncentiveInclExclShared";
import OutgoingScopeFields, { type ScopeSelection } from "@/components/deals/OutgoingScopeFields";
import {
  OUTGOING_DEAL_KINDS, KIND_BUSINESS_TYPE, buildScopePayload, dealsHref, directionLabel,
  fromScopeType, toScopeType,
  type DealScopeType, type OutgoingDealKind,
} from "@/lib/dealScope";

// ── static options ───────────────────────────────────────────────────────────
const CONTRACT_YEARS = ["Calendar year", "Financial year"];
const TRIGGER_TYPES  = ["Flown", "Sales"];
const PAYOUT_TYPES   = ["Flown", "Sales"];
const BUSINESS_TYPES = ["B2B", "B2C", "B2E", "MICE"];

/** An onboarded agency, as matched from the chosen Supplier name. */
type AgencyMatch = { id: number; name: string; branch_name: string | null; branch_code: string; channels: string };

// Entity codes and Login IDs / IATA come from the User Master. Login IDs are
// filtered by airline name + vendor (supplier) + LoB (= business type).
type LoginIdMaster = {
  login_id: string;
  airline_name: string | null;
  vendor_name: string | null;
  lob: string | null;
  is_active: boolean;
};

// The deal-level Contract Valid From/To flow down into each selected incentive's
// own from/to date fields. Keys differ per incentive; Ancillary and Deposit
// Incentive (DI) have no contract date fields, so they're intentionally omitted.
const INCENTIVE_DATE_KEYS: Record<string, [fromKey: string, toKey: string]> = {
  "PLB":               ["validFrom", "validTo"],
  "Super PLB":         ["validFrom", "validTo"],
  "Transaction Fee":   ["validFrom", "validTo"],
  "Marketing Fund":    ["validFrom", "validTo"],
  "Frontend":          ["validFrom", "validTo"],
  "Backend":           ["validFrom", "validTo"],
  "Push Action":       ["validFrom", "validTo"],
  "Cashback":          ["cashbackPeriodFrom", "cashbackPeriodTo"],
  "Segment Incentive": ["siPeriodFrom", "siPeriodTo"],
};

const INCL_EXCL_META: Record<string, { suffix: string; isExclusion: boolean }> = {
  "Inclusion For Trigger": { suffix: "for Inclusion", isExclusion: false },
  "Exclusion For Trigger": { suffix: "for Exclusion", isExclusion: true  },
  "Inclusion For Payout":  { suffix: "for Inclusion", isExclusion: false },
  "Exclusion For Payout":  { suffix: "for Exclusion", isExclusion: true  },
};

// ── deal type selection screen ───────────────────────────────────────────────
function DealTypeSelector({ direction, onSelect }: {
  direction: "inbound" | "outbound";
  onSelect: (dir: "inbound" | "outbound", t: "airline" | "b2b", tag: "standard" | "adhoc", scope: DealScopeType) => void;
}) {
  const [selected, setSelected]   = useState<"airline" | "b2b" | null>(null);
  const [dealTag, setDealTag]     = useState<"standard" | "adhoc">("standard");
  // Outgoing only: WHO the deal is for. Kept separate from `dealType` on purpose —
  // `dealType` is the airline-vs-b2b discriminator that drives the API endpoint,
  // the required-column set and the contract fields, and writing a scope into it
  // would silently disable all three.
  const [scopeKind, setScopeKind]   = useState<OutgoingDealKind>("b2b");

  // Outgoing deals can only be B2B at the contract level — you can't float a deal
  // back to an airline. Who it reaches is the scope question below.
  const typeOptions: ReadonlyArray<"airline" | "b2b"> = direction === "outbound" ? ["b2b"] : ["airline", "b2b"];
  const effectiveSelected: "airline" | "b2b" | null = direction === "outbound" ? "b2b" : selected;
  const outbound = direction === "outbound";
  const scope: DealScopeType = outbound ? toScopeType(scopeKind) : "all";

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-10 w-full max-w-md">
        <h1 className="text-base font-semibold text-gray-800 mb-1">Deal Details</h1>
        <p className="text-xs text-gray-400 mb-6">Choose the type of deal you want to create.</p>

        {/* Direction is fixed by the entry point (Incoming vs Outgoing repo) — read-only */}
        <div className="mb-6">
          <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide mb-2">Deal Direction</p>
          <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium border ${
            direction === "outbound"
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}>
            {direction === "outbound" ? "Outgoing" : "Incoming"}
          </span>
        </div>

        {outbound ? (
          <div className="mb-6">
            <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide mb-2">Deal Type</p>
            <div className="grid grid-cols-3 gap-2">
              {OUTGOING_DEAL_KINDS.map(k => (
                <label key={k.key}
                  className={`flex flex-col gap-1 border rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                    scopeKind === k.key
                      ? "border-blue-500 bg-blue-50/60"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
                  }`}>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="scopeKind"
                      value={k.key}
                      checked={scopeKind === k.key}
                      onChange={() => setScopeKind(k.key)}
                      className="w-3.5 h-3.5 accent-blue-600"
                    />
                    <span className="text-xs font-medium text-gray-800">{k.label}</span>
                  </div>
                  <p className="text-[10px] text-gray-400 leading-tight">{k.blurb}</p>
                </label>
              ))}
            </div>
            <p className="text-[10px] text-gray-400 mt-2 leading-tight">
              {scopeKind === "common"
                ? "Applies to every customer — no party to pick."
                : `You will pick the ${scopeKind === "b2b" ? "agency" : "corporate"} on the next screen.`}
            </p>
          </div>
        ) : (
          <div className="mb-6">
            <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide mb-2">Deal Type</p>
            <div className="flex gap-3">
              {typeOptions.map(type => (
                <label key={type}
                  className={`flex items-start gap-2 border rounded-lg px-4 py-2.5 cursor-pointer transition-colors flex-1 ${
                    effectiveSelected === type
                      ? "border-blue-500 bg-blue-50/60"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
                  }`}>
                  <input
                    type="radio"
                    name="dealType"
                    value={type}
                    checked={effectiveSelected === type}
                    onChange={() => setSelected(type)}
                    className="w-3.5 h-3.5 mt-0.5 accent-blue-600"
                  />
                  <div>
                    <span className="text-xs font-medium text-gray-800">
                      {type === "airline" ? "Airline" : "B2B"}
                    </span>
                    <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">
                      {type === "airline"
                        ? "Airline contract with full incentive and payout details"
                        : "B2B deal without contract year"}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="mb-8">
          <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide mb-2">Deal Tag</p>
          <div className="flex gap-3">
            {(["standard", "adhoc"] as const).map(tag => (
              <label key={tag}
                className={`flex items-center gap-2 border rounded-lg px-4 py-2.5 cursor-pointer transition-colors flex-1 ${
                  dealTag === tag
                    ? "border-blue-500 bg-blue-50/60"
                    : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
                }`}>
                <input
                  type="radio"
                  name="dealTag"
                  value={tag}
                  checked={dealTag === tag}
                  onChange={() => setDealTag(tag)}
                  className="w-3.5 h-3.5 accent-blue-600"
                />
                <span className="text-xs font-medium text-gray-700 capitalize">{tag}</span>
                {tag === "standard" && <span className="text-[10px] text-gray-400 ml-auto">(default)</span>}
              </label>
            ))}
          </div>
        </div>

        <button
          type="button"
          disabled={!effectiveSelected}
          onClick={() => effectiveSelected && onSelect(direction, effectiveSelected, dealTag, scope)}
          className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── main page ────────────────────────────────────────────────────────────────
export default function NewDealPage() {
  const router = useRouter();

  const [dealType, setDealType] = useState<"airline" | "b2b" | null>(null);
  const [dealTag, setDealTag]   = useState<"standard" | "adhoc">("standard");
  // inbound = deal received; outbound = deal floated to a sub-agency (B2B only).
  const [direction, setDirection] = useState<"inbound" | "outbound">("inbound");

  // airline contract fields
  const [airlineType, setAirlineType]   = useState("");
  const [airlineName, setAirlineName]   = useState("");
  const [validFrom, setValidFrom]       = useState("");
  const [validTo, setValidTo]           = useState("");
  const [contractYear, setContractYear] = useState("");
  const [triggerType, setTriggerType]   = useState("");
  const [payoutType, setPayoutType]     = useState("");
  const [entity, setEntity]             = useState("");
  const [businessType, setBusinessType] = useState("");
  const [iataCommission, setIataCommission] = useState("");   // IATA commission %
  // Login ID / IATA — multi-select from the User Master, shared by Airline and B2B.
  const [loginIds, setLoginIds]         = useState<string[]>([]);
  const [supplierName, setSupplierName] = useState("");

  // ── Outgoing-deal scope: WHO this deal is floated to ──────────────────────
  // Orthogonal to `dealType`, which stays "b2b" for every outbound deal.
  const [scopeType, setScopeType] = useState<DealScopeType>("all");
  const [scopeSel, setScopeSel]   = useState<ScopeSelection>({
    agencyId: null, corporateId: null, agencyEntityId: null, entity: "", loginIds: [],
  });
  /** Set on the first save attempt, so required-field hints appear only after one. */
  const [submitAttempted, setSubmitAttempted] = useState(false);

  // top-level tab
  const [activeTopTab, setActiveTopTab] = useState<"deal" | "incentive">("deal");

  // incentive sub-tabs
  const [incentives, setIncentives]         = useState<Record<string, boolean>>({});
  const [activeIncentiveTab, setActiveIncentiveTab] = useState("");
  const [incentiveData, setIncentiveData]   = useState<Record<string, Record<string, string>>>({});

  // incl/excl: per incentive type, which of the 4 rule sub-sub-tabs is active
  const [activeInclExclSubTab, setActiveInclExclSubTab] = useState<Record<string, string>>({});
  // [ruleType][incentiveType][field] = value
  const [inclExclData, setInclExclData] = useState<Record<string, Record<string, Record<string, IEFieldValue>>>>({});
  const [viceVersa, setViceVersa]       = useState<Record<string, Record<string, boolean>>>({});

  // file / misc
  const [file, setFile]           = useState<File | null>(null);
  const fileRef                   = useRef<HTMLInputElement>(null);
  const [remark, setRemark]       = useState("");
  const [dealMakerName, setDealMakerName] = useState("");

  const [airlineOptions, setAirlineOptions]           = useState<string[]>([]);
  const [airlines, setAirlines]                       = useState<{airline_name:string;airline_type:string}[]>([]);
  const [loadingAirlines, setLoadingAirlines]         = useState(false);
  const [supplierOptions, setSupplierOptions]         = useState<string[]>([]);
  const [entityOptions, setEntityOptions]             = useState<string[]>([]);
  const [allLoginIds, setAllLoginIds]                 = useState<LoginIdMaster[]>([]);
  const [continentOptions, setContinentOptions]       = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);

  // Agency Onboarding sources. For a B2B Standard deal, Entity + Login ID come
  // from the user's Agency Profile (the agency whose name matches the chosen
  // Supplier) rather than the User Master. Agency names are copied from the
  // Supplier master, so Supplier → Agency is a name match.
  //
  // That match can now return SEVERAL agencies: a vendor is onboarded once per
  // branch AND once per channel, so Lords Delhi GDS, Lords Delhi LCC and Lords
  // Mumbai are three rows with different entities and credentials. When it
  // returns more than one, a Branch field appears and picking one is what
  // resolves the agency — silently taking the first would load the wrong
  // entities and put the wrong login IDs on the deal.
  const [agencies, setAgencies]             = useState<AgencyMatch[]>([]);
  const [agencyBranch, setAgencyBranch]     = useState<number | null>(null);
  const [agencyEntities, setAgencyEntities] = useState<{ id: number; name: string; code: string }[]>([]);
  const [agencyLoginIds, setAgencyLoginIds] = useState<{ id: number; login_id: string; entity_id: number | null }[]>([]);
  const [agencyEntityId, setAgencyEntityId] = useState<number | null>(null);   // selected agency entity (drives login ids)

  const [isSubmitting, setIsSubmitting]   = useState(false);
  const [isDraftSaving, setIsDraftSaving] = useState(false);
  const [submitError, setSubmitError]     = useState("");

  // Edit mode: /deals/new?editId=<id> pre-fills the form from an existing deal and
  // saves via PATCH instead of POST. While pre-filling a B2B Standard deal, the
  // agency-reset effects must NOT wipe the prefilled Entity/Login selection — this
  // ref suppresses those resets until the user actively changes Supplier/Entity.
  const suppressAgencyResetRef = useRef(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editChecked, setEditChecked] = useState(false);
  const [loadingEdit, setLoadingEdit] = useState(false);

  // B2B Standard reroutes Entity + Login ID to the Agency Onboarding data.
  const isB2bStandard = dealType === "b2b" && dealTag === "standard";
  // Deliberately NOT folded into isB2bStandard: that flag also drives the
  // incentive tab's date-wise slabs and the incl/excl class list, so widening it
  // would quietly change the incentive form for outgoing adhoc deals. This one
  // only governs which party fields render and where entity/logins come from.
  const outboundScoped = direction === "outbound";
  // Every onboarded branch of the chosen Supplier, by name.
  const agencyMatches = isB2bStandard
    ? agencies.filter(a => (a.name ?? "").trim().toLowerCase() === supplierName.trim().toLowerCase())
    : [];
  // One match resolves itself; several need the Branch field below.
  const agencyId = agencyMatches.length === 1
    ? agencyMatches[0].id
    : (agencyBranch != null && agencyMatches.some(a => a.id === agencyBranch) ? agencyBranch : null);

  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then(r => setSupplierOptions(r.data.map(s => s.name)))
      .catch(() => {});
  }, []);

  // The user's own agencies (Agency Profile → Agency Onboarding). Used to map the
  // chosen Supplier to an agency for the B2B Standard Entity/Login ID lists.
  useEffect(() => {
    api.get<AgencyMatch[]>("/agencies/", { params: { limit: 1000 } })
      .then(r => setAgencies(r.data))
      .catch(() => {});
  }, []);

  // A different Supplier means a different set of branches — drop the old pick.
  useEffect(() => { setAgencyBranch(null); }, [supplierName]);

  // Edit mode — read ?editId once and pre-fill the whole form from the deal.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("editId");
    const id = Number(raw || "");
    setEditChecked(true);
    // Direction is fixed by the entry point (Incoming vs Outgoing repo) and is set
    // for BOTH modes. In edit mode the value below is only a seed — the authoritative
    // one comes back from /form — but seeding it means the correct form renders
    // straight away, and Cancel still returns to the right repository if that
    // request fails.
    if (params.get("direction") === "outbound") setDirection("outbound");
    if (!raw || !Number.isFinite(id) || id <= 0) return;
    let cancelled = false;
    setLoadingEdit(true);
    suppressAgencyResetRef.current = true;   // keep prefilled entity/login (B2B Standard)
    api.get<Record<string, unknown>>(`/deals/repository/${id}/form`)
      .then(({ data }) => {
        if (cancelled) return;
        setEditingId(id);
        setDealType(data.deal_type === "b2b" ? "b2b" : "airline");
        setDealTag(data.deal_tag === "adhoc" ? "adhoc" : "standard");
        setDirection(data.direction === "outbound" ? "outbound" : "inbound");
        setAirlineType((data.airline_type as string) ?? "");
        setAirlineName((data.airline_name as string) ?? "");
        setValidFrom((data.valid_from as string) ?? "");
        setValidTo((data.valid_to as string) ?? "");
        setContractYear((data.contract_year as string) ?? "");
        setTriggerType((data.trigger_type as string) ?? "");
        setPayoutType((data.payout_type as string) ?? "");
        setEntity((data.entity as string) ?? "");
        setBusinessType((data.business_type as string) ?? "");
        setIataCommission((data.iata_commission as string) ?? "");
        const savedLoginIds = Array.isArray(data.login_ids) ? (data.login_ids as string[]) : [];
        setLoginIds(savedLoginIds);
        setSupplierName((data.supplier_name as string) ?? "");
        // Outgoing scope. Without this the form re-opened on the Incoming branch
        // with no party, and saving would have re-scoped the deal to whatever the
        // default happened to be.
        setScopeType((data.scope_type as DealScopeType) ?? "all");
        setScopeSel({
          agencyId:       (data.agency_id as number) ?? null,
          corporateId:    (data.corporate_id as number) ?? null,
          agencyEntityId: (data.agency_entity_id as number) ?? null,
          entity:         (data.entity as string) ?? "",
          loginIds:       savedLoginIds,
        });
        setRemark((data.remark as string) ?? "");
        setDealMakerName((data.deal_maker_name as string) ?? "");
        // Incentives: rebuild the boolean map + per-incentive flat form (repo slabs[]
        // → amountSlabs/segmentSlabs JSON via incentiveEntryToForm).
        const incTypes = (data.incentive_types as string[]) ?? [];
        const incMap: Record<string, boolean> = {};
        const incData: Record<string, Record<string, string>> = {};
        const rawIncData = (data.incentive_data as Record<string, Record<string, unknown>>) ?? {};
        for (const t of incTypes) {
          incMap[t] = true;
          incData[t] = incentiveEntryToForm(rawIncData[t] ?? {});
        }
        setIncentives(incMap);
        setIncentiveData(incData);
        setActiveIncentiveTab(incTypes[0] ?? "");
        // Incl/excl already arrives in create-form shape {ruleType: {incType: fields}}.
        setInclExclData((data.incl_excl_data as Record<string, Record<string, Record<string, IEFieldValue>>>) ?? {});
        setViceVersa((data.vice_versa as Record<string, Record<string, boolean>>) ?? {});
      })
      .catch(() => { suppressAgencyResetRef.current = false; })
      .finally(() => { if (!cancelled) setLoadingEdit(false); });
    return () => { cancelled = true; };
  }, []);

  // Entity codes + Login IDs from the User Master (tenant-scoped).
  useEffect(() => {
    api.get<{ code: string }[]>("/entities/", { params: { limit: 1000 } })
      .then(r => setEntityOptions(Array.from(new Set(r.data.map(e => e.code).filter(Boolean)))))
      .catch(() => {});
    api.get<LoginIdMaster[]>("/login-ids/", { params: { limit: 1000 } })
      .then(r => setAllLoginIds(r.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    api.get<{ continents: string[]; country_groups: string[] }>("/airports/options")
      .then(({ data }) => {
        if (data.continents?.length)     setContinentOptions(data.continents);
        if (data.country_groups?.length) setCountryGroupOptions(data.country_groups);
      })
      .catch(() => {});
  }, []);

  // Load all airlines with their type up-front; Airline Type auto-fills from the
  // class/RBD master once the user picks an airline.
  useEffect(() => {
    setLoadingAirlines(true);
    api.get<{airline_name:string;airline_type:string}[]>("/classes/airlines-with-type")
      .then(r => { setAirlines(r.data); setAirlineOptions(r.data.map(a => a.airline_name)); })
      .catch(() => {})
      .finally(() => setLoadingAirlines(false));
  }, []);

  // B2B Standard: whenever the resolved agency changes (i.e. the Supplier changed),
  // reset the entity/login selection and reload the agency's entities. During an edit
  // prefill the reset is suppressed so the prefilled Entity/Login survives.
  useEffect(() => {
    if (!isB2bStandard) return;
    if (!suppressAgencyResetRef.current) {
      setEntity("");
      setAgencyEntityId(null);
      setLoginIds([]);
      setAgencyLoginIds([]);
    }
    if (!agencyId) { setAgencyEntities([]); return; }
    api.get<{ id: number; name: string; code: string }[]>("/agency-entities/", { params: { agency_id: agencyId, limit: 1000 } })
      .then(r => setAgencyEntities(r.data))
      .catch(() => setAgencyEntities([]));
  }, [isB2bStandard, agencyId]);

  // B2B Standard edit prefill: the form endpoint gives the entity NAME, not its id.
  // Once the agency's entities load, resolve the id so the login ids can be fetched.
  useEffect(() => {
    if (!isB2bStandard || !entity || agencyEntityId != null) return;
    const match = agencyEntities.find(e => e.name === entity);
    if (match) setAgencyEntityId(match.id);
  }, [isB2bStandard, entity, agencyEntities, agencyEntityId]);

  // B2B Standard: whenever the selected agency entity changes, reload that entity's
  // login ids from Agency Onboarding (reset suppressed during an edit prefill).
  useEffect(() => {
    if (!isB2bStandard) return;
    if (!suppressAgencyResetRef.current) setLoginIds([]);
    if (!agencyId || !agencyEntityId) { setAgencyLoginIds([]); return; }
    api.get<{ id: number; login_id: string; entity_id: number | null }[]>("/agency-login-ids/", { params: { agency_id: agencyId, entity_id: agencyEntityId, limit: 1000 } })
      .then(r => setAgencyLoginIds(r.data))
      .catch(() => setAgencyLoginIds([]));
  }, [isB2bStandard, agencyId, agencyEntityId]);

  const selectedIncentives = INCENTIVE_TYPES.filter(t => incentives[t]);

  // Airline Name always lists every airline from the master. Picking a name
  // auto-fills the Airline Type (looked up from the class/RBD master); choosing a
  // type does NOT filter the name list.
  const airlineNameOptions = airlineOptions;

  // Login IDs are filtered by the selected Airline Name + Supplier (vendor) +
  // Business Type (= the login id's LoB). Each filter applies only when set, so
  // e.g. "Air India" + "Lords Travel" + "B2B" narrows to matching login ids.
  const _norm = (s: string | null | undefined) => (s ?? "").trim().toLowerCase();
  const loginIdOptions = Array.from(new Set(
    allLoginIds
      .filter(l => l.is_active)
      .filter(l => !airlineName  || _norm(l.airline_name) === _norm(airlineName))
      .filter(l => !supplierName || _norm(l.vendor_name)  === _norm(supplierName))
      .filter(l => !businessType || _norm(l.lob)          === _norm(businessType))
      .map(l => l.login_id)
  ));

  // Entity + Login ID sources swap to Agency Onboarding data for B2B Standard.
  // Entity options are the matched agency's entity names; Login ID options are the
  // login ids under the chosen entity. Everything else keeps the User Master list.
  const entityFieldOptions = isB2bStandard
    ? Array.from(new Set(agencyEntities.map(e => e.name).filter(Boolean)))
    : entityOptions;
  const loginIdFieldOptions = isB2bStandard
    ? Array.from(new Set(agencyLoginIds.map(l => l.login_id).filter(Boolean)))
    : loginIdOptions;
  const entityPlaceholder = !isB2bStandard
    ? "Search and select"
    : !supplierName            ? "Select a supplier first"
    : agencyMatches.length > 1 && agencyId == null ? "Select a branch first"
    : agencyId == null         ? "No matching agency for this supplier"
    : agencyEntities.length === 0 ? "No entities for this agency"
    :                            "Search and select";
  const loginIdPlaceholder = !isB2bStandard
    ? "Search and select"
    : !entity                    ? "Select an entity first"
    : agencyLoginIds.length === 0 ? "No login IDs for this entity"
    :                             "Search and select";

  // Set the deal-level contract dates and mirror them into every selected
  // incentive that has its own from/to date fields (all except Ancillary and DI).
  const setContractDates = (from: string, to: string) => {
    setValidFrom(from);
    setValidTo(to);
    setIncentiveData(prev => {
      const next = { ...prev };
      for (const inc of selectedIncentives) {
        const keys = INCENTIVE_DATE_KEYS[inc];
        if (!keys) continue;
        next[inc] = { ...(next[inc] ?? {}), [keys[0]]: from, [keys[1]]: to };
      }
      return next;
    });
  };

  const toggleIncentive = (key: string) => {
    setIncentives(p => {
      const next = { ...p, [key]: !p[key] };
      if (!p[key]) {
        setActiveIncentiveTab(key);
        // Seed the newly-selected incentive's from/to with the deal-level dates.
        const keys = INCENTIVE_DATE_KEYS[key];
        if (keys && (validFrom || validTo)) {
          setIncentiveData(prevD => {
            const seeded = { ...(prevD[key] ?? {}) };
            if (validFrom) seeded[keys[0]] = validFrom;
            if (validTo)   seeded[keys[1]] = validTo;
            return { ...prevD, [key]: seeded };
          });
        }
      } else {
        const remaining = INCENTIVE_TYPES.filter(t => t !== key && next[t]);
        setActiveIncentiveTab(remaining[remaining.length - 1] ?? "");
      }
      return next;
    });
  };

  const setIncentiveField = (inc: string, k: string, v: string) =>
    setIncentiveData(p => ({ ...p, [inc]: { ...(p[inc] ?? {}), [k]: v } }));

  const setInclExclField = (sec: string, incType: string, k: string, v: IEFieldValue) =>
    setInclExclData(p => ({
      ...p,
      [sec]: { ...(p[sec] ?? {}), [incType]: { ...(p[sec]?.[incType] ?? {}), [k]: v } },
    }));

  const toggleViceVersa = (sec: string, incType: string) =>
    setViceVersa(p => ({
      ...p,
      [sec]: { ...(p[sec] ?? {}), [incType]: !p[sec]?.[incType] },
    }));

  const getActiveInclExclSubTab = (incType: string) =>
    activeInclExclSubTab[incType] ?? INCLUSIONS_EXCLUSIONS[0];

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f && f.type === "application/pdf") setFile(f);
  };

  // Contract Year drives the contract dates:
  //   Calendar year  ⇒ Jan 1 – Dec 31 of the current year
  //   Financial year ⇒ Apr 1 (this year) – Mar 31 (next year)
  // Dates stay editable afterwards; other fields are left untouched.
  const handleContractYearChange = (val: string) => {
    setContractYear(val);
    const year = new Date().getFullYear();
    if (val === "Calendar year") {
      setContractDates(`${year}-01-01`, `${year}-12-31`);
    } else if (val === "Financial year") {
      setContractDates(`${year}-04-01`, `${year + 1}-03-31`);
    }
  };

  /** The deal header fields the API declares required (AirlineDealCreate /
   *  B2BDealCreate: airline_type, airline_name, valid_from, valid_to), plus
   *  Supplier Name, which a B2B deal is meaningless without — it is the
   *  counterparty, and for a B2B Standard deal it is also what resolves the
   *  agency whose entities and login IDs populate the two fields below it.
   *
   *  All four API-required fields were previously reachable while blank: the
   *  form checked only three of them, and the API's `str` type accepts "" and
   *  stores it as NULL, so nothing complained either side. */
  const requiredHeaderFields = () => [
    // Incoming only: an outgoing deal names its counterparty through the scope
    // below, not through the supplier master.
    { label: "Supplier Name",       value: supplierName, when: !outboundScoped && dealType === "b2b" },
    // Outgoing, and only for the two "specific" scopes — a Common deal has no party.
    { label: "Agency",              value: scopeSel.agencyId ? "set" : "",    when: outboundScoped && scopeType === "agency" },
    { label: "Corporate",           value: scopeSel.corporateId ? "set" : "", when: outboundScoped && scopeType === "corporate" },
    { label: "Airline Name",        value: airlineName },
    // Auto-filled from the class/RBD master when an airline is picked, but that
    // master does not cover every airline, so it still has to be checked.
    { label: "Airline Type",        value: airlineType },
    { label: "Contract Valid From", value: validFrom },
    { label: "Contract Valid To",   value: validTo },
  ];

  const validateCore = (): boolean => {
    setSubmitAttempted(true);
    return requireFields(requiredHeaderFields());
  };

  /** Contract dates must also make sense against each other — an inverted range
   *  silently produces incentives that can never trigger. */
  const validateDateOrder = (): boolean => {
    if (validFrom && validTo && validTo < validFrom) {
      return notifyRequired("Contract Valid To must be on or after Contract Valid From.");
    }
    return true;
  };

  const buildPayload = (): Record<string, unknown> => {
    const effectiveLoginIds = outboundScoped ? scopeSel.loginIds : loginIds;
    const payload: Record<string, unknown> = {
      source_type:      "manual",
      source_agent:     dealMakerName || "manual",
      deal_tag:         dealTag,
      direction:        direction,
      issue_date:       null,
      notes:            null,
      airline_type:     airlineType,
      airline_name:     airlineName,
      valid_from:       validFrom,
      valid_to:         validTo,
      // Entity + Login ID/IATA are single fields on both forms, always sent and
      // not gated by Airline Type. iata_number / entity_lcc are no longer split
      // out separately — the consolidated values live in entity / login_id.
      // On an outgoing deal the entity and credentials belong to the scoped
      // AGENCY, not to the User Master, so they come off the scope selection.
      entity:           (outboundScoped ? scopeSel.entity : entity) || null,
      iata_number:      null,
      iata_commission:  iataCommission || null,
      business_type:    businessType || null,
      entity_lcc:       null,
      login_id:         effectiveLoginIds.join(", ") || null,   // joined display (back-compat)
      login_ids:        effectiveLoginIds.length ? effectiveLoginIds : null,
      remark:           remark        || null,
      deal_maker_name:  dealMakerName || null,
      incentive_types:  selectedIncentives,
      incentive_data:   incentiveData,
      incl_excl_types:  INCLUSIONS_EXCLUSIONS,
      incl_excl_data:   inclExclData,
      vice_versa:       viceVersa,
      column_map:       {},
      rows:             [],
    };
    if (dealType === "airline") {
      payload.contract_year = contractYear || null;
      payload.trigger_type  = triggerType  || null;
      payload.payout_type   = payoutType   || null;
    }
    if (dealType === "b2b") {
      // Outgoing derives supplier_name server-side from the scope, so the label
      // reads "All Agencies" rather than blank on a common deal.
      payload.supplier_name = outboundScoped ? null : (supplierName || null);
    }
    if (outboundScoped) {
      // buildScopePayload mirrors the server's own re-derivation, so a stale id
      // left behind by a scope change can never travel attached to the wrong scope.
      Object.assign(payload, buildScopePayload(
        scopeType, scopeSel.agencyId, scopeSel.corporateId, scopeSel.agencyEntityId,
      ));
    }
    return payload;
  };

  const handleSaveDraft = async () => {
    // Same checks as Submit, deliberately. "Save Draft" does not currently
    // produce a draft — the API has no draft status and both buttons create the
    // deal as pending_approval — so relaxing validation here would push
    // half-filled deals straight into the approval queue.
    if (!validateCore() || !validateDateOrder()) return;
    setIsDraftSaving(true);
    setSubmitError("");
    try {
      if (editingId != null) {
        await api.patch(`/deals/repository/${editingId}?deal_type=unified`, buildPayload());
        toast.success("Deal updated.");
      } else {
        const endpoint = dealType === "b2b" ? "/deals/manual/b2b" : "/deals/manual/airline";
        await api.post(endpoint, { ...buildPayload(), save_as_draft: true });
        toast.success("Deal saved as draft.");
      }
      router.push(dealsHref(direction));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(msg ?? "Failed to save draft. Make sure the backend is running.");
    } finally {
      setIsDraftSaving(false);
    }
  };

  const handleSubmitForApproval = async () => {
    if (!validateCore() || !validateDateOrder()) return;
    // The Deal Details tab's Next button is disabled until an incentive is
    // ticked, but edit mode and the tab bar can both land here without one, and
    // a deal with no incentive has nothing to approve or calculate.
    if (selectedIncentives.length === 0) {
      notifyRequired("Select at least one Incentive Type before submitting for approval.");
      setActiveTopTab("deal");
      return;
    }
    setIsSubmitting(true);
    setSubmitError("");
    try {
      if (editingId != null) {
        // Edit: full-replace update of the existing deal (rebuilds incentives + rules).
        await api.patch(`/deals/repository/${editingId}?deal_type=unified`, buildPayload());
        toast.success("Deal updated.");
      } else {
        const endpoint = dealType === "b2b" ? "/deals/manual/b2b" : "/deals/manual/airline";
        await api.post(endpoint, buildPayload());
        toast.success("Deal submitted for approval.");
      }
      router.push(dealsHref(direction));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(msg ?? "Failed to submit deal. Make sure the backend is running.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // ── Step 0: deal-type selection (skipped in edit mode — type comes from the deal) ─
  if (dealType === null) {
    if (!editChecked || loadingEdit) {
      return (
        <div className="min-h-[60vh] flex items-center justify-center">
          <p className="text-sm text-gray-400">Loading deal…</p>
        </div>
      );
    }
    return <DealTypeSelector direction={direction} onSelect={(d, t, tag, scope) => { setDirection(d); setDealType(t); setDealTag(tag); setScopeType(scope);
      // Outgoing seeds Business Type from the scope — a corporate customer is B2E.
      // Still editable on the form; this is a default, not a constraint.
      setBusinessType(d === "outbound" ? KIND_BUSINESS_TYPE[fromScopeType(scope)] : (t === "b2b" ? "B2B" : "")); }} />;
  }

  // ── Step 1: two-tab form ─────────────────────────────────────────────────
  return (
    <div className="w-full pb-20">

      {/* Page header */}
      <div className="flex items-center gap-2 mb-3">
        <button type="button" onClick={() => editingId != null ? router.push(dealsHref(direction)) : setDealType(null)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <span className="text-gray-300 text-xs">|</span>
        <h1 className="text-sm font-semibold text-gray-700">
          {editingId != null ? "Edit Deal" : "Create Deal"} —{" "}
          <span className="text-blue-600">{dealType === "airline" ? "Airline" : "B2B"}</span>
          <span className="ml-2 text-[11px] font-normal text-gray-400 capitalize">{dealTag}</span>
          <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium ${direction === "outbound" ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
            {directionLabel(direction)}
          </span>
        </h1>
      </div>

      {/* ── Top-level tabs ── */}
      <div className="flex gap-0 border-b border-gray-200 mb-4 bg-white rounded-t-lg px-2 pt-2">
        {(["deal", "incentive"] as const).map(tab => (
          <button
            key={tab}
            type="button"
            disabled={tab === "incentive" && selectedIncentives.length === 0}
            onClick={() => setActiveTopTab(tab)}
            className={`flex items-center gap-1.5 px-5 py-2 text-sm font-semibold border-b-2 transition-colors ${
              activeTopTab === tab
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            } ${tab === "incentive" && selectedIncentives.length === 0 ? "opacity-40 cursor-not-allowed" : ""}`}>
            {tab === "deal" ? "Deal Details" : "Incentive Details"}
            {tab === "incentive" && selectedIncentives.length > 0 && (
              <span className="bg-blue-100 text-blue-600 text-[10px] px-1.5 py-0.5 rounded-full font-semibold">
                {selectedIncentives.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* TAB 1 — DEAL DETAILS                                             */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {activeTopTab === "deal" && (
        <div className="space-y-3">

          {/* Airline Contract Details */}
          <SectionCard title="Airline Contract Details">
            <div className="px-4 py-3 grid grid-cols-2 gap-3">
              {/* [1] WHO the deal is for.
                  Outgoing picks the party straight from Agency / Corporate Master,
                  so there is a real id to match a ticket against later — and no
                  branch to disambiguate, because one agency row IS one branch on
                  one channel. Incoming keeps the supplier-name search: it names a
                  vendor from the global supplier master, which is a different set. */}
              {outboundScoped ? (
                <OutgoingScopeFields
                  scope={scopeType}
                  value={scopeSel}
                  onChange={setScopeSel}
                  touched={submitAttempted}
                />
              ) : dealType === "b2b" && (
                <SearchSelectField
                  label="Supplier Name"
                  required
                  options={supplierOptions}
                  value={supplierName}
                  onChange={v => { suppressAgencyResetRef.current = false; setSupplierName(v); }}
                  placeholder={supplierOptions.length ? "Search and select supplier" : "Loading suppliers..."}
                />
              )}

              {/* [1b] Branch — only when this supplier is onboarded more than once.
                  Entities and login IDs belong to a BRANCH, so without this the
                  form would load one branch's and attach them to the other's deal.
                  Outgoing never needs it: the agency picker already names the exact
                  branch + channel row. */}
              {!outboundScoped && isB2bStandard && agencyMatches.length > 1 && (
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                    Branch <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={agencyBranch ?? ""}
                    onChange={e => { suppressAgencyResetRef.current = false; setAgencyBranch(e.target.value ? Number(e.target.value) : null); }}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50"
                  >
                    <option value="">— Select branch —</option>
                    {/* Channel as well as branch: one branch working both channels
                        is onboarded twice, and the two rows carry different
                        entities and credentials under the same branch name. */}
                    {agencyMatches.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.branch_name || a.branch_code} · {a.channels}
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-gray-400 mt-1">
                    This agency is onboarded {agencyMatches.length} times — per branch and per channel — and each
                    has its own entities and login IDs.
                  </p>
                </div>
              )}

              {/* [2] Airline Name — full master list; picking one auto-fills the type */}
              <SearchSelectField
                label="Airline Name"
                required
                options={airlineNameOptions}
                value={airlineName}
                onChange={name => {
                  setAirlineName(name);
                  // Auto-fill the type from the class/RBD master; if this airline has
                  // no type there, clear it (don't keep the previous airline's type).
                  const t = (airlines.find(a => a.airline_name === name)?.airline_type || "").toUpperCase();
                  setAirlineType(t);
                }}
                placeholder={loadingAirlines ? "Loading airlines..." : "Search and select airline"}
              />

              {/* [3] Airline Type — auto-fills when an airline is picked (from the
                   class/RBD master), but stays editable and may be left blank. */}
              <SelectField
                label="Airline Type"
                required
                options={["GDS", "LCC"]}
                value={airlineType}
                onChange={setAirlineType}
              />

              {/* [3b] Contract Year — Airline only; selecting it auto-fills the dates */}
              {dealType === "airline" && (
                <SelectField label="Contract Year" options={CONTRACT_YEARS} value={contractYear} onChange={handleContractYearChange} />
              )}

              {/* [4] Business Type — shown for every deal (B2B defaults to "B2B") */}
              <SearchSelectField label="Business Type" options={BUSINESS_TYPES} value={businessType} onChange={setBusinessType} />

              {/* [6] Valid From — flows into every selected incentive's "from" date */}
              <DateField label="Contract Valid From" required value={validFrom} onChange={v => setContractDates(v, validTo)} />

              {/* [7] Valid To — flows into every selected incentive's "to" date */}
              <DateField label="Contract Valid To" required value={validTo} onChange={v => setContractDates(validFrom, v)} />

              {/* [8a+8b] Trigger Type + Payout Type — Airline only */}
              {dealType === "airline" && (
                <>
                  <SelectField label="Trigger Type" options={TRIGGER_TYPES} value={triggerType} onChange={setTriggerType} />
                  <SelectField label="Payout Type"  options={PAYOUT_TYPES}  value={payoutType}  onChange={setPayoutType} />
                </>
              )}

              {/* Entity + Login ID/IATA — single fixed fields shown for both Airline
                   and B2B. Not gated by Airline Type, and unaffected when other
                   fields (Airline Type, Contract Year, …) change. For B2B Standard
                   these come from Agency Onboarding (agency-by-supplier → entities →
                   login ids); otherwise from the User Master.
                   Hidden on an outgoing deal: OutgoingScopeFields renders its own
                   Agency Entity / Agency Login ID above, sourced from the picked
                   agency, and two sets of the same field would disagree. */}
              {!outboundScoped && (
              <>
              <SearchSelectField
                label="Entity"
                placeholder={entityPlaceholder}
                options={entityFieldOptions}
                value={entity}
                onChange={name => {
                  suppressAgencyResetRef.current = false;   // user picked an entity → allow login reset
                  setEntity(name);
                  // Track the agency entity id so its login ids can be loaded (B2B Standard).
                  if (isB2bStandard) setAgencyEntityId(agencyEntities.find(e => e.name === name)?.id ?? null);
                }}
              />
              <MultiSearchSelectField
                label={dealType === "airline" ? "Login ID / IATA Code" : "Login ID / IATA Number"}
                placeholder={loginIdPlaceholder}
                options={loginIdFieldOptions}
                values={loginIds}
                onChange={setLoginIds}
              />
              </>
              )}

              {/* IATA Commission (%) — free numeric input, after Login ID / IATA */}
              <div>
                <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">IATA Commission (%)</label>
                <div className="relative">
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    value={iataCommission}
                    onChange={e => setIataCommission(e.target.value)}
                    placeholder="e.g. 5"
                    className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 pr-6"
                  />
                  <span className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs pointer-events-none">%</span>
                </div>
              </div>
            </div>
          </SectionCard>

          {/* Incentive Types — checkboxes only, no inline content */}
          <SectionCard title="Incentive Types">
            <div className="px-4 py-3 grid grid-cols-4 gap-x-4 gap-y-2">
              {INCENTIVE_TYPES.map(type => (
                <label key={type} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!incentives[type]}
                    onChange={() => toggleIncentive(type)}
                    className="w-3.5 h-3.5 rounded border-gray-300 accent-blue-600"
                  />
                  <span className="text-xs text-gray-700">{type}</span>
                </label>
              ))}
            </div>
            {selectedIncentives.length > 0 && (
              <div className="px-4 pb-3">
                <p className="text-[11px] text-blue-500 mt-1">
                  {selectedIncentives.length} incentive type{selectedIncentives.length > 1 ? "s" : ""} selected — configure details in the{" "}
                  <button
                    type="button"
                    onClick={() => setActiveTopTab("incentive")}
                    className="underline font-medium hover:text-blue-700">
                    Incentive Details tab
                  </button>.
                </p>
              </div>
            )}
          </SectionCard>

          {/* Upload Contract File */}
          <div className="bg-white rounded-lg border border-gray-200 px-4 py-3 space-y-1.5">
            <div className="flex items-center gap-1">
              <span className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Upload Contract File</span>
              <span
                className="w-3.5 h-3.5 rounded-full border border-gray-400 text-gray-400 text-[9px] flex items-center justify-center cursor-help"
                title="Upload contract PDF">
                i
              </span>
            </div>
            <p className="text-[10px] text-gray-400">Supported File Type(s): .pdf</p>
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileRef.current?.click()}
              className="border-2 border-dashed border-gray-200 rounded-lg flex flex-col items-center justify-center py-6 cursor-pointer hover:border-blue-300 hover:bg-blue-50/20 transition-colors">
              <input ref={fileRef} type="file" accept=".pdf" className="hidden"
                onChange={e => setFile(e.target.files?.[0] ?? null)} />
              <svg className="w-8 h-8 text-blue-400 mb-1" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="8" y="6" width="24" height="32" rx="3" />
                <rect x="16" y="10" width="24" height="32" rx="3" strokeDasharray="4 2" />
              </svg>
              <p className="text-xs text-blue-500">{file ? file.name : "Drag and drop or click to upload file."}</p>
            </div>
          </div>

          {/* Remark */}
          <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
            <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Remark</label>
            <textarea
              rows={2}
              placeholder="Enter text"
              value={remark}
              onChange={e => setRemark(e.target.value)}
              className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
            />
          </div>

          {/* Deal Maker Details */}
          <SectionCard title="Deal Maker Details">
            <div className="px-4 py-3">
              <div className="max-w-[50%]">
                <label className="block text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Name</label>
                <input
                  type="text"
                  placeholder="Enter Name"
                  value={dealMakerName}
                  onChange={e => setDealMakerName(e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
            </div>
          </SectionCard>

        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* TAB 2 — INCENTIVE DETAILS                                        */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      {activeTopTab === "incentive" && (
        <div>
          {selectedIncentives.length === 0 ? (
            <div className="bg-white rounded-lg border border-gray-200 px-4 py-12 text-center">
              <p className="text-xs text-gray-400">
                Select at least one incentive type in the{" "}
                <button type="button" onClick={() => setActiveTopTab("deal")}
                  className="underline text-blue-500 hover:text-blue-700">
                  Deal Details tab
                </button>{" "}
                to configure incentive details.
              </p>
            </div>
          ) : (
            <div className="bg-white rounded-lg border border-gray-200">

              {/* Level A: incentive type sub-tabs */}
              <TabBar
                tabs={selectedIncentives}
                active={activeIncentiveTab}
                onSelect={setActiveIncentiveTab}
                onRemove={t => toggleIncentive(t)}
              />

              {activeIncentiveTab && incentives[activeIncentiveTab] && (
                <>
                  {/* Incentive-specific fields */}
                  <IncentiveTabContent
                    name={activeIncentiveTab}
                    data={incentiveData[activeIncentiveTab] ?? {}}
                    onChange={(k, v) => setIncentiveField(activeIncentiveTab, k, v)}
                    b2bStandard={isB2bStandard}
                  />

                  {/* Level B: incl/excl rule sub-sub-tabs */}
                  <div className="border-t border-gray-100 mt-1">
                    <div className="px-4 pt-3 pb-0.5">
                      <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                        Inclusion / Exclusion Rules
                      </span>
                    </div>

                    <TabBar
                      tabs={INCLUSIONS_EXCLUSIONS}
                      active={getActiveInclExclSubTab(activeIncentiveTab)}
                      onSelect={t =>
                        setActiveInclExclSubTab(p => ({ ...p, [activeIncentiveTab]: t }))
                      }
                    />

                    {(() => {
                      const ruleTab = getActiveInclExclSubTab(activeIncentiveTab);
                      const meta    = INCL_EXCL_META[ruleTab];
                      return (
                        <InclExclTabContent
                          suffix={meta.suffix}
                          isExclusion={meta.isExclusion}
                          data={inclExclData[ruleTab]?.[activeIncentiveTab] ?? {}}
                          onChange={(k, v) => setInclExclField(ruleTab, activeIncentiveTab, k, v)}
                          viceVersa={!!viceVersa[ruleTab]?.[activeIncentiveTab]}
                          onViceVersa={() => toggleViceVersa(ruleTab, activeIncentiveTab)}
                          continentOptions={continentOptions}
                          countryGroupOptions={countryGroupOptions}
                          // B2B Standard: Class field lists the airline's class codes,
                          // narrowed by this incentive's selected Class.
                          airlineName={isB2bStandard ? airlineName : undefined}
                          incentiveClass={incentiveData[activeIncentiveTab]?.class}
                        />
                      );
                    })()}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Sticky bottom bar ────────────────────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 z-40">
        {submitError && (
          <p className="text-center text-[11px] text-red-500 py-1 border-b border-red-100 bg-red-50">
            {submitError}
          </p>
        )}
        <div className="flex items-center justify-center gap-3 py-2.5">

          {/* Cancel — always visible */}
          <button type="button" onClick={() => router.push(dealsHref(direction))}
            className="px-6 py-1.5 border border-red-400 text-red-500 rounded-full text-xs font-medium hover:bg-red-50 transition-colors">
            Cancel
          </button>

          {/* Save Draft — always visible */}
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={isDraftSaving || isSubmitting}
            className="px-6 py-1.5 border border-gray-300 text-gray-600 rounded-full text-xs font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
            {isDraftSaving ? "Saving..." : editingId != null ? "Save Changes" : "Save Draft"}
          </button>

          {/* Deal Details tab → Next */}
          {activeTopTab === "deal" && (
            <button
              type="button"
              disabled={selectedIncentives.length === 0}
              onClick={() => setActiveTopTab("incentive")}
              className="flex items-center gap-1.5 px-6 py-1.5 bg-[#1e3a5f] text-white rounded-full text-xs font-semibold hover:bg-[#16304f] transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
              Next
              <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M3 8h10M9 4l4 4-4 4"/>
              </svg>
            </button>
          )}

          {/* Incentive Details tab → Submit for Approval */}
          {activeTopTab === "incentive" && (
            <button
              type="button"
              onClick={handleSubmitForApproval}
              disabled={isSubmitting || isDraftSaving}
              className="px-6 py-1.5 bg-blue-600 text-white rounded-full text-xs font-semibold hover:bg-blue-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed">
              {isSubmitting ? "Submitting..." : editingId != null ? "Update Deal" : "Submit for Approval"}
            </button>
          )}

        </div>
      </div>
    </div>
  );
}
