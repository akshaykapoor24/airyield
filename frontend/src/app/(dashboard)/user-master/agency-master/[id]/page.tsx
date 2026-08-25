"use client";

// Agency account — the money side of an agency, as opposed to Agency Master
// which is who they are. Three tabs: Overview (balance + terms + the switch),
// Ledger (every payment, append-only), Cycles (billing periods).
//
// EVERYTHING HERE IS PER CHANNEL. An agency that is cash on GDS and credit on
// LCC has two limits, two cycles and two balances, so a channel pill row sits
// ABOVE the tabs rather than folding into them — the channel is orthogonal to
// Overview/Ledger/Cycles, and merging the two would give six combinations.

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle, ArrowLeft, BookOpen, CalendarRange, Plus,
  RefreshCw, RotateCcw, Wallet,
} from "lucide-react";
import api from "@/lib/api";
import { INPUT, LABEL, apiError, ModalShell } from "@/components/userMaster/shared";

type Settlement = { direction: string; amount: number; options: string[]; message: string };

type Account = {
  agency_id: number; agency_name: string; branch_name: string | null;
  agency_channels: string; channel: string;
  agency_type: string | null; billing_cycle: string | null;
  cycle_anchor_date: string | null; terms_id: number | null; effective_from: string | null;
  balance: number; paid_in: number; billed: number;
  limit: number | null; available: number | null;
  used_percent: number | null; usage_threshold: number | null; threshold_breached: boolean;
  unbilled_exposure: number; unbilled_exposure_scope: string;
  is_settled: boolean; settlement: Settlement | null;
};

type Entry = {
  id: number; channel: string; entry_date: string; entry_type: string; amount: number; balance_after: number;
  billing_id: number | null; payment_mode: string | null; reference_no: string | null;
  note: string | null; reversal_of_id: number | null; is_reversed: boolean;
};

type Terms = {
  id: number; channel: string; effective_from: string; effective_to: string | null;
  agency_type: string; credit_limit: number | null; usage_percent: number | null;
  billing_cycle: string; cycle_anchor_date: string; note: string | null;
};

type Cycle = {
  seq: number; period_from: string; period_to: string; elapsed: boolean; status: string;
  billing_id: number | null; billing_name: string | null; billed_amount: number | null;
};

type Blocker = { code: string; message: string; settlement: Settlement | null };

const TABS = [
  { key: "overview", label: "Overview", icon: Wallet },
  { key: "ledger", label: "Ledger", icon: BookOpen },
  { key: "cycles", label: "Cycles", icon: CalendarRange },
] as const;

const PAYMENT_MODES = ["neft", "rtgs", "imps", "upi", "cheque", "cash", "card", "other"];
const CYCLES = ["weekly", "fortnightly", "monthly"];
const AGENCY_TYPES = ["cash", "credit"];

/** Which single channels a declared scope covers. */
const channelsOf = (scope: string | undefined): string[] =>
  scope === "BOTH" ? ["GDS", "LCC"] : scope ? [scope] : [];

const money = (v: number | null | undefined) =>
  v == null ? "—" : `${v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const title = (v: string | null | undefined) =>
  !v ? "—" : v.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

const fmtDate = (v: string | null | undefined) =>
  !v ? "—" : new Date(v + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

export default function AgencyAccountPage() {
  const params = useParams();
  const router = useRouter();
  const agencyId = Number(params?.id);

  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("overview");
  const [account, setAccount] = useState<Account | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [terms, setTerms] = useState<Terms[]>([]);
  const [cycles, setCycles] = useState<Cycle[]>([]);
  const [blockers, setBlockers] = useState<Blocker[]>([]);
  const [canSwitch, setCanSwitch] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [entryModal, setEntryModal] = useState<string | null>(null);   // the entry_type being posted
  const [switchModal, setSwitchModal] = useState(false);
  const [openModal, setOpenModal] = useState(false);   // open a new channel
  // "" until the first load tells us what this agency trades on. The API refuses
  // to guess for a BOTH agency, so we must send one from then on.
  const [channel, setChannel] = useState("");

  const load = useCallback(async () => {
    if (!Number.isFinite(agencyId)) return;
    setLoading(true); setErr("");
    const p = channel ? { params: { channel } } : undefined;
    try {
      // The account call resolves the channel for a single-channel agency, so it
      // goes first and its answer drives the rest.
      const a = await api.get<Account>(`/agencies/${agencyId}/account`, p);
      const ch = a.data.channel;
      if (ch !== channel) setChannel(ch);
      const q = { params: { channel: ch } };
      const [l, t, c, s] = await Promise.all([
        api.get<Entry[]>(`/agencies/${agencyId}/ledger`, q),
        api.get<Terms[]>(`/agencies/${agencyId}/terms`),   // all channels — this is history
        api.get<Cycle[]>(`/agencies/${agencyId}/cycles`, q),
        api.get<{ can_switch: boolean; blockers: Blocker[] }>(`/agencies/${agencyId}/switch-preview`, q),
      ]);
      setAccount(a.data); setEntries(l.data); setTerms(t.data); setCycles(c.data);
      setCanSwitch(s.data.can_switch); setBlockers(s.data.blockers ?? []);
    } catch (e) {
      // A BOTH agency with no channel yet: pick the first and try again.
      const detail = apiError(e);
      if (!channel && detail.includes("GDS")) { setChannel("GDS"); return; }
      setErr(detail);
    }
    finally { setLoading(false); }
  }, [agencyId, channel]);

  useEffect(() => { load(); }, [load]);

  const reverse = async (id: number) => {
    if (!confirm("Reverse this entry? A cancelling entry is posted — the original stays on the statement.")) return;
    try { await api.post(`/agencies/${agencyId}/ledger/${id}/reverse`); load(); }
    catch (e) { alert(apiError(e)); }
  };

  const closeChannel = async () => {
    if (!account) return;
    if (!confirm(`Stop trading with this agency on ${account.channel}? Its arrangement is closed; the other channel is untouched.`)) return;
    try {
      await api.post(`/agencies/${agencyId}/channels/close`, { channel: account.channel });
      setChannel("");   // reload will resolve whichever channel remains
      load();
    } catch (e) { alert(apiError(e)); }
  };

  // Settling is just a ledger entry, so the blocker offers the exact one needed.
  const settleOptions = account?.settlement?.options ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <button onClick={() => router.push("/user-master/agency-master")} className="mt-1 p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50">
            <ArrowLeft className="w-4 h-4 text-gray-600" />
          </button>
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Agency Account</p>
            <h2 className="text-lg font-bold text-gray-900">
              {account?.agency_name ?? "Agency"}
              {account?.branch_name && <span className="text-gray-400 font-semibold"> · {account.branch_name}</span>}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {account?.agency_type
                ? `${account.channel} · ${title(account.agency_type)} · ${title(account.billing_cycle)} cycle from ${fmtDate(account.cycle_anchor_date)}`
                : `No ${account?.channel ?? "commercial"} terms set yet.`}
            </p>
          </div>
        </div>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {err && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg">{err}</div>}

      {account && (
        <div className="flex items-center gap-2">
          {channelsOf(account.agency_channels).map(c => (
            <button key={c} onClick={() => { setChannel(c); }}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-bold border transition ${
                account.channel === c
                  ? "bg-[#1e4d8c] text-white border-[#1e4d8c]"
                  : "bg-white text-gray-500 border-gray-200 hover:bg-gray-50"
              }`}>{c}</button>
          ))}
          {account.agency_channels !== "BOTH" && (
            <button onClick={() => setOpenModal(true)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold text-sky-600 border border-dashed border-sky-300 hover:bg-sky-50">
              <Plus className="w-3 h-3" /> Add {account.agency_channels === "GDS" ? "LCC" : "GDS"}
            </button>
          )}
          <span className="text-[10px] text-gray-400 ml-1">
            {account.agency_channels === "BOTH"
              ? "Separate balance, limit and cycle per channel."
              : `This agency trades on ${account.agency_channels} only.`}
          </span>
        </div>
      )}

      <div className="flex items-center gap-1 border-b border-gray-200">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-colors ${
              tab === t.key ? "border-[#1e4d8c] text-[#1e4d8c]" : "border-transparent text-gray-400 hover:text-gray-600"
            }`}>
            <t.icon className="w-3.5 h-3.5" /> {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && account && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label={account.balance >= 0 ? "Balance (in credit)" : "Outstanding"}
              value={money(Math.abs(account.balance))}
              tone={account.balance < 0 ? "warn" : "good"} />
            <Stat label={account.agency_type === "cash" ? "Deposited" : "Credit limit"} value={money(account.limit)} />
            <Stat label="Available" value={money(account.available)}
              tone={account.available != null && account.available <= 0 ? "warn" : "plain"} />
            <Stat label="Billed to date" value={money(account.billed)} />
          </div>

          {account.used_percent != null && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-gray-600">
                  {account.used_percent.toFixed(1)}% used
                  {account.usage_threshold != null && <span className="text-gray-400 font-normal"> · notify at {account.usage_threshold}%</span>}
                </span>
                {account.threshold_breached && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
                    <AlertTriangle className="w-3 h-3" /> Threshold reached
                  </span>
                )}
              </div>
              <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                <div className={`h-full rounded-full ${account.threshold_breached ? "bg-amber-500" : "bg-[#1e4d8c]"}`}
                  style={{ width: `${Math.min(100, Math.max(0, account.used_percent))}%` }} />
              </div>
              {account.unbilled_exposure > 0 && (
                <p className="text-[10px] text-gray-400 mt-2">
                  {money(account.unbilled_exposure)} of tickets are not billed yet — not counted above
                  {account.unbilled_exposure_scope === "agency" && ", and across ALL channels: ticket data does not record GDS/LCC"}.
                </p>
              )}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-gray-800">Change {account.channel} agency type</h3>
              <button onClick={() => setSwitchModal(true)} disabled={!canSwitch}
                className="text-white rounded-lg px-3.5 py-2 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                Switch {account.agency_type === "cash" ? "to Credit" : account.agency_type === "credit" ? "to Cash" : "type"}
              </button>
            </div>
            {canSwitch ? (
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-emerald-600">
                  {account.channel} cycle closed and balance settled — this channel can switch.
                </p>
                {account.agency_channels === "BOTH" && (
                  <button onClick={closeChannel}
                    className="border border-gray-200 rounded-lg px-2.5 py-1 text-[10px] font-semibold text-red-500 hover:bg-red-50 whitespace-nowrap">
                    Stop trading on {account.channel}
                  </button>
                )}
              </div>
            ) : (
              <ul className="space-y-2">
                {blockers.map((b, i) => (
                  <li key={i} className="flex items-start justify-between gap-3 text-[11px] text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                    <span className="flex items-start gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-px" /> {b.message}
                    </span>
                    {b.settlement && (
                      <span className="flex gap-1.5 shrink-0">
                        {b.settlement.options.map(o => (
                          <button key={o} onClick={() => setEntryModal(o)}
                            className="border border-gray-200 bg-white rounded-lg px-2 py-1 text-[10px] font-semibold hover:bg-gray-50 whitespace-nowrap">
                            {o === "receipt" ? "Record receipt" : o === "refund" ? "Refund" : "Adjust off"}
                          </button>
                        ))}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <p className="px-4 py-2.5 text-xs font-bold text-gray-800 border-b border-gray-100">Terms history</p>
            <table className="w-full">
              <thead><tr style={{ background: "#1e4d8c" }}>
                {["CHANNEL", "FROM", "TO", "TYPE", "LIMIT", "USAGE %", "CYCLE", "NOTE"].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-white uppercase tracking-wider">{h}</th>))}
              </tr></thead>
              <tbody>
                {terms.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-8 text-center text-xs text-gray-400">No terms recorded yet.</td></tr>
                ) : terms.map((t, i) => (
                  <tr key={t.id} className={`border-b border-gray-50 ${i % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                        t.channel === "GDS" ? "bg-sky-50 text-sky-700 border-sky-200" : "bg-violet-50 text-violet-700 border-violet-200"
                      }`}>{t.channel}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-700">{fmtDate(t.effective_from)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{t.effective_to ? fmtDate(t.effective_to) : <span className="text-emerald-600 font-semibold">Current</span>}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{title(t.agency_type)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{money(t.credit_limit)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{t.usage_percent ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{title(t.billing_cycle)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-400">{t.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "ledger" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {(["topup", "receipt", "refund", "adjustment", "opening_balance"] as const).map(t => (
              <button key={t} onClick={() => setEntryModal(t)}
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3 py-1.5 rounded-lg text-[11px] font-semibold hover:bg-gray-50">
                <Plus className="w-3 h-3" /> {title(t)}
              </button>
            ))}
            {settleOptions.length > 0 && (
              <span className="ml-auto text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
                {account?.settlement?.message}
              </span>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden overflow-x-auto">
            <table className="w-full">
              <thead><tr style={{ background: "#1e4d8c" }}>
                {["DATE", "TYPE", "REFERENCE", "NOTE", "AMOUNT", "BALANCE", ""].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">{h}</th>))}
              </tr></thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
                ) : entries.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">No payments recorded yet. Record a top-up to open the account.</td></tr>
                ) : entries.map((e, i) => (
                  <tr key={e.id} className={`border-b border-gray-50 ${i % 2 ? "bg-gray-50/30" : "bg-white"} ${e.is_reversed ? "opacity-50" : ""}`}>
                    <td className="px-3 py-2 text-[11px] text-gray-700 whitespace-nowrap">{fmtDate(e.entry_date)}</td>
                    <td className="px-3 py-2">
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-gray-50 text-gray-600 border-gray-200">{title(e.entry_type)}</span>
                      {e.is_reversed && <span className="ml-1 text-[10px] text-red-400">reversed</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">
                      {e.payment_mode ? `${e.payment_mode.toUpperCase()} ` : ""}{e.reference_no ?? (e.billing_id ? `Billing #${e.billing_id}` : "—")}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-500 max-w-64 truncate" title={e.note ?? ""}>{e.note ?? "—"}</td>
                    <td className={`px-3 py-2 text-[11px] font-semibold whitespace-nowrap ${e.amount < 0 ? "text-red-500" : "text-emerald-600"}`}>{money(e.amount)}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-700 whitespace-nowrap">{money(e.balance_after)}</td>
                    <td className="px-3 py-2">
                      {!e.is_reversed && e.entry_type !== "reversal" && (
                        <button onClick={() => reverse(e.id)} className="p-1.5 hover:bg-red-50 rounded-lg text-gray-300 hover:text-red-500" title="Reverse this entry">
                          <RotateCcw className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "cycles" && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead><tr style={{ background: "#1e4d8c" }}>
              {["#", "PERIOD", "STATUS", "BILLING", "AMOUNT"].map(h => (
                <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider">{h}</th>))}
            </tr></thead>
            <tbody>
              {cycles.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-12 text-center text-xs text-gray-400">No cycles yet — set the agency type to start the clock.</td></tr>
              ) : cycles.map((c, i) => (
                <tr key={c.seq} className={`border-b border-gray-50 ${i % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                  <td className="px-3 py-2 text-[11px] text-gray-500">{c.seq}</td>
                  <td className="px-3 py-2 text-[11px] text-gray-700">{fmtDate(c.period_from)} – {fmtDate(c.period_to)}</td>
                  <td className="px-3 py-2">
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                      c.status === "billed" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : c.status === "unbilled" ? "bg-amber-50 text-amber-700 border-amber-200"
                      : "bg-gray-50 text-gray-500 border-gray-200"}`}>{title(c.status)}</span>
                  </td>
                  <td className="px-3 py-2 text-[11px] text-gray-600">{c.billing_name ?? "—"}</td>
                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{money(c.billed_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {entryModal && account && (
        <EntryModal agencyId={agencyId} channel={account.channel} entryType={entryModal}
          suggested={account?.settlement ?? null}
          onClose={() => setEntryModal(null)} onSaved={() => { setEntryModal(null); load(); }} />
      )}
      {switchModal && account && (
        <SwitchModal agencyId={agencyId} channel={account.channel} currentType={account.agency_type}
          onClose={() => setSwitchModal(false)} onSaved={() => { setSwitchModal(false); load(); }} />
      )}
      {openModal && account && (
        <OpenChannelModal agencyId={agencyId}
          channel={account.agency_channels === "GDS" ? "LCC" : "GDS"}
          onClose={() => setOpenModal(false)}
          onSaved={ch => { setOpenModal(false); setChannel(ch); }} />
      )}
    </div>
  );
}

function Stat({ label, value, tone = "plain" }: { label: string; value: string; tone?: "plain" | "good" | "warn" }) {
  const color = tone === "warn" ? "text-amber-600" : tone === "good" ? "text-emerald-600" : "text-gray-900";
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-3.5">
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-base font-bold ${color}`}>{value}</p>
    </div>
  );
}

function EntryModal({
  agencyId, channel, entryType, suggested, onClose, onSaved,
}: {
  agencyId: number;
  channel: string; entryType: string; suggested: Settlement | null;
  onClose: () => void; onSaved: () => void;
}) {
  // When this modal was opened from a blocker, pre-fill the exact amount that
  // settles the account — that is the whole point of the settlement plan.
  const prefill = suggested && suggested.options.includes(entryType) ? String(suggested.amount) : "";
  const [amount, setAmount] = useState(prefill);
  const [entryDate, setEntryDate] = useState(new Date().toISOString().slice(0, 10));
  const [mode, setMode] = useState("");
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const needsMode = entryType === "topup" || entryType === "receipt" || entryType === "refund";

  const save = async () => {
    if (!amount.trim() || !Number.isFinite(Number(amount)) || Number(amount) <= 0) {
      setError("Enter an amount greater than zero."); return;
    }
    setSaving(true); setError("");
    try {
      await api.post(`/agencies/${agencyId}/ledger`, {
        entry_type: entryType,
        channel,
        amount: Number(amount),
        entry_date: entryDate,
        payment_mode: mode || null,
        reference_no: ref.trim() || null,
        note: note.trim() || null,
      });
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={`${title(entryType)} · ${channel}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-[11px] text-gray-500">
          {entryType === "topup" && "Money received from the agency into their deposit."}
          {entryType === "receipt" && "Payment received against an outstanding invoice."}
          {entryType === "refund" && "Unused deposit paid back out to the agency."}
          {entryType === "adjustment" && "Write an amount off or back on, without money moving."}
          {entryType === "opening_balance" && "Bring an already-trading agency on board with its starting balance."}
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>Amount (₹) *</label>
            <input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)} className={INPUT} /></div>
          <div><label className={LABEL}>Date</label>
            <input type="date" value={entryDate} onChange={e => setEntryDate(e.target.value)} className={INPUT} /></div>
        </div>
        {needsMode && (
          <div className="grid grid-cols-2 gap-3">
            <div><label className={LABEL}>Payment Mode</label>
              <select value={mode} onChange={e => setMode(e.target.value)} className={INPUT}>
                <option value="">— Select —</option>
                {PAYMENT_MODES.map(m => <option key={m} value={m}>{m.toUpperCase()}</option>)}
              </select></div>
            <div><label className={LABEL}>Reference No</label>
              <input value={ref} onChange={e => setRef(e.target.value)} placeholder="UTR / cheque no" className={INPUT} /></div>
          </div>
        )}
        <div><label className={LABEL}>Note</label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Remarks" className={INPUT} /></div>
        {error && <p className="text-[11px] text-red-500">{error}</p>}
        <div className="flex gap-3 pt-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Posting…" : `Post ${title(entryType)}`}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

function SwitchModal({
  agencyId, channel, currentType, onClose, onSaved,
}: {
  agencyId: number;
  channel: string; currentType: string | null; onClose: () => void; onSaved: () => void;
}) {
  const target = currentType === "cash" ? "credit" : "cash";
  const [agencyType, setAgencyType] = useState(target);
  const [cycle, setCycle] = useState("monthly");
  const [limit, setLimit] = useState("");
  const [usage, setUsage] = useState("");
  const [effective, setEffective] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setSaving(true); setError("");
    try {
      await api.post(`/agencies/${agencyId}/switch`, {
        agency_type: agencyType,
        channel,
        billing_cycle: cycle,
        credit_limit: agencyType === "credit" && limit.trim() ? Number(limit) : null,
        usage_percent: agencyType === "cash" && usage.trim() ? Number(usage) : null,
        effective_from: effective,
        note: note.trim() || null,
      });
      onSaved();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={`Change ${channel} agency type`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-[11px] text-gray-500">
          This closes the current arrangement and opens a new one from the date below. The old terms stay on record against everything billed under them.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>New Type</label>
            <select value={agencyType} onChange={e => setAgencyType(e.target.value)} className={INPUT}>
              <option value="cash">Cash</option>
              <option value="credit">Credit</option>
            </select></div>
          <div><label className={LABEL}>Billing Cycle</label>
            <select value={cycle} onChange={e => setCycle(e.target.value)} className={INPUT}>
              {CYCLES.map(c => <option key={c} value={c}>{title(c)}</option>)}
            </select></div>
        </div>
        {agencyType === "credit" ? (
          <div><label className={LABEL}>Credit Limit (₹)</label>
            <input type="number" min="0" value={limit} onChange={e => setLimit(e.target.value)} placeholder="e.g. 5000000" className={INPUT} />
            <p className="text-[10px] text-gray-400 mt-1">Invoices go out on the billing cycle; the limit caps what may be outstanding.</p>
          </div>
        ) : (
          <div><label className={LABEL}>Usage %</label>
            <input type="number" min="0" value={usage} onChange={e => setUsage(e.target.value)} placeholder="e.g. 90" className={INPUT} />
            <p className="text-[10px] text-gray-400 mt-1">On cash the limit is whatever is on deposit — record a top-up to fund the account.</p>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>Effective From</label>
            <input type="date" value={effective} onChange={e => setEffective(e.target.value)} className={INPUT} /></div>
          <div><label className={LABEL}>Note</label>
            <input value={note} onChange={e => setNote(e.target.value)} placeholder="Why the change" className={INPUT} /></div>
        </div>
        {error && <p className="text-[11px] text-red-500">{error}</p>}
        <div className="flex gap-3 pt-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Switching…" : `Switch to ${title(agencyType)}`}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}


/** Start trading with this agency on the channel it did not trade on before.
 *
 * A guarded transition rather than a field edit: it opens a commercial
 * arrangement and, on cash, takes the first deposit. Also the repair path for an
 * agency onboarded on one channel that later needs the other. */
function OpenChannelModal({
  agencyId, channel, onClose, onSaved,
}: {
  agencyId: number;
  channel: string;
  onClose: () => void;
  onSaved: (channel: string) => void;
}) {
  const [agencyType, setAgencyType] = useState("cash");
  const [cycle, setCycle] = useState("monthly");
  const [limit, setLimit] = useState("");
  const [deposit, setDeposit] = useState("");
  const [usage, setUsage] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isCash = agencyType === "cash";

  const save = async () => {
    if (isCash && !deposit.trim()) { setError(`${channel} is cash — enter the deposit amount.`); return; }
    if (!isCash && !limit.trim()) { setError(`${channel} is credit — enter the credit limit.`); return; }
    setSaving(true); setError("");
    try {
      await api.post(`/agencies/${agencyId}/channels/open`, {
        channel,
        agency_type: agencyType,
        billing_cycle: cycle,
        credit_limit: !isCash && limit.trim() ? Number(limit) : null,
        deposit_amount: isCash && deposit.trim() ? Number(deposit) : null,
        usage_percent: isCash && usage.trim() ? Number(usage) : null,
        note: note.trim() || null,
      });
      onSaved(channel);
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <ModalShell title={`Start trading on ${channel}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-[11px] text-gray-500">
          {channel === "GDS"
            ? "The agency will book on your IATA stock through a mirror office, so the BSP liability is yours from the moment of issue."
            : "The agency will book on each airline's own agent portal, settling through that airline's wallet."}
          {" "}This opens a separate arrangement — its own balance, limit and cycle.
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>Type *</label>
            <select value={agencyType} onChange={e => setAgencyType(e.target.value)} className={INPUT}>
              {AGENCY_TYPES.map(t => <option key={t} value={t}>{title(t)}</option>)}
            </select></div>
          <div><label className={LABEL}>Billing Cycle *</label>
            <select value={cycle} onChange={e => setCycle(e.target.value)} className={INPUT}>
              {CYCLES.map(c => <option key={c} value={c}>{title(c)}</option>)}
            </select></div>
        </div>

        {isCash ? (
          <>
            <div><label className={LABEL}>Opening deposit (₹) *</label>
              <input type="number" min="0" value={deposit} onChange={e => setDeposit(e.target.value)} className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">Posted as the first top-up — the limit is read back from the ledger.</p></div>
            <div><label className={LABEL}>Usage %</label>
              <input type="number" min="0" value={usage} onChange={e => setUsage(e.target.value)} placeholder="e.g. 90" className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">Notify once this share of the deposit is used. May go above 100.</p></div>
          </>
        ) : (
          <div><label className={LABEL}>Credit limit (₹) *</label>
            <input type="number" min="0" value={limit} onChange={e => setLimit(e.target.value)} className={INPUT} /></div>
        )}

        <div><label className={LABEL}>Note</label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Why this channel is opening" className={INPUT} /></div>

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-3 pt-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving}
            className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
            {saving ? "Opening…" : `Open ${channel}`}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
