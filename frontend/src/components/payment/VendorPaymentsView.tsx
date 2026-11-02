"use client";

// Vendors data → Payment Module → Vendor Payments: one account per vendor.
//
// A consolidator is paid on account — a lump sum by NEFT / RTGS against its balance — not
// ticket by ticket. So each vendor has an account: its opening balance (when its first
// statement prints one), every statement it billed, what Vendor Mapping holds or claims back,
// and every payment recorded. Payments are applied to the statements oldest first (one made
// against a statement goes to it first), which gives each statement its paid and balance and
// the account its ageing. All of it is computed by the server on every load
// (backend/app/services/vendor_mapping.py); a payment is the one thing recorded here.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle, ArrowLeft, ArrowRight, Ban, Landmark, Plus, RefreshCw, Scale, Wallet, X,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { PAYMENT_MODULE_API, VENDOR_ACCOUNTS_API, type PaymentTabSlug } from "@/lib/paymentModule";
import { formatDay, formatPeriod } from "@/lib/statementPeriod";
import { PAYMENT_MODES, ReasonDialog, errorDetail, inr, todayIso } from "./shared";
import type {
  AccountPayment, AccountStatement, AccountsResponse, AgingBucket, StatementState, VendorAccount,
} from "./vendorTypes";

const INPUT_CLS =
  "w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400";
// The modes a bank reference is asked for — backend vendor_mapping.BANK_MODES.
const BANK_MODES = ["NEFT", "RTGS", "IMPS", "UPI", "Cheque"];

const STATE_STYLE: Record<StatementState, { label: string; cls: string }> = {
  paid: { label: "Paid", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  part_paid: { label: "Part paid", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  unpaid: { label: "Unpaid", cls: "bg-red-50 text-red-700 border-red-200" },
  credit: { label: "Credit", cls: "bg-sky-50 text-sky-700 border-sky-200" },
};

type Tab = "statements" | "payments" | "ledger";

function Stat({ label, value, tone = "slate", hint }: {
  label: string; value: number | null; tone?: "slate" | "emerald" | "red" | "amber" | "violet" | "blue"; hint?: string;
}) {
  const tones = {
    slate: "text-slate-800", emerald: "text-emerald-700", red: "text-red-700", amber: "text-amber-700",
    violet: "text-violet-700", blue: "text-blue-700",
  };
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3.5 py-2.5" title={hint}>
      <p className="text-[10px] uppercase tracking-wide text-slate-400 font-semibold">{label}</p>
      <p className={`text-base font-bold tabular-nums ${tones[tone]}`}>{value == null ? "—" : inr(value)}</p>
    </div>
  );
}

/** What is owed, by how long since its statement's period ended. */
function Aging({ buckets }: { buckets: AgingBucket[] }) {
  const total = buckets.reduce((a, b) => a + Math.max(b.amount, 0), 0);
  const tones = ["bg-emerald-400", "bg-lime-400", "bg-amber-400", "bg-orange-500", "bg-red-500"];
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] uppercase tracking-wide text-slate-400 font-semibold">Ageing of what is owed</p>
        <p className="text-[11px] text-slate-500 tabular-nums">{inr(total)}</p>
      </div>
      <div className="flex h-2 rounded-full overflow-hidden bg-slate-100">
        {total > 0 && buckets.map((b, i) => b.amount > 0 && (
          <div key={b.bucket} className={tones[i]} style={{ width: `${(b.amount / total) * 100}%` }} title={`${b.bucket}: ${inr(b.amount)}`} />
        ))}
      </div>
      <div className="grid grid-cols-5 gap-2 mt-2">
        {buckets.map((b, i) => (
          <div key={b.bucket}>
            <p className="flex items-center gap-1 text-[10px] text-slate-500">
              <span className={`w-2 h-2 rounded-full ${tones[i]}`} /> {b.bucket}
            </p>
            <p className="text-xs font-semibold tabular-nums text-slate-700">{inr(b.amount)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function VendorPaymentsView({
  onOpenTab, focus,
}: {
  onOpenTab?: (slug: PaymentTabSlug, focus?: { vendor?: string | null; statement?: string | null }) => void;
  /** Opened from Vendor Mapping's "Pay this vendor": that vendor's account. */
  focus?: { vendor?: string | null } | null;
}) {
  const [list, setList] = useState<AccountsResponse | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vendor, setVendor] = useState<string | null>(focus?.vendor ?? null);
  const [account, setAccount] = useState<VendorAccount | null>(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [tab, setTab] = useState<Tab>("statements");
  const [payFor, setPayFor] = useState<{ statement: AccountStatement | null } | null>(null);
  const [voidTarget, setVoidTarget] = useState<AccountPayment | null>(null);
  const [voiding, setVoiding] = useState(false);

  const loadList = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      const { data } = await api.get<AccountsResponse>(VENDOR_ACCOUNTS_API);
      setList(data);
    } catch (e) {
      setError(errorDetail(e, "Could not load the vendor accounts."));
    } finally {
      setListLoading(false);
    }
  }, []);

  const loadAccount = useCallback(async (key: string) => {
    setAccountLoading(true);
    setError(null);
    try {
      const { data } = await api.get<VendorAccount>(`${VENDOR_ACCOUNTS_API}/detail`, { params: { vendor: key } });
      setAccount(data);
    } catch (e) {
      setError(errorDetail(e, "Could not load this vendor's account."));
      setAccount(null);
    } finally {
      setAccountLoading(false);
    }
  }, []);

  useEffect(() => { void loadList(); }, [loadList]);
  useEffect(() => {
    if (vendor) void loadAccount(vendor);
    else setAccount(null);
  }, [vendor, loadAccount]);

  const openVendor = (key: string | null) => { setVendor(key); setTab("statements"); };

  const voidPayment = async (reason: string) => {
    if (!voidTarget || !vendor) return;
    setVoiding(true);
    try {
      await api.post(`${PAYMENT_MODULE_API}/payments/${voidTarget.id}/void`, { reason });
      toast.success("Payment voided — what it paid is owed again.");
      setVoidTarget(null);
      await Promise.all([loadAccount(vendor), loadList()]);
    } catch (e) {
      toast.error(errorDetail(e, "Could not void the payment."));
    } finally {
      setVoiding(false);
    }
  };

  // ── one vendor ─────────────────────────────────────────────────────────────
  if (vendor) {
    const t = account?.totals;
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <button type="button" onClick={() => openVendor(null)}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800">
            <ArrowLeft className="w-3.5 h-3.5" /> All vendors
          </button>
          <span className="h-4 w-px bg-slate-200" />
          <h2 className="text-sm font-bold text-slate-800">
            {account?.vendor.name ?? "…"}
            {account?.vendor.branch && <span className="font-normal text-slate-500"> — {account.vendor.branch}</span>}
          </h2>
          {account?.vendor.channels.map((c) => (
            <span key={c} className="px-1.5 py-0.5 rounded bg-slate-100 text-[9px] font-semibold text-slate-500">{c}</span>
          ))}
          <span className="ml-auto flex items-center gap-2">
            <button type="button" onClick={() => onOpenTab?.("mapping", { vendor })}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">
              <Scale className="w-3.5 h-3.5" /> Vendor Mapping
            </button>
            <button type="button" onClick={() => void loadAccount(vendor)} disabled={accountLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
              <RefreshCw className={`w-3.5 h-3.5 ${accountLoading ? "animate-spin" : ""}`} /> Refresh
            </button>
            <button type="button" disabled={!account} onClick={() => setPayFor({ statement: null })}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
              <Plus className="w-3.5 h-3.5" /> Record payment
            </button>
          </span>
        </div>

        {error && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
            <AlertCircle className="w-4 h-4 shrink-0" /> {error}
          </div>
        )}

        {t && account && (
          <>
            <div className="grid gap-2 grid-cols-2 sm:grid-cols-4 xl:grid-cols-8">
              {t.opening != null && <Stat label="Opening" value={t.opening} hint="Printed on the vendor's first statement — what was owed before it" />}
              <Stat label="Billed" value={t.billed} hint="Every statement's lines" />
              <Stat label="Claimed back" value={t.claims} tone="violet" hint="Lines decided “vendor is wrong” in Vendor Mapping — not paid" />
              <Stat label="Paid" value={t.paid} tone="emerald" hint="Every payment recorded, voided ones left out" />
              <Stat label="Balance" value={t.balance} tone={t.balance > 0 ? "red" : "emerald"}
                hint="Opening + billed − claimed − paid. Below zero: an advance with the vendor" />
              <Stat label="On hold" value={t.hold_unpaid} tone="amber" hint="Unpaid lines held in Vendor Mapping until decided" />
              <Stat label="Payable now" value={t.payable_now} tone="blue" hint="The balance less what is held" />
              {t.advance > 0 && <Stat label="Advance" value={t.advance} tone="emerald" hint="Paid beyond what is owed — used up by the next statements" />}
            </div>

            {account.check && (
              <div className={`flex items-start gap-2 px-4 py-2.5 rounded-xl border text-xs ${
                Math.abs(account.check.difference) < 1 ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
                <Landmark className="w-4 h-4 shrink-0 mt-px" />
                <span>
                  On {formatDay(account.check.as_at)} the vendor&apos;s statement ({account.check.file_name}) shows a balance of{" "}
                  <b>{inr(account.check.vendor)}</b>; this account at the same day shows <b>{inr(account.check.ours)}</b>
                  {Math.abs(account.check.difference) < 1
                    ? " — they agree."
                    : <> — <b>{inr(account.check.difference)}</b> apart: a payment one side has not recorded, or a statement not loaded.</>}
                </span>
              </div>
            )}

            <Aging buckets={account.aging} />

            <div className="flex items-center gap-1 border-b border-slate-200">
              {(["statements", "payments", "ledger"] as Tab[]).map((k) => (
                <button key={k} type="button" onClick={() => setTab(k)}
                  className={`px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px ${
                    tab === k ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                  {k === "statements" ? `Statements (${account.statements.length})`
                    : k === "payments" ? `Payments (${account.payments.length})` : "Ledger"}
                </button>
              ))}
            </div>

            {tab === "statements" && (
              <StatementsTable account={account} onPay={(s) => setPayFor({ statement: s })}
                onMap={(s) => onOpenTab?.("mapping", { vendor, statement: s.batch_id })} />
            )}
            {tab === "payments" && <PaymentsTable account={account} onVoid={setVoidTarget} />}
            {tab === "ledger" && <LedgerTable account={account} />}
          </>
        )}
        {accountLoading && !account && <p className="py-10 text-center text-xs text-slate-400">Loading the account…</p>}

        {payFor && account && (
          <PaymentDialog account={account} statement={payFor.statement} onClose={() => setPayFor(null)}
            onSaved={(next) => { setAccount(next); setPayFor(null); setTab("payments"); void loadList(); }} />
        )}
        {voidTarget && (
          <ReasonDialog
            title="Void this payment?"
            description={`${inr(voidTarget.amount)} paid ${formatDay(voidTarget.payment_date)}${voidTarget.reference ? ` (${voidTarget.reference})` : ""}. What it paid is owed again. The payment stays on record as void.`}
            confirmLabel="Void payment" requireRemarks danger busy={voiding}
            onCancel={() => setVoidTarget(null)} onConfirm={(remarks) => void voidPayment(remarks)}
          />
        )}
      </div>
    );
  }

  // ── every vendor ───────────────────────────────────────────────────────────
  const totals = list?.totals;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <p className="text-xs text-slate-500">
          Every vendor with a statement loaded or a payment recorded{list ? ` · as of ${formatDay(list.as_of)}` : ""}.
        </p>
        <button type="button" onClick={() => void loadList()} disabled={listLoading}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${listLoading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {totals && (
        <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Billed" value={totals.billed} />
          <Stat label="Paid" value={totals.paid} tone="emerald" />
          <Stat label="Balance owed" value={totals.balance} tone="red" hint="What every vendor's account comes to — advances netted" />
          <Stat label="On hold" value={totals.hold} tone="amber" hint="Held in Vendor Mapping until decided" />
          <Stat label="Payable now" value={totals.payable_now} tone="blue" />
          <Stat label="Claimed back" value={totals.claims} tone="violet" />
        </div>
      )}
      {list && <Aging buckets={list.aging} />}
      {list && list.unassigned_statements > 0 && (
        <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {list.unassigned_statements} vendor statement{list.unassigned_statements === 1 ? " was" : "s were"} uploaded without a vendor
          (Agency Master) and {list.unassigned_statements === 1 ? "is" : "are"} on no account — re-upload under the vendor.
        </p>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
                <th className="text-left px-3 py-2.5 font-semibold">Vendor</th>
                <th className="text-right px-3 py-2.5 font-semibold">Statements</th>
                <th className="text-right px-3 py-2.5 font-semibold">Billed</th>
                <th className="text-right px-3 py-2.5 font-semibold">Claimed</th>
                <th className="text-right px-3 py-2.5 font-semibold">Paid</th>
                <th className="text-right px-3 py-2.5 font-semibold">Balance</th>
                <th className="text-right px-3 py-2.5 font-semibold">On hold</th>
                <th className="text-right px-3 py-2.5 font-semibold">Payable now</th>
                <th className="text-left px-3 py-2.5 font-semibold">Oldest due</th>
                <th className="text-left px-3 py-2.5 font-semibold">Last payment</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {listLoading && !list ? (
                <tr><td colSpan={11} className="px-3 py-12 text-center text-slate-400">Loading the vendor accounts…</td></tr>
              ) : !list || list.vendors.length === 0 ? (
                <tr><td colSpan={11} className="px-3 py-12 text-center text-slate-400">
                  No vendor has a statement loaded yet — upload one under Statements → Third Party.
                </td></tr>
              ) : list.vendors.map((v) => (
                <tr key={v.id} className="border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer" onClick={() => openVendor(v.id)}>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-slate-800">{v.name}</div>
                    <div className="text-[10px] text-slate-400">{[v.branch, v.channels.join(" · ")].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">
                    {v.statements}
                    {v.open > 0 && <div className="text-[10px] text-amber-600">{v.open} to decide</div>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(v.billed)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-violet-700">{v.claims ? inr(v.claims) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-emerald-700">{v.paid ? inr(v.paid) : "—"}</td>
                  <td className={`px-3 py-2 text-right tabular-nums font-semibold ${v.balance > 0 ? "text-red-700" : "text-emerald-700"}`}>
                    {inr(v.balance)}
                    {v.advance > 0 && <div className="text-[10px] font-normal">advance</div>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-amber-700">{v.hold_unpaid ? inr(v.hold_unpaid) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-blue-700">{inr(v.payable_now)}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                    {v.oldest_due ? <>{formatDay(v.oldest_due.day)}<div className="text-[10px] text-slate-400">{v.oldest_due.age ?? 0} days</div></> : "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                    {v.last_payment ? <>{inr(v.last_payment.amount)}<div className="text-[10px] text-slate-400">{formatDay(v.last_payment.payment_date)} · {v.last_payment.mode}</div></> : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600">Open <ArrowRight className="w-3 h-3" /></span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatementsTable({ account, onPay, onMap }: {
  account: VendorAccount; onPay: (s: AccountStatement) => void; onMap: (s: AccountStatement) => void;
}) {
  const rows = [...account.statements].reverse();     // newest first, as everywhere else
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <th className="text-left px-3 py-2.5 font-semibold">Statement</th>
              <th className="text-right px-3 py-2.5 font-semibold">Lines</th>
              <th className="text-right px-3 py-2.5 font-semibold">Billed</th>
              <th className="text-right px-3 py-2.5 font-semibold" title="Held in Vendor Mapping until decided">On hold</th>
              <th className="text-right px-3 py-2.5 font-semibold" title="Decided “vendor is wrong” — not paid">Claimed</th>
              <th className="text-right px-3 py-2.5 font-semibold" title="Payments applied to it, oldest statement first">Paid</th>
              <th className="text-right px-3 py-2.5 font-semibold">Balance</th>
              <th className="text-right px-3 py-2.5 font-semibold">Payable now</th>
              <th className="text-left px-3 py-2.5 font-semibold">Age</th>
              <th className="text-left px-3 py-2.5 font-semibold">Status</th>
              <th className="px-3 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={11} className="px-3 py-10 text-center text-slate-400">No statement loaded for this vendor.</td></tr>
            ) : rows.map((s) => {
              const st = STATE_STYLE[s.state];
              return (
                <tr key={s.batch_id} className="border-b border-slate-100 align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-800 truncate max-w-[260px]" title={s.file_name ?? undefined}>{s.file_name || s.batch_id}</div>
                    <div className="text-[10px] text-slate-400">
                      {s.slug === "tp-lcc" ? "LCC" : "GDS"} · {s.period_from && s.period_to ? formatPeriod(s.period_from, s.period_to) : "no period"}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">
                    {s.lines}
                    {s.open > 0 && <div className="text-[10px] text-amber-600">{s.open} to decide</div>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(s.billed)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-amber-700">{s.hold ? inr(s.hold) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-violet-700">{s.claim ? inr(s.claim) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-emerald-700">{s.paid ? inr(s.paid) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold">{s.state === "credit" ? inr(s.due) : inr(s.balance)}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-blue-700">{s.payable_now ? inr(s.payable_now) : "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-slate-500">{s.age_days != null ? `${s.age_days} days` : "—"}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.cls}`}>{st.label}</span>
                    {s.state === "credit" && s.credit_used ? <div className="text-[10px] text-slate-400 mt-0.5">{inr(s.credit_used)} used</div> : null}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button type="button" onClick={() => onMap(s)} className="text-[11px] font-medium text-slate-500 hover:text-blue-700 mr-3">Map</button>
                    {s.payable_now > 0 && (
                      <button type="button" onClick={() => onPay(s)} className="text-[11px] font-semibold text-blue-600 hover:underline">Pay</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PaymentsTable({ account, onVoid }: { account: VendorAccount; onVoid: (p: AccountPayment) => void }) {
  const names = useMemo(() => new Map(account.statements.map((s) => [s.batch_id, s.file_name || s.batch_id])), [account]);
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
            <th className="text-left px-3 py-2.5 font-semibold">Date</th>
            <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
            <th className="text-left px-3 py-2.5 font-semibold">Mode</th>
            <th className="text-left px-3 py-2.5 font-semibold">UTR / reference</th>
            <th className="text-left px-3 py-2.5 font-semibold">Against</th>
            <th className="text-left px-3 py-2.5 font-semibold">Remarks</th>
            <th className="px-3 py-2.5" />
          </tr>
        </thead>
        <tbody>
          {account.payments.length === 0 ? (
            <tr><td colSpan={7} className="px-3 py-10 text-center text-slate-400">No payment recorded for this vendor yet.</td></tr>
          ) : account.payments.map((p) => {
            const voided = p.status === "voided";
            return (
              <tr key={p.id} className={`border-b border-slate-100 ${voided ? "text-slate-400" : ""}`}>
                <td className="px-3 py-2 whitespace-nowrap">{formatDay(p.payment_date)}</td>
                <td className={`px-3 py-2 text-right tabular-nums font-semibold ${voided ? "line-through" : "text-slate-800"}`}>{inr(p.amount)}</td>
                <td className="px-3 py-2">{p.mode || "—"}</td>
                <td className="px-3 py-2 font-mono">{p.reference || "—"}</td>
                <td className="px-3 py-2 truncate max-w-[220px]">{p.statement ? names.get(p.statement) ?? "a statement" : "On account — oldest first"}</td>
                <td className="px-3 py-2 max-w-[260px]">
                  {voided ? <span className="text-red-600">Void — {p.void_reason}</span> : p.remarks || "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  {!voided && (
                    <button type="button" onClick={() => onVoid(p)} className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-red-600">
                      <Ban className="w-3 h-3" /> Void
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LedgerTable({ account }: { account: VendorAccount }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
            <th className="text-left px-3 py-2.5 font-semibold">Date</th>
            <th className="text-left px-3 py-2.5 font-semibold">Entry</th>
            <th className="text-right px-3 py-2.5 font-semibold" title="What the vendor billed — adds to what is owed">Billed</th>
            <th className="text-right px-3 py-2.5 font-semibold" title="Payments and claims — take off what is owed">Paid / claimed</th>
            <th className="text-right px-3 py-2.5 font-semibold">Balance</th>
          </tr>
        </thead>
        <tbody>
          {account.ledger.length === 0 ? (
            <tr><td colSpan={5} className="px-3 py-10 text-center text-slate-400">Nothing on this account yet.</td></tr>
          ) : account.ledger.map((e, i) => (
            <tr key={i} className="border-b border-slate-100">
              <td className="px-3 py-2 whitespace-nowrap text-slate-600">{formatDay(e.day)}</td>
              <td className="px-3 py-2 text-slate-700">
                {e.label}
                {e.period_from && e.period_to && <span className="text-slate-400"> · {formatPeriod(e.period_from, e.period_to)}</span>}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{e.amount > 0 ? inr(e.amount) : ""}</td>
              <td className="px-3 py-2 text-right tabular-nums text-emerald-700">{e.amount < 0 ? inr(-e.amount) : ""}</td>
              <td className={`px-3 py-2 text-right tabular-nums font-semibold ${e.balance > 0 ? "text-slate-800" : "text-emerald-700"}`}>{inr(e.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Record a payment made to the vendor — on account, or against one statement. */
function PaymentDialog({ account, statement, onClose, onSaved }: {
  account: VendorAccount; statement: AccountStatement | null;
  onClose: () => void; onSaved: (account: VendorAccount) => void;
}) {
  const t = account.totals;
  const [against, setAgainst] = useState(statement?.batch_id ?? "");
  const target = account.statements.find((s) => s.batch_id === against) ?? null;
  const suggested = target ? target.payable_now : t.payable_now;
  const [amount, setAmount] = useState(suggested > 0 ? suggested.toFixed(2) : "");
  const [date, setDate] = useState(todayIso());
  const [mode, setMode] = useState<string>("NEFT");
  const [reference, setReference] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const value = Number(amount);
  const needsRef = BANK_MODES.includes(mode);
  const after = t.balance - (Number.isFinite(value) ? value : 0);
  const ok = Number.isFinite(value) && value > 0 && !!date && (!needsRef || reference.trim() !== "");

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { data } = await api.post<VendorAccount>(`${VENDOR_ACCOUNTS_API}/payments`, {
        vendor: account.vendor.id, payment_date: date, amount: value.toFixed(2), mode,
        reference: reference.trim() || null, remarks: remarks.trim() || null, statement: against || null,
      });
      toast.success(`Payment of ${inr(value)} recorded for ${account.vendor.name}.`);
      onSaved(data);
    } catch (e) {
      setErr(errorDetail(e, "Could not record the payment."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Wallet className="w-4 h-4 text-blue-600" /> Record payment — {account.vendor.name}
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Balance {inr(t.balance)} · payable now {inr(t.payable_now)}{t.hold_unpaid ? ` · ${inr(t.hold_unpaid)} on hold` : ""}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 hover:bg-slate-100 rounded-lg text-slate-400" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <label className="block">
          <span className="text-[11px] text-slate-500">Against</span>
          <select value={against} onChange={(e) => {
            setAgainst(e.target.value);
            const s = account.statements.find((x) => x.batch_id === e.target.value);
            const next = s ? s.payable_now : t.payable_now;
            setAmount(next > 0 ? next.toFixed(2) : "");
          }} className={`${INPUT_CLS} mt-1 bg-white`}>
            <option value="">On account — applied to the oldest statement first</option>
            {[...account.statements].reverse().filter((s) => s.balance > 0.005).map((s) => (
              <option key={s.batch_id} value={s.batch_id}>
                {s.file_name || s.batch_id} · {s.period_from && s.period_to ? formatPeriod(s.period_from, s.period_to) : "no period"} · balance {inr(s.balance)}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[11px] text-slate-500">Amount (₹)</span>
            <input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
              className={`${INPUT_CLS} mt-1 tabular-nums`} />
          </label>
          <label className="block">
            <span className="text-[11px] text-slate-500">Payment date</span>
            <input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)}
              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
              className={`${INPUT_CLS} mt-1`} />
          </label>
          <label className="block">
            <span className="text-[11px] text-slate-500">Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)} className={`${INPUT_CLS} mt-1 bg-white`}>
              {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-[11px] text-slate-500">
              {mode === "Cheque" ? "Cheque number" : "UTR / reference"}{needsRef ? " (required)" : " (optional)"}
            </span>
            <input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={100}
              placeholder={mode === "Cheque" ? "e.g. 004512" : "e.g. HDFCN26302123456"}
              className={`${INPUT_CLS} mt-1 font-mono`} />
          </label>
        </div>
        <label className="block">
          <span className="text-[11px] text-slate-500">Remarks (optional)</span>
          <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} maxLength={2000} className={`${INPUT_CLS} mt-1`} />
        </label>

        {Number.isFinite(value) && value > 0 && (
          <p className={`text-[11px] ${after < -0.005 ? "text-amber-700" : "text-slate-500"}`}>
            {after < -0.005
              ? <>This pays {inr(-after)} more than the balance — it is kept as an advance and used by the next statements.</>
              : <>Balance after this payment: <b className="tabular-nums">{inr(after)}</b>.</>}
            {target && value > target.balance + 0.005 && " More than this statement's balance — the rest goes to the oldest statements still owed."}
          </p>
        )}
        {err && <p className="text-[11px] text-red-600">{err}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
            Cancel
          </button>
          <button type="button" disabled={!ok || busy} onClick={() => void save()}
            className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {busy ? "Saving…" : `Record ${Number.isFinite(value) && value > 0 ? inr(value) : "payment"}`}
          </button>
        </div>
      </div>
    </div>
  );
}
