"use client";

// Agency manager (table + add/edit modal + bulk add + xlsx upload) for
// User master → Agency Master. Agencies are private to the user; details are
// copied from the global master at add-time.
//
// ONE ROW IS ONE BRANCH ON ONE CHANNEL. A vendor exists as several master rows,
// one per branch ("Air India Limited" is 3, "Riya Travel & Tours" is 14), and
// Lords Delhi and Lords Mumbai are separate commercial relationships with
// separate deposits, limits and invoices. So the picker is two steps — agency,
// then branch — and both always show. The word "Supplier" is deliberately absent
// from everything the user reads here: to them these are agencies, and the master
// they come from is an implementation detail.
//
// TERMS ARE PER CHANNEL and mandatory. An agency is routinely cash on GDS (it
// books on our IATA stock, so we carry the BSP liability and it pays first) and
// credit on LCC (each airline settles through its own wallet, so exposure is
// capped). THERE IS NO "BOTH" CARD: an agency that works both channels is added
// twice, once per channel, so each gets its own terms block, its own deposit, its
// own balance and its own line in the table. The old single row carrying two
// arrangements had to be special-cased by every screen that read it.
//
// THE TAX BLOCK IS ORDERED BY WHAT CAN BE CHECKED. State fixes a GSTIN's first
// two characters and PAN fixes characters 3 to 12, so the form asks for state,
// then PAN, then whether the agency is registered at all, and only then offers
// the GSTIN box — by which point three of the four checks in lib/indiaTax have
// something to compare against. State is required for exactly that reason.

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Edit2, Trash2, RefreshCw, Search, Wallet, ArrowRight } from "lucide-react";
import api from "@/lib/api";
import SearchSelect from "@/components/ui/SearchSelect";
import {
  STATE_NAMES, canonicalState, gstinError, gstinPlaceholder, gstinTypingError,
  normaliseTaxId, panError, panTypingError,
} from "@/lib/indiaTax";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell, Toolbar,
} from "@/components/userMaster/shared";

export type Channel = "GDS" | "LCC";
// What a row may SAY it trades on. "BOTH" is read-only: rows created before
// agencies were split per channel still carry it, and the account page can still
// widen one, so every reader has to handle it — but nothing here creates it.
export type ChannelScope = Channel | "BOTH";

/** One channel's current arrangement, as the API returns it. */
export type AgencyTerms = {
  channel: Channel;
  agency_type: "cash" | "credit";
  billing_cycle: string;
  credit_limit: number | null;
  usage_percent: number | null;
  terms_id: number;
  effective_from: string;
  cycle_anchor_date: string;
  deposit_paid: number;
};

export type AgencyRow = {
  id: number;
  name: string;
  supplier_id: number | null;
  branch_code: string;
  branch_name: string | null;
  channels: ChannelScope;
  address: string | null;
  state: string | null;
  city: string | null;
  region_chapter: string | null;
  // Stored rather than inferred from a non-null gst_number: "not registered" and
  // "nobody has filled it in yet" are different facts, and only the first one
  // means the blank cell is correct.
  gst_registered: boolean;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  notes: string | null;
  is_active: boolean;
  terms: AgencyTerms[];
};

// The master fields an agency copies from at add-time. Note phone/email come
// from the DIRECTORY columns: contact_phone / contact_email are empty across the
// whole master, so reading only those filled nothing.
type SupplierFull = {
  id: number;
  code: string | null;
  name: string;
  branch: string | null;
  address_1: string | null;
  address_2: string | null;
  address_3: string | null;
  city: string | null;
  region_chapter: string | null;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telephone_mobile: string | null;
  email_address: string | null;
  alternate_email_id: string | null;
  notes: string | null;
};

// No "Both". An agency working both channels is added twice — see the note at the
// top of this file — which is what gives each channel its own terms and balance.
const CHANNEL_CHOICES: { value: Channel; label: string; hint: string }[] = [
  { value: "GDS", label: "GDS", hint: "Books on your IATA stock via a mirror office" },
  { value: "LCC", label: "LCC", hint: "Books on each airline's own agent portal" },
];

const AGENCY_TYPES = [
  { value: "cash", label: "Cash" },
  { value: "credit", label: "Credit" },
] as const;

const BILLING_CYCLES = [
  { value: "weekly", label: "Weekly" },
  { value: "fortnightly", label: "Fortnightly" },
  { value: "monthly", label: "Monthly" },
] as const;

/** Which single channels a declared scope needs terms for. Still handles "BOTH",
 *  because rows created before the split carry it even though nothing makes one. */
const channelsOf = (scope: ChannelScope): Channel[] =>
  scope === "BOTH" ? ["GDS", "LCC"] : [scope];

function money(v: number | null): string {
  if (v == null) return "—";
  return `₹${Number(v).toLocaleString("en-IN")}`;
}

function titleCase(v: string | null): string {
  if (!v) return "—";
  return v.charAt(0).toUpperCase() + v.slice(1);
}

/** "Cash · ₹1,00,00,000 · Monthly" — the whole arrangement in one cell. */
function TermsCell({ t }: { t: AgencyTerms | undefined }) {
  if (!t) return <span className="text-[11px] text-gray-300">—</span>;
  // On cash the usable limit IS the money on deposit, which lives in the ledger.
  const limit = t.agency_type === "cash" ? t.deposit_paid : t.credit_limit;
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`inline-flex w-fit items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
        t.agency_type === "cash"
          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : "bg-amber-50 text-amber-700 border-amber-200"
      }`}>{titleCase(t.agency_type)}</span>
      <span className="text-[11px] font-semibold text-gray-700 whitespace-nowrap">
        {money(limit)}
        {t.agency_type === "cash" && t.usage_percent != null && (
          <span className="text-[10px] font-normal text-gray-400"> · {t.usage_percent}%</span>
        )}
      </span>
      <span className="text-[10px] text-gray-400">{titleCase(t.billing_cycle)}</span>
    </div>
  );
}

function ChannelPills({ scope }: { scope: ChannelScope }) {
  return (
    <div className="flex gap-1">
      {channelsOf(scope).map(c => (
        <span key={c} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
          c === "GDS"
            ? "bg-sky-50 text-sky-700 border-sky-200"
            : "bg-violet-50 text-violet-700 border-violet-200"
        }`}>{c}</span>
      ))}
    </div>
  );
}

export default function AgencyInfoSection({
  onChange, onGoTo,
}: {
  onChange?: (count: number) => void;
  /** Jump to the Entities / Login IDs tab with this agency preselected. */
  onGoTo?: (tab: "entities" | "logins", agencyId: number) => void;
}) {
  const router = useRouter();
  const [rows, setRows] = useState<AgencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<AgencyRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<AgencyRow[]>("/agencies/", { params: { search } });
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [search, onChange]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);

  const toggle = async (row: AgencyRow) => {
    try {
      const { data } = await api.patch<AgencyRow>(`/agencies/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  const del = async (id: number) => {
    if (!confirm("Delete this agency? Its entities and login IDs will be removed too. This cannot be undone.")) return;
    try {
      await api.delete(`/agencies/${id}`);
      setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
    } catch (e) { alert(apiError(e)); }
  };

  const COLUMNS = ["AGENCY", "BRANCH", "CHANNELS", "GDS TERMS", "LCC TERMS", "GST", "PAN", "PHONE", "STATUS", "ACTIONS"];

  return (
    <div className="space-y-3">
      <Toolbar label="Agency" count={rows.length} search={search} setSearch={setSearch}
        onAdd={() => setModal(null)} onRefresh={fetchRows} loading={loading} />

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {COLUMNS.map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-gray-400">No agencies yet. Add one, or upload an XLS.</td></tr>
              ) : rows.map((r, idx) => {
                const byChannel = Object.fromEntries(r.terms.map(t => [t.channel, t]));
                return (
                  <tr key={r.id} className={`border-b border-gray-50 hover:bg-sky-50/30 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{r.name}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                      {r.branch_name || r.city || "—"}
                      <span className="text-[10px] text-gray-400 ml-1">{r.branch_code}</span>
                    </td>
                    <td className="px-3 py-2"><ChannelPills scope={r.channels} /></td>
                    {(["GDS", "LCC"] as Channel[]).map(ch => (
                      <td key={ch} className="px-3 py-2">
                        {channelsOf(r.channels).includes(ch)
                          ? (byChannel[ch]
                              ? <TermsCell t={byChannel[ch]} />
                              : <button onClick={() => router.push(`/user-master/agency-master/${r.id}`)}
                                  className="text-[10px] font-semibold text-sky-600 hover:underline">Set terms</button>)
                          : <span className="text-[11px] text-gray-300">—</span>}
                      </td>
                    ))}
                    {/* "Unregistered" and "—" say different things: the first is an
                        answer, the second is a blank nobody has filled in yet. */}
                    <td className="px-3 py-2 text-[11px] text-gray-600">
                      {r.gst_number || (r.gst_registered
                        ? <span className="text-amber-600">Not entered</span>
                        : <span className="text-gray-400">Unregistered</span>)}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{r.pan_number || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600 max-w-40 truncate" title={r.contact_phone ?? ""}>{r.contact_phone || "—"}</td>
                    <td className="px-3 py-2"><ActiveBadge active={r.is_active} onClick={() => toggle(r)} /></td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button onClick={() => router.push(`/user-master/agency-master/${r.id}`)}
                          className="p-1.5 hover:bg-emerald-50 rounded-lg text-emerald-500 hover:text-emerald-700"
                          title="Account — payments, terms history and billing cycles"><Wallet className="w-3.5 h-3.5" /></button>
                        <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                        <button onClick={() => del(r.id)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {modal !== false && (
        <AgencyModal agency={modal} onClose={() => setModal(false)}
          onSaved={() => { setModal(false); fetchRows(); }} onRefresh={fetchRows} onGoTo={onGoTo} />
      )}
    </div>
  );
}

/** One channel's terms as typed into the form — all strings until save. */
type TermsDraft = { agency_type: string; billing_cycle: string; deposit_amount: string; usage_percent: string; credit_limit: string };
const emptyTerms = (): TermsDraft => ({ agency_type: "", billing_cycle: "", deposit_amount: "", usage_percent: "", credit_limit: "" });

function AgencyModal({
  agency, onClose, onSaved, onRefresh, onGoTo,
}: {
  agency: AgencyRow | null;
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
  onGoTo?: (tab: "entities" | "logins", agencyId: number) => void;
}) {
  const isEdit = !!agency;
  const [tab, setTab] = useState<"single" | "multi" | "xls">("single");
  const [suppliers, setSuppliers] = useState<SupplierFull[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Set on 201 so the modal can offer the natural next steps rather than just closing.
  const [created, setCreated] = useState<AgencyRow | null>(null);

  const [vendorName, setVendorName] = useState("");
  const [supplierId, setSupplierId] = useState<number | null>(null);
  const [channels, setChannels] = useState<Channel>("GDS");
  // Keyed by channel so switching GDS → LCC → GDS does not lose what was typed.
  const [terms, setTerms] = useState<Record<Channel, TermsDraft>>({ GDS: emptyTerms(), LCC: emptyTerms() });
  const [form, setForm] = useState({
    name: agency?.name ?? "",
    branch_code: agency?.branch_code ?? "",
    branch_name: agency?.branch_name ?? "",
    address: agency?.address ?? "",
    // Through canonicalState so a row stored as "NEW DELHI" or "Orissa" selects
    // the picker entry it means instead of showing an empty box.
    state: canonicalState(agency?.state) || "",
    city: agency?.city ?? "",
    region_chapter: agency?.region_chapter ?? "",
    // Registered by default when a GSTIN is already on the row, so opening an
    // existing agency shows its number rather than hiding it behind an off toggle.
    gst_registered: agency?.gst_registered ?? !!agency?.gst_number,
    gst_number: agency?.gst_number ?? "",
    pan_number: agency?.pan_number ?? "",
    contact_phone: agency?.contact_phone ?? "",
    contact_email: agency?.contact_email ?? "",
    notes: agency?.notes ?? "",
    is_active: agency?.is_active ?? true,
  });
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  // Live per-field problems, shown under the box being typed into. Deliberately
  // separate from `error` (which is one line above the buttons): a GSTIN whose
  // check digit is wrong needs to be pointed AT the GSTIN, not summarised.
  //
  // The *Typing* variants stay quiet until the value is long enough to judge —
  // see lib/indiaTax. The strict versions run again in taxProblem() on save, so
  // a half-typed value is caught there rather than slipping through.
  const panProblem = panTypingError(form.pan_number);
  // A malformed PAN is not worth cross-checking the GSTIN against — it would
  // report "characters 3-12 do not match" on top of the PAN error already shown.
  const gstProblem = form.gst_registered
    ? gstinTypingError(form.gst_number, { pan: panProblem ? "" : form.pan_number, state: form.state })
    : "";

  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pickSearch, setPickSearch] = useState("");
  const [result, setResult] = useState<{ created: number; skipped: number } | null>(null);
  // Bulk add applies ONE arrangement to every picked agency, so it offers a
  // single channel choice rather than the per-channel blocks — mixed terms across
  // forty agencies is not something one form can honestly collect. Run it twice,
  // once per channel, to onboard the same set on both.
  const [multiChannel, setMultiChannel] = useState<Channel>("GDS");

  useEffect(() => {
    if (!isEdit) {
      api.get<SupplierFull[]>("/suppliers/", { params: { limit: 5000 } })
        .then(r => setSuppliers(r.data)).catch(() => setSuppliers([]));
    }
  }, [isEdit]);

  // One entry per agency name, each holding its branch rows. ~2,339 names out of
  // ~2,480 master rows, so most have exactly one branch.
  const vendors = useMemo(() => {
    const m = new Map<string, SupplierFull[]>();
    for (const s of suppliers) {
      const key = (s.name ?? "").trim();
      if (!key) continue;
      const existing = m.get(key);
      if (existing) existing.push(s); else m.set(key, [s]);
    }
    return m;
  }, [suppliers]);

  const vendorNames = useMemo(
    () => [...vendors.keys()].sort((a, b) => a.localeCompare(b)),
    [vendors],
  );

  const branches = vendorName ? (vendors.get(vendorName) ?? []) : [];

  const branchLabel = (s: SupplierFull) =>
    [s.branch, s.city, s.region_chapter].filter(Boolean).join(" — ") || s.code || `Branch ${s.id}`;

  // Merge rather than replace, so terms already entered survive a re-pick.
  const applyBranch = (s: SupplierFull) => {
    setSupplierId(s.id);
    setForm(p => ({
      ...p,
      name: s.name ?? "",
      branch_code: (s.code ?? "").trim() || "MAIN",
      branch_name: s.branch || s.city || "",
      // address_1..3 are one postal address split across three columns, not
      // alternatives. State has no source in the master — it is typed in.
      address: [s.address_1, s.address_2, s.address_3].map(x => (x ?? "").trim()).filter(Boolean).join(", "),
      city: s.city ?? "",
      region_chapter: s.region_chapter ?? "",
      // Upper-cased on the way in so the checks below compare like with like —
      // the master is inconsistent about case and these are checked character
      // by character against each other.
      gst_registered: p.gst_registered || !!normaliseTaxId(s.gst_number),
      gst_number: normaliseTaxId(s.gst_number),
      pan_number: normaliseTaxId(s.pan_number),
      contact_phone: s.contact_phone || s.telephone_mobile || "",
      contact_email: s.contact_email || s.email_address || s.alternate_email_id || "",
      notes: s.notes ?? "",
    }));
  };

  const pickVendor = (name: string) => {
    setVendorName(name);
    const list = vendors.get(name) ?? [];
    if (list.length > 0) applyBranch(list[0]);
    else setSupplierId(null);
  };

  const setTerm = (ch: Channel, k: keyof TermsDraft, v: string) =>
    setTerms(p => ({ ...p, [ch]: { ...p[ch], [k]: v } }));

  const setAgencyType = (ch: Channel, v: string) =>
    setTerms(p => ({
      ...p,
      // Drop what no longer applies so a stale deposit can't ride along.
      [ch]: {
        ...p[ch],
        agency_type: v,
        deposit_amount: v === "cash" ? p[ch].deposit_amount : "",
        usage_percent: v === "cash" ? p[ch].usage_percent : "",
        credit_limit: v === "credit" ? p[ch].credit_limit : "",
      },
    }));

  /** State and the tax ids, checked as a set on save — none is right on its own.
   *  Uses the STRICT checks, not the typing-aware ones, so a value abandoned
   *  half-typed is refused here rather than posted. */
  const taxProblem = (): string => {
    if (!form.state) return "Pick the state — a GSTIN's first two characters are checked against it.";
    const pan = panError(form.pan_number);
    if (pan) return pan;
    if (form.gst_registered && !form.gst_number.trim()) {
      return "This agency is marked GST registered — enter its GSTIN, or turn the toggle off.";
    }
    return form.gst_registered
      ? gstinError(form.gst_number, { pan: form.pan_number, state: form.state })
      : "";
  };

  const saveSingle = async () => {
    if (!form.name.trim()) { setError("Agency is required."); return; }
    if (!isEdit && !form.branch_code.trim()) { setError("Pick a branch."); return; }

    const bad = taxProblem();
    if (bad) { setError(bad); return; }

    // An unregistered agency posts no GSTIN at all rather than whatever is still
    // sitting in the hidden box — the two facts have to agree, and "unregistered"
    // is the one just asserted.
    const taxFields = {
      state: form.state,
      gst_registered: form.gst_registered,
      gst_number: form.gst_registered ? normaliseTaxId(form.gst_number) : null,
      pan_number: normaliseTaxId(form.pan_number) || null,
    };

    if (isEdit && agency) {
      // Identity only — terms live on the Account page now.
      setSaving(true); setError("");
      try {
        await api.patch(`/agencies/${agency.id}`, {
          name: form.name.trim(), address: form.address || null, ...taxFields,
          city: form.city || null, region_chapter: form.region_chapter || null,
          contact_phone: form.contact_phone || null, contact_email: form.contact_email || null,
          notes: form.notes || null, is_active: form.is_active,
        });
        onSaved();
      } catch (e) { setError(apiError(e)); }
      finally { setSaving(false); }
      return;
    }

    // One block, for the declared channel. The loop stays because the message has
    // to name the channel — "pick cash or credit" alone does not say which
    // arrangement is incomplete once an agency exists on both.
    const payloadTerms = [];
    for (const ch of channelsOf(channels)) {
      const t = terms[ch];
      if (!t.agency_type) { setError(`${ch}: pick Cash or Credit.`); return; }
      if (!t.billing_cycle) { setError(`${ch}: pick a billing cycle.`); return; }
      const numeric: [keyof TermsDraft, string][] = [
        ["credit_limit", "Limit"], ["deposit_amount", "Deposit"], ["usage_percent", "Usage %"],
      ];
      for (const [key, label] of numeric) {
        const raw = t[key].trim();
        if (!raw) continue;
        if (!Number.isFinite(Number(raw))) { setError(`${ch}: ${label} must be a number.`); return; }
        if (Number(raw) < 0) { setError(`${ch}: ${label} cannot be negative.`); return; }
      }
      if (t.agency_type === "cash" && !t.deposit_amount.trim()) {
        setError(`${ch} is cash — enter the deposit amount.`); return;
      }
      if (t.agency_type === "credit" && !t.credit_limit.trim()) {
        setError(`${ch} is credit — enter the credit limit.`); return;
      }
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      payloadTerms.push({
        channel: ch,
        agency_type: t.agency_type,
        billing_cycle: t.billing_cycle,
        credit_limit: num(t.credit_limit),
        deposit_amount: num(t.deposit_amount),
        usage_percent: num(t.usage_percent),
      });
    }

    setSaving(true); setError("");
    try {
      const { data } = await api.post<AgencyRow>("/agencies/", {
        name: form.name.trim(),
        supplier_id: supplierId,
        branch_code: form.branch_code.trim(),
        branch_name: form.branch_name || null,
        address: form.address || null,
        ...taxFields,
        city: form.city || null,
        region_chapter: form.region_chapter || null,
        contact_phone: form.contact_phone || null,
        contact_email: form.contact_email || null,
        notes: form.notes || null,
        is_active: form.is_active,
        channels,
        terms: payloadTerms,
      });
      setCreated(data);
      onRefresh();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMulti = async () => {
    if (picked.size === 0) { setError("Select at least one agency."); return; }
    const t = terms.GDS;
    if (!t.agency_type || !t.billing_cycle) { setError("Set the terms every selected agency will get."); return; }
    if (t.agency_type === "cash" && !t.deposit_amount.trim()) { setError("Cash — enter the deposit amount."); return; }
    if (t.agency_type === "credit" && !t.credit_limit.trim()) { setError("Credit — enter the credit limit."); return; }

    setSaving(true); setError(""); setResult(null);
    const num = (v: string) => (v.trim() === "" ? null : Number(v));
    try {
      const { data } = await api.post<{ created: number; skipped: number }>(
        "/agencies/from-suppliers", {
          supplier_ids: Array.from(picked),
          channels: multiChannel,
          terms: channelsOf(multiChannel).map(ch => ({
            channel: ch,
            agency_type: t.agency_type,
            billing_cycle: t.billing_cycle,
            credit_limit: num(t.credit_limit),
            deposit_amount: num(t.deposit_amount),
            usage_percent: num(t.usage_percent),
          })),
        });
      setResult(data);
      setPicked(new Set());
      if (data.created > 0) onRefresh();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const vendorRows = useMemo(
    () => vendorNames.map(n => vendors.get(n)![0]),
    [vendorNames, vendors],
  );
  const filteredVendors = pickSearch.trim()
    ? vendorRows.filter(s => s.name.toLowerCase().includes(pickSearch.trim().toLowerCase()))
    : vendorRows;

  /** The terms block, rendered once per declared channel. */
  const termsBlock = (ch: Channel, heading: string) => {
    const t = terms[ch];
    return (
      <div key={ch} className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-3">
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide">{heading}</p>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>Type *</label>
            <select value={t.agency_type} onChange={e => setAgencyType(ch, e.target.value)} className={INPUT}>
              <option value="">— Select —</option>
              {AGENCY_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>
          <div><label className={LABEL}>Billing Cycle *</label>
            <select value={t.billing_cycle} onChange={e => setTerm(ch, "billing_cycle", e.target.value)} className={INPUT}>
              <option value="">— Select —</option>
              {BILLING_CYCLES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
        </div>

        {t.agency_type === "cash" && (
          <>
            <div><label className={LABEL}>Deposit (₹) *</label>
              <input type="number" min="0" value={t.deposit_amount}
                onChange={e => setTerm(ch, "deposit_amount", e.target.value)}
                placeholder="e.g. 10000000" className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">In cash the limit is the deposit — the agency pays first, so its balance is the money in.</p>
            </div>
            <div><label className={LABEL}>Usage %</label>
              <input type="number" min="0" value={t.usage_percent}
                onChange={e => setTerm(ch, "usage_percent", e.target.value)}
                placeholder="e.g. 90" className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">Notify once this share of the deposit is used. May go above 100 — 110 warns after they run 10% past it.</p>
            </div>
          </>
        )}

        {t.agency_type === "credit" && (
          <div><label className={LABEL}>Limit (₹) *</label>
            <input type="number" min="0" value={t.credit_limit}
              onChange={e => setTerm(ch, "credit_limit", e.target.value)}
              placeholder="e.g. 5000000" className={INPUT} />
            <p className="text-[10px] text-gray-400 mt-1">On credit the limit stands on its own — invoices go out on the billing cycle.</p>
          </div>
        )}
      </div>
    );
  };

  // ── after a successful create ──────────────────────────────────────────
  // The channel this branch is NOT yet on, if there is one. Null for a legacy
  // BOTH row, which already covers everything.
  const otherChannel: Channel | null =
    created && created.channels !== "BOTH" ? (created.channels === "GDS" ? "LCC" : "GDS") : null;

  /** Reopen the form on the other channel with the identity already filled in.
   *  `terms` is keyed by channel, so the block that appears is empty and the one
   *  just submitted is untouched. */
  const addOnOtherChannel = () => {
    if (!otherChannel) return;
    setChannels(otherChannel);
    setCreated(null);
    setError("");
  };

  if (created) {
    return (
      <ModalShell title="Agency added" onClose={onSaved}>
        <div className="space-y-4">
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2.5">
            <p className="text-[12px] font-semibold text-green-800">
              {created.name} · {created.branch_name || created.branch_code} added.
            </p>
            <p className="text-[11px] text-green-700 mt-0.5">
              {channelsOf(created.channels).map(c => {
                const t = created.terms.find(x => x.channel === c);
                return t ? `${c} ${t.agency_type}` : c;
              }).join(" · ")}
            </p>
          </div>
          {/* The other channel is a SECOND agency, not a setting on this one — so
              offer to add it here, carrying the identity across. Retyping the
              state, PAN and GSTIN of the branch just onboarded is the friction
              that made a "Both" card look necessary in the first place. */}
          {otherChannel && (
            <button onClick={addOnOtherChannel}
              className="w-full flex items-center justify-center gap-1.5 border border-sky-200 bg-sky-50 rounded-lg py-2.5 text-xs font-semibold text-sky-700 hover:bg-sky-100">
              Also add {created.name} on {otherChannel} <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}

          <p className="text-[11px] text-gray-500">
            Next, give it the branches it books from and the credentials it books with.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => onGoTo?.("entities", created.id)} disabled={!onGoTo}
              className="flex items-center justify-center gap-1.5 border border-gray-200 rounded-lg py-2.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-40">
              Add Entities <ArrowRight className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => onGoTo?.("logins", created.id)} disabled={!onGoTo}
              className="flex items-center justify-center gap-1.5 border border-gray-200 rounded-lg py-2.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-40">
              Add Login IDs <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <button onClick={onSaved} className="w-full text-white rounded-lg py-2 text-sm font-semibold"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>Done</button>
        </div>
      </ModalShell>
    );
  }

  const manualForm = (
    <div className="space-y-3">
      {!isEdit && (
        <>
          {/* Channel first — it decides which terms block appears below, and it is
              part of what makes this row unique. The same branch can be added
              again on the other channel; it becomes a second agency. */}
          <div>
            <label className={LABEL}>Channel *</label>
            <div className="grid grid-cols-2 gap-2">
              {CHANNEL_CHOICES.map(c => (
                <button key={c.value} type="button" onClick={() => setChannels(c.value)}
                  className={`rounded-lg border px-2 py-2 text-center transition ${
                    channels === c.value
                      ? "border-sky-500 bg-sky-50 ring-1 ring-sky-400"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}>
                  <span className={`block text-[12px] font-bold ${channels === c.value ? "text-sky-700" : "text-gray-700"}`}>{c.label}</span>
                  <span className="block text-[9px] leading-tight text-gray-400 mt-0.5">{c.hint}</span>
                </button>
              ))}
            </div>
            <p className="text-[10px] text-gray-400 mt-1">
              Works both? Add it on one channel, then add it again on the other — each keeps
              its own terms, deposit and balance.
            </p>
          </div>

          <div>
            <label className={LABEL}>Agency *</label>
            <SearchSelect value={vendorName} options={vendorNames} onChange={pickVendor}
              placeholder="Search and select an agency" />
            <p className="text-[10px] text-gray-400 mt-1">Details below are filled in from the master and stay editable.</p>
          </div>

          {branches.length > 0 && (
            <div>
              <label className={LABEL}>Branch *</label>
              <select value={supplierId ?? ""} onChange={e => {
                const s = branches.find(b => b.id === Number(e.target.value));
                if (s) applyBranch(s);
              }} disabled={branches.length === 1} className={branches.length === 1 ? `${INPUT} bg-gray-100 text-gray-500` : INPUT}>
                {branches.map(b => <option key={b.id} value={b.id}>{branchLabel(b)}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">
                {branches.length === 1
                  ? "This agency has one branch on record."
                  : `${branches.length} branches on record — each is onboarded separately, with its own terms and balance.`}
              </p>
            </div>
          )}
        </>
      )}

      <div><label className={LABEL}>Agency Name *</label>
        <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Lords Travels" className={INPUT} /></div>

      <div><label className={LABEL}>Address</label>
        <input value={form.address} onChange={e => set("address", e.target.value)} placeholder="e.g. 12 Connaught Place" className={INPUT} />
        <p className="text-[10px] text-gray-400 mt-1">This branch&apos;s address. Entities added under it start from this address, state and city.</p></div>

      <div className="grid grid-cols-3 gap-3">
        {/* A picker rather than free text, because this value has to resolve to a
            GST state code — "Delhi" typed three different ways cannot check a
            GSTIN's first two characters. */}
        <div><label className={LABEL}>State *</label>
          {/* Highlighted only once a save has failed — a fresh form is empty, not wrong. */}
          <SearchSelect value={form.state} options={STATE_NAMES} onChange={v => set("state", v)}
            placeholder="Select state" invalid={!form.state && !!error} />
        </div>
        <div><label className={LABEL}>City</label>
          <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. MUMBAI" className={INPUT} /></div>
        <div><label className={LABEL}>Region / Chapter</label>
          <input value={form.region_chapter} onChange={e => set("region_chapter", e.target.value)} placeholder="e.g. WESTERN REGION" className={INPUT} /></div>
      </div>
      {isEdit && agency?.state && !form.state ? (
        // The row predates the picker and holds something that is not a state —
        // often an IATA chapter copied from the master. Say what was there rather
        // than showing an empty box the user has to guess at.
        <p className="text-[10px] text-amber-600 -mt-1">
          This agency was saved with &quot;{agency.state}&quot;, which is not a state a GSTIN can be
          checked against. Pick the real one.
        </p>
      ) : (
        <p className="text-[10px] text-gray-400 -mt-1">
          The state decides the first two characters of this agency&apos;s GSTIN, so it is required
          even when the agency is not registered.
        </p>
      )}

      {/* ── Tax ids, in the order they can be checked ──────────────────────
          PAN first (it fixes characters 3-12 of the GSTIN), then whether the
          agency is registered at all, and only then the GSTIN itself. */}
      <div><label className={LABEL}>PAN Number</label>
        <input value={form.pan_number}
          onChange={e => set("pan_number", normaliseTaxId(e.target.value))}
          placeholder="e.g. AAPFU0939F" maxLength={10}
          className={`${INPUT} font-mono uppercase tracking-wider ${panProblem ? "border-red-300 bg-red-50" : ""}`} />
        {panProblem && <p className="text-[10px] text-red-500 mt-1">{panProblem}</p>}
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={form.gst_registered}
            onChange={e => {
              set("gst_registered", e.target.checked);
              // Clear the number when the answer becomes "no" — leaving it behind
              // would post a GSTIN for an agency just declared unregistered.
              if (!e.target.checked) set("gst_number", "");
            }}
            className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
          <span className="text-xs font-semibold text-gray-700">Is this agency GST registered?</span>
        </label>

        {form.gst_registered && (
          <div>
            <label className={LABEL}>GST Number *</label>
            <input value={form.gst_number}
              onChange={e => set("gst_number", normaliseTaxId(e.target.value))}
              placeholder={gstinPlaceholder(form.state, form.pan_number)} maxLength={15}
              className={`${INPUT} font-mono uppercase tracking-wider ${gstProblem ? "border-red-300 bg-red-50" : ""}`} />
            {gstProblem
              ? <p className="text-[10px] text-red-500 mt-1">{gstProblem}</p>
              : <p className="text-[10px] text-gray-400 mt-1">
                  Checked against the state above (first two characters), the PAN (characters 3 to 12)
                  and its own check digit — no lookup needed.
                </p>}
          </div>
        )}
      </div>
      {!isEdit && (
        <p className="text-[10px] text-gray-400 -mt-1">The master holds no GST, PAN or state, so enter those yourself.</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>Phone</label>
          <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)} placeholder="Contact phone" className={INPUT} /></div>
        <div><label className={LABEL}>Email</label>
          <input value={form.contact_email} onChange={e => set("contact_email", e.target.value)} placeholder="Contact email" className={INPUT} /></div>
      </div>

      {/* ── Commercial terms, one block per declared channel ──────────────── */}
      {!isEdit && (
        <div className="border-t border-gray-100 pt-3 space-y-3">
          {channelsOf(channels).map(ch => termsBlock(ch, `${ch} terms`))}
        </div>
      )}

      {isEdit && (
        <div className="border-t border-gray-100 pt-3">
          <p className="text-[11px] text-gray-500">
            Commercial terms, deposits and channels are managed on the{" "}
            <a href={`/user-master/agency-master/${agency!.id}`} className="font-semibold text-sky-600 hover:underline">Account page</a>
            {" "}— changing them has to close one arrangement and open another at a settled balance.
          </p>
        </div>
      )}

      <div><label className={LABEL}>Notes</label>
        <input value={form.notes} onChange={e => set("notes", e.target.value)} placeholder="Remarks" className={INPUT} /></div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
        <span className="text-xs font-semibold text-gray-600">Active</span>
      </label>

      {error && <p className="text-[11px] text-red-500">{error}</p>}

      <div className="flex gap-3 pt-1">
        <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        <button onClick={saveSingle} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Create Agency"}
        </button>
      </div>
    </div>
  );

  return (
    <ModalShell title={isEdit ? "Edit Agency" : "Add Agency"} onClose={onClose} wide>
      {!isEdit && (
        <div className="flex border-b border-gray-100 mb-4 -mt-1">
          {([["single", "Add Agency"], ["multi", "Bulk Add"], ["xls", "Upload XLS"]] as const).map(([t, lbl]) => (
            <button key={t} onClick={() => { setTab(t); setError(""); }}
              className={`flex-1 py-2.5 text-[11px] font-semibold ${tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400"}`}>
              {lbl}
            </button>
          ))}
        </div>
      )}

      {isEdit || tab === "single" ? manualForm
        : tab === "multi" ? (
          <div className="space-y-3">
            <p className="text-[11px] text-gray-500">
              Pick the agencies you work with — each becomes an agency on its first branch, on the channel
              and terms below. Branches already added on that channel are skipped, so running this again
              on the other channel onboards the same set there too.
            </p>
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              The master holds no state, PAN or GST — it has IATA regions like &quot;WESTERN REGION&quot;, not states.
              Agencies added here start without them and need editing before a GSTIN can be verified.
            </p>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={pickSearch} onChange={e => setPickSearch(e.target.value)} placeholder="Search agencies…"
                className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400" />
            </div>
            <div className="max-h-52 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-50">
              {filteredVendors.length === 0 ? (
                <p className="px-3 py-6 text-center text-[11px] text-gray-400">No agencies found.</p>
              ) : filteredVendors.map(s => {
                const count = vendors.get(s.name)?.length ?? 1;
                return (
                  <label key={s.id} className="flex items-center gap-2 px-3 py-2 hover:bg-sky-50/40 cursor-pointer">
                    <input type="checkbox" checked={picked.has(s.id)}
                      onChange={e => setPicked(p => { const n = new Set(p); if (e.target.checked) n.add(s.id); else n.delete(s.id); return n; })}
                      className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
                    <span className="text-[11px] font-semibold text-gray-700">{s.name}</span>
                    {s.city && <span className="text-[10px] text-gray-400">{s.city}</span>}
                    {count > 1 && <span className="text-[10px] text-gray-400">· {count} branches</span>}
                  </label>
                );
              })}
            </div>

            <div>
              <label className={LABEL}>Channel *</label>
              <div className="grid grid-cols-2 gap-2">
                {CHANNEL_CHOICES.map(c => (
                  <button key={c.value} type="button" onClick={() => setMultiChannel(c.value)}
                    className={`rounded-lg border px-2 py-1.5 text-[11px] font-bold transition ${
                      multiChannel === c.value
                        ? "border-sky-500 bg-sky-50 text-sky-700 ring-1 ring-sky-400"
                        : "border-gray-200 text-gray-600 hover:bg-gray-50"
                    }`}>{c.label}</button>
                ))}
              </div>
            </div>
            {termsBlock("GDS", "Terms applied to every selected agency")}

            {result && (
              <div className="rounded-lg border bg-green-50 border-green-200 px-3 py-2 text-[11px] text-green-700">
                {result.created} agenc{result.created === 1 ? "y" : "ies"} added{result.skipped > 0 ? `, ${result.skipped} skipped (already added or unavailable)` : ""}.
              </div>
            )}
            {error && <p className="text-[11px] text-red-500">{error}</p>}

            <div className="flex gap-3 pt-1">
              <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Close</button>
              <button onClick={saveMulti} disabled={saving || picked.size === 0} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                {saving ? "Adding…" : `Add ${picked.size || ""} Agenc${picked.size === 1 ? "y" : "ies"}`.replace("  ", " ")}
              </button>
            </div>
          </div>
        ) : (
          // One row per agency PER CHANNEL — CHANNELS is GDS or LCC, and a branch
          // that works both gets two rows. STATE is required on every row: the
          // GSTIN is checked against it.
          <UploadBox resource="agencies" templateName="agency_template.xlsx"
            columns="NAME, BRANCH_CODE, BRANCH_NAME, ADDRESS, STATE, CITY, REGION, PAN, GST_REGISTERED, GST, PHONE, EMAIL, NOTES, CHANNELS, GDS_TYPE, GDS_LIMIT, GDS_DEPOSIT, GDS_USAGE_PCT, GDS_BILLING_CYCLE, LCC_TYPE, LCC_LIMIT, LCC_DEPOSIT, LCC_USAGE_PCT, LCC_BILLING_CYCLE, ACTIVE"
            onDone={onSaved} />
        )}
    </ModalShell>
  );
}
