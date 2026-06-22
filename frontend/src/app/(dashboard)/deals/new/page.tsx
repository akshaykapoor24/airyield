"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import {
  IEFieldValue,
  INCENTIVE_TYPES, INCLUSIONS_EXCLUSIONS,
  CONTINENTS, COUNTRY_GROUPS,
  SelectField, SearchSelectField, DateField, TabBar, SectionCard,
  IncentiveTabContent, InclExclTabContent,
} from "@/components/deals/IncentiveInclExclShared";

// ── static options ───────────────────────────────────────────────────────────
const CONTRACT_YEARS = ["Calendar year", "Financial year"];
const TRIGGER_TYPES  = ["Flown", "Sales"];
const PAYOUT_TYPES   = ["Flown", "Sales"];
const ENTITIES       = ["ATB", "TSI", "YOL"];
const IATA_NUMBERS   = ["12345678", "87654321", "11223344", "44332211"];
const BUSINESS_TYPES = ["B2B", "B2C", "B2E", "MICE"];
const LOGIN_IDS      = ["AGENT001", "AGENT002", "AGENT003", "AGENT004"];

const INCL_EXCL_META: Record<string, { suffix: string; isExclusion: boolean }> = {
  "Inclusion For Trigger": { suffix: "for Inclusion", isExclusion: false },
  "Exclusion For Trigger": { suffix: "for Exclusion", isExclusion: true  },
  "Inclusion For Payout":  { suffix: "for Inclusion", isExclusion: false },
  "Exclusion For Payout":  { suffix: "for Exclusion", isExclusion: true  },
};

// ── deal type selection screen ───────────────────────────────────────────────
function DealTypeSelector({ onSelect }: { onSelect: (t: "airline" | "b2b", tag: "standard" | "adhoc") => void }) {
  const [selected, setSelected] = useState<"airline" | "b2b" | null>(null);
  const [dealTag, setDealTag]   = useState<"standard" | "adhoc">("standard");

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-10 w-full max-w-md">
        <h1 className="text-base font-semibold text-gray-800 mb-1">Select Deal Type</h1>
        <p className="text-xs text-gray-400 mb-6">Choose the type of deal you want to create.</p>

        <div className="flex flex-col gap-3 mb-6">
          {(["airline", "b2b"] as const).map(type => (
            <label key={type}
              className={`flex items-center gap-3 border rounded-lg px-4 py-3.5 cursor-pointer transition-colors ${
                selected === type
                  ? "border-blue-500 bg-blue-50/60"
                  : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/60"
              }`}>
              <input
                type="radio"
                name="dealType"
                value={type}
                checked={selected === type}
                onChange={() => setSelected(type)}
                className="w-4 h-4 accent-blue-600"
              />
              <div>
                <span className="text-sm font-medium text-gray-800">
                  {type === "airline" ? "Airline" : "B2B"}
                </span>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {type === "airline"
                    ? "Airline contract with full incentive and payout details"
                    : "B2B deal without contract year"}
                </p>
              </div>
            </label>
          ))}
        </div>

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
          disabled={!selected}
          onClick={() => selected && onSelect(selected, dealTag)}
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

  // airline contract fields
  const [airlineType, setAirlineType]   = useState("");
  const [airlineName, setAirlineName]   = useState("");
  const [contractYear, setContractYear] = useState("");
  const [validFrom, setValidFrom]       = useState("");
  const [validTo, setValidTo]           = useState("");
  const [triggerType, setTriggerType]   = useState("");
  const [payoutType, setPayoutType]     = useState("");
  const [entity, setEntity]             = useState("");
  const [iataNumber, setIataNumber]     = useState("");
  const [businessType, setBusinessType] = useState("");
  const [entityLCC, setEntityLCC]       = useState("");
  const [loginId, setLoginId]           = useState("");
  const [supplierName, setSupplierName] = useState("");

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
  const [loadingAirlines, setLoadingAirlines]         = useState(false);
  const [supplierOptions, setSupplierOptions]         = useState<string[]>([]);
  const [continentOptions, setContinentOptions]       = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);

  const [isSubmitting, setIsSubmitting]   = useState(false);
  const [isDraftSaving, setIsDraftSaving] = useState(false);
  const [submitError, setSubmitError]     = useState("");

  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then(r => setSupplierOptions(r.data.map(s => s.name)))
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

  const fetchAirlinesByType = async (type: string) => {
    if (!type) { setAirlineOptions([]); return; }
    setLoadingAirlines(true);
    try {
      const { data } = await api.get<string[]>(`/classes/airlines-by-type/${type}`);
      setAirlineOptions(data);
    } catch {
      setAirlineOptions([]);
    } finally {
      setLoadingAirlines(false);
    }
  };

  const selectedIncentives = INCENTIVE_TYPES.filter(t => incentives[t]);

  const toggleIncentive = (key: string) => {
    setIncentives(p => {
      const next = { ...p, [key]: !p[key] };
      if (!p[key]) {
        setActiveIncentiveTab(key);
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

  const validateCore = (): boolean => {
    if (!airlineType) { toast.error("Please select Airline Type."); return false; }
    if (!airlineName) { toast.error("Please select Airline Name."); return false; }
    if (!validFrom)   { toast.error("Please enter Valid From date."); return false; }
    return true;
  };

  const buildPayload = (): Record<string, unknown> => {
    const payload: Record<string, unknown> = {
      source_type:      "manual",
      source_agent:     dealMakerName || "manual",
      deal_tag:         dealTag,
      issue_date:       null,
      notes:            null,
      airline_type:     airlineType,
      airline_name:     airlineName,
      valid_from:       validFrom,
      valid_to:         validTo,
      entity:           airlineType === "GDS" ? (entity       || null) : null,
      iata_number:      airlineType === "GDS" ? (iataNumber   || null) : null,
      business_type:    airlineType === "LCC" ? (businessType || null) : null,
      entity_lcc:       airlineType === "LCC" ? (entityLCC    || null) : null,
      login_id:         airlineType === "LCC" ? (loginId      || null) : null,
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
      payload.supplier_name = supplierName || null;
    }
    return payload;
  };

  const handleSaveDraft = async () => {
    if (!validateCore()) return;
    setIsDraftSaving(true);
    setSubmitError("");
    try {
      const endpoint = dealType === "b2b" ? "/deals/manual/b2b" : "/deals/manual/airline";
      await api.post(endpoint, { ...buildPayload(), save_as_draft: true });
      toast.success("Deal saved as draft.");
      router.push("/deals");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(msg ?? "Failed to save draft. Make sure the backend is running.");
    } finally {
      setIsDraftSaving(false);
    }
  };

  const handleSubmitForApproval = async () => {
    if (!validateCore()) return;
    setIsSubmitting(true);
    setSubmitError("");
    try {
      const endpoint = dealType === "b2b" ? "/deals/manual/b2b" : "/deals/manual/airline";
      await api.post(endpoint, buildPayload());
      toast.success("Deal submitted for approval.");
      router.push("/deals");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(msg ?? "Failed to submit deal. Make sure the backend is running.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // ── Step 0: deal-type selection ──────────────────────────────────────────
  if (dealType === null) {
    return <DealTypeSelector onSelect={(t, tag) => { setDealType(t); setDealTag(tag); }} />;
  }

  // ── Step 1: two-tab form ─────────────────────────────────────────────────
  return (
    <div className="w-full pb-20">

      {/* Page header */}
      <div className="flex items-center gap-2 mb-3">
        <button type="button" onClick={() => setDealType(null)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <span className="text-gray-300 text-xs">|</span>
        <h1 className="text-sm font-semibold text-gray-700">
          Create Deal —{" "}
          <span className="text-blue-600">{dealType === "airline" ? "Airline" : "B2B"}</span>
          <span className="ml-2 text-[11px] font-normal text-gray-400 capitalize">{dealTag}</span>
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
              {/* [1] Airline Type */}
              <SelectField
                label="Airline Type"
                options={["GDS", "LCC"]}
                value={airlineType}
                onChange={v => { setAirlineType(v); setAirlineName(""); fetchAirlinesByType(v); }}
              />

              {/* [2] Airline Name */}
              <SearchSelectField
                label="Airline Name"
                options={airlineOptions}
                value={airlineName}
                onChange={setAirlineName}
                placeholder={loadingAirlines ? "Loading..." : airlineType ? "Search and select" : "Select airline type first"}
              />

              {/* [3] Supplier Name — B2B only */}
              {dealType === "b2b" && (
                <SearchSelectField
                  label="Supplier Name"
                  options={supplierOptions}
                  value={supplierName}
                  onChange={setSupplierName}
                  placeholder={supplierOptions.length ? "Search and select supplier" : "Loading suppliers..."}
                />
              )}

              {/* [4] Contract Year — Airline only */}
              {dealType === "airline" && (
                <SelectField label="Contract Year" options={CONTRACT_YEARS} value={contractYear} onChange={setContractYear} />
              )}

              {/* [5] Business Type — LCC only (fills grid slot) */}
              {airlineType === "LCC"
                ? <SearchSelectField label="Business Type" options={BUSINESS_TYPES} value={businessType} onChange={setBusinessType} />
                : <div />}

              {/* [6] Valid From */}
              <DateField label="Contract Valid From" value={validFrom} onChange={setValidFrom} />

              {/* [7] Valid To */}
              <DateField label="Contract Valid To" value={validTo} onChange={setValidTo} />

              {/* [8a+8b] Trigger Type + Payout Type — Airline only */}
              {dealType === "airline" && (
                <>
                  <SelectField label="Trigger Type" options={TRIGGER_TYPES} value={triggerType} onChange={setTriggerType} />
                  <SelectField label="Payout Type"  options={PAYOUT_TYPES}  value={payoutType}  onChange={setPayoutType} />
                </>
              )}

              {/* Conditional: GDS extras */}
              {airlineType === "GDS" && (
                <>
                  <SearchSelectField label="Entity"      options={ENTITIES}     value={entity}     onChange={setEntity} />
                  <SearchSelectField label="IATA Number" options={IATA_NUMBERS} value={iataNumber} onChange={setIataNumber} />
                </>
              )}

              {/* Conditional: LCC extras */}
              {airlineType === "LCC" && (
                <>
                  <SearchSelectField label="Entity for LCC" options={ENTITIES}  value={entityLCC} onChange={setEntityLCC} />
                  <SearchSelectField label="Login ID"        options={LOGIN_IDS} value={loginId}   onChange={setLoginId} />
                </>
              )}
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
          <button type="button" onClick={() => router.push("/deals")}
            className="px-6 py-1.5 border border-red-400 text-red-500 rounded-full text-xs font-medium hover:bg-red-50 transition-colors">
            Cancel
          </button>

          {/* Save Draft — always visible */}
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={isDraftSaving || isSubmitting}
            className="px-6 py-1.5 border border-gray-300 text-gray-600 rounded-full text-xs font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
            {isDraftSaving ? "Saving..." : "Save Draft"}
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
              {isSubmitting ? "Submitting..." : "Submit for Approval"}
            </button>
          )}

        </div>
      </div>
    </div>
  );
}
