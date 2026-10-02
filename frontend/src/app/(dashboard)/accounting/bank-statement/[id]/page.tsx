"use client";

// One uploaded bank statement, line by line. Each DEPOSIT is linked to the corporate,
// employee or agency that paid it — that link is what "Billed vs Received" counts.
// Withdrawals are only sorted by category for now (vendor payment, credit card, …).
//
// Suggestions come from the server: a payer linked on an earlier statement is suggested
// again ("linked before"), otherwise the name in the remarks is matched against the
// masters. "Accept suggestions" links the strong ones in one go, except agencies: an
// agency link posts a receipt into its ledger, so each one is a deliberate click.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Check, RefreshCw, Search, Sparkles, X } from "lucide-react";
import api from "@/lib/api";
import { inr, rupees } from "@/lib/money";
import {
  IN_CATEGORIES, OUT_CATEGORIES, PARTY_TYPE_LABEL, errText, fmtDate, partyLabel,
  type BankRow, type PartyRef, type StatementDetail,
} from "@/lib/bankStatement";

type Filter = "to_link" | "all" | "in" | "out" | "linked";

const TH = "px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap";
const TH_R = TH.replace("text-left", "text-right");
const CELL = "px-3 py-2 text-[11px] text-gray-700 align-top";
const CELL_R = `${CELL} text-right tabular-nums whitespace-nowrap`;
const SELECT = "w-full px-2 py-1 border border-gray-200 rounded-lg text-[11px] bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40";
/** Mirrors api/v1/bank_statements._AUTO_ACCEPT. */
const AUTO_ACCEPT = 0.85;

const isOpenReceipt = (r: BankRow) => r.direction === "in" && !r.party && r.category === "receipt";
const autoAcceptable = (r: BankRow) =>
  !!r.suggestion && r.suggestion.party.party_type !== "agency"
  && (r.suggestion.source === "history" || r.suggestion.score >= AUTO_ACCEPT);

export default function BankStatementDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [parties, setParties] = useState<PartyRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState<Filter | null>(null);
  const [search, setSearch] = useState("");
  const [busyRow, setBusyRow] = useState<number | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [picking, setPicking] = useState<{ row: BankRow; agency?: PartyRef } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<StatementDetail>(`/bank-statements/${id}`);
      setDetail(data);
      setFilter((f) => f ?? (data.statement.unlinked_receipt_count > 0 ? "to_link" : "all"));
      setError("");
    } catch (e) {
      setError(errText(e, "Failed to load the statement."));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get<PartyRef[]>("/bank-statements/parties").then(({ data }) => setParties(data)).catch(() => {});
  }, []);

  const patch = async (row: BankRow, body: Record<string, unknown>) => {
    setBusyRow(row.id);
    setError("");
    try {
      await api.patch(`/bank-statements/rows/${row.id}`, body);
      await load();
    } catch (e) {
      setError(errText(e, "Could not save that change."));
    } finally {
      setBusyRow(null);
    }
  };

  const link = (row: BankRow, p: PartyRef, channel?: string) =>
    patch(row, { party_type: p.party_type, party_id: p.party_id, ...(channel ? { agency_channel: channel } : {}) });

  /** An agency on both channels needs its account picked before anything is posted. */
  const linkSuggestion = (row: BankRow) => {
    const p = row.suggestion!.party;
    if (p.party_type === "agency" && p.channels === "BOTH") setPicking({ row, agency: p });
    else link(row, p);
  };

  const acceptAll = async () => {
    setAccepting(true);
    setError("");
    try {
      const { data } = await api.post<{ linked: number; skipped_agencies: number }>(
        `/bank-statements/${id}/accept-suggestions`,
      );
      setNotice(
        `Linked ${data.linked} deposit${data.linked === 1 ? "" : "s"}.` +
        (data.skipped_agencies ? ` ${data.skipped_agencies} agency match${data.skipped_agencies === 1 ? " is" : "es are"} left for you to confirm.` : ""),
      );
      await load();
    } catch (e) {
      setError(errText(e, "Could not accept the suggestions."));
    } finally {
      setAccepting(false);
    }
  };

  const rows = useMemo(() => {
    if (!detail) return [];
    const q = search.trim().toLowerCase();
    return detail.rows.filter((r) => {
      if (filter === "to_link" && !isOpenReceipt(r)) return false;
      if (filter === "in" && r.direction !== "in") return false;
      if (filter === "out" && r.direction !== "out") return false;
      if (filter === "linked" && !r.party) return false;
      if (!q) return true;
      return [r.remarks, r.counterparty, r.tran_id, r.party?.name].some((v) => (v ?? "").toLowerCase().includes(q));
    });
  }, [detail, filter, search]);

  if (!detail) {
    return (
      <div className="py-16 text-center text-xs text-gray-400">
        {error ? <span className="text-red-600">{error}</span> : (
          <><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading statement…</>
        )}
      </div>
    );
  }

  const s = detail.statement;
  const acceptable = detail.rows.filter((r) => isOpenReceipt(r) && autoAcceptable(r)).length;
  const counts: Record<Filter, number> = {
    to_link: detail.rows.filter(isOpenReceipt).length,
    all: detail.rows.length,
    in: detail.rows.filter((r) => r.direction === "in").length,
    out: detail.rows.filter((r) => r.direction === "out").length,
    linked: detail.rows.filter((r) => r.party).length,
  };
  const tiles = [
    { label: "Deposits", value: rupees(s.total_deposits, 2), tone: "text-green-700" },
    { label: "Withdrawals", value: rupees(s.total_withdrawals, 2), tone: "text-red-600" },
    { label: "Linked to a party", value: rupees(s.linked_amount, 2), sub: `${s.linked_count} deposits`, tone: "text-[#1e3a5f]" },
    {
      label: "Waiting to link", value: rupees(s.unlinked_receipt_amount, 2),
      sub: `${s.unlinked_receipt_count} deposits`, tone: s.unlinked_receipt_count ? "text-amber-600" : "text-green-700",
    },
  ];

  return (
    <div className="space-y-4">
      <div>
        <Link href="/accounting/bank-statement" className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-700 mb-1">
          <ArrowLeft className="w-3 h-3" /> Bank Statement
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{s.account_name || s.file_name}</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {[s.bank_name, s.account_no && `A/c ${s.account_no}`, s.branch].filter(Boolean).join(" · ")}
              {" · "}{fmtDate(s.period_from)} – {fmtDate(s.period_to)}
              {s.duplicate_count > 0 && ` · ${s.duplicate_count} lines already loaded elsewhere were skipped`}
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            title="Refresh"
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50 shrink-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {tiles.map((t) => (
          <div key={t.label} className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{t.label}</p>
            <p className={`text-lg font-bold tabular-nums mt-0.5 ${t.tone}`}>{t.value}</p>
            {t.sub && <p className="text-[10px] text-gray-400 mt-0.5">{t.sub}</p>}
          </div>
        ))}
      </div>

      {notice && (
        <div className="flex items-center justify-between text-xs text-green-800 bg-green-50 border border-green-200 rounded-xl px-4 py-2.5">
          {notice}
          <button onClick={() => setNotice("")}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}
      {error && <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{error}</div>}

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="flex gap-1">
            {([
              ["to_link", "To link"], ["all", "All"], ["in", "Deposits"], ["out", "Withdrawals"], ["linked", "Linked"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold ${
                  filter === key ? "bg-[#1e3a5f] text-white" : "bg-gray-50 text-gray-600 hover:bg-gray-100"
                }`}
              >
                {label} <span className="opacity-60">{counts[key]}</span>
              </button>
            ))}
          </div>
          <div className="relative flex-1 min-w-40">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search remarks, name or transaction id…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>
          {acceptable > 0 && (
            <button
              onClick={acceptAll}
              disabled={accepting}
              title="Link every deposit whose match is strong — a payer linked before, or a near-exact name. Agencies are left for you."
              className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white px-3 py-1.5 rounded-lg text-[11px] font-semibold disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" /> {accepting ? "Linking…" : `Accept ${acceptable} suggestion${acceptable === 1 ? "" : "s"}`}
            </button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                <th className={TH}>Date</th>
                <th className={TH}>Details</th>
                <th className={TH_R}>Withdrawal</th>
                <th className={TH_R}>Deposit</th>
                <th className={TH_R}>Balance</th>
                <th className={TH}>Category</th>
                <th className={`${TH} min-w-64`}>Received from</th>
              </tr>
            </thead>
            <tbody className={loading ? "opacity-60 transition-opacity" : ""}>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-xs text-gray-400">
                    {filter === "to_link" ? "Every deposit on this statement is linked or categorised." : "No lines match."}
                  </td>
                </tr>
              ) : rows.map((r, idx) => (
                <tr key={r.id} className={`border-b border-gray-50 ${idx % 2 ? "bg-gray-50/30" : "bg-white"} ${busyRow === r.id ? "opacity-50" : ""}`}>
                  <td className={`${CELL} whitespace-nowrap`}>
                    {fmtDate(r.txn_date)}
                    {r.tran_id && <p className="text-[10px] text-gray-400 font-mono">{r.tran_id}</p>}
                  </td>
                  <td className={`${CELL} max-w-md`}>
                    {r.counterparty && <p className="font-semibold text-gray-800">{r.counterparty}</p>}
                    <p className="text-[10px] text-gray-400 font-mono break-all">{r.remarks}</p>
                    {(r.payment_mode || r.reference) && (
                      <p className="text-[10px] text-gray-400">
                        {[r.payment_mode?.toUpperCase().replace("_", " "), r.reference].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </td>
                  <td className={`${CELL_R} text-red-600`}>{r.withdrawal ? inr(r.withdrawal, 2) : ""}</td>
                  <td className={`${CELL_R} text-green-700 font-semibold`}>{r.deposit ? inr(r.deposit, 2) : ""}</td>
                  <td className={`${CELL_R} text-gray-400`}>{r.balance != null ? inr(r.balance, 2) : ""}</td>
                  <td className={`${CELL} w-40`}>
                    <select
                      value={r.category}
                      disabled={busyRow === r.id}
                      onChange={(e) => patch(r, { category: e.target.value })}
                      className={SELECT}
                      title={r.party ? "Changing a linked deposit away from Customer receipt unlinks it" : undefined}
                    >
                      {(r.direction === "in" ? IN_CATEGORIES : OUT_CATEGORIES).map((c) => (
                        <option key={c} value={c}>{detail.categories[c] ?? c}</option>
                      ))}
                    </select>
                  </td>
                  <td className={CELL}>
                    <PartyCell
                      row={r}
                      busy={busyRow === r.id}
                      onPick={() => setPicking({ row: r })}
                      onAccept={() => linkSuggestion(r)}
                      onUnlink={() => patch(r, { party_type: null })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {picking && (
        <PartyPicker
          row={picking.row}
          parties={parties}
          initialAgency={picking.agency}
          onClose={() => setPicking(null)}
          onPick={(p, channel) => { setPicking(null); link(picking.row, p, channel); }}
        />
      )}
    </div>
  );
}

function PartyCell({ row, busy, onPick, onAccept, onUnlink }: {
  row: BankRow; busy: boolean; onPick: () => void; onAccept: () => void; onUnlink: () => void;
}) {
  if (row.direction === "out") return <span className="text-[10px] text-gray-300">—</span>;

  if (row.party) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] bg-blue-50 border border-blue-100 rounded-lg px-2 py-1">
          <Check className="w-3 h-3" /> {partyLabel(row.party)}
        </span>
        <button
          onClick={onUnlink}
          disabled={busy}
          className="p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50"
          title={row.party.party_type === "agency"
            ? "Unlink — the receipt posted to the agency's ledger is reversed"
            : "Unlink"}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  if (row.category !== "receipt") return <span className="text-[10px] text-gray-400">Not a customer receipt</span>;

  return (
    <div className="space-y-1">
      {row.suggestion && (
        <div className="flex items-center gap-1.5">
          <span
            className="text-[11px] text-gray-700 border border-dashed border-gray-300 rounded-lg px-2 py-1"
            title={row.suggestion.source === "history"
              ? "This payer was linked to this party on an earlier statement"
              : `Name match ${Math.round(row.suggestion.score * 100)}%`}
          >
            {partyLabel(row.suggestion.party)}
            <span className="ml-1 text-[10px] text-gray-400">
              {row.suggestion.source === "history" ? "· linked before" : `· ${Math.round(row.suggestion.score * 100)}%`}
            </span>
          </span>
          <button
            onClick={onAccept}
            disabled={busy}
            className="text-[11px] font-semibold text-white bg-[#1e3a5f] hover:bg-[#16304f] rounded-lg px-2 py-1 disabled:opacity-50"
          >
            Link
          </button>
        </div>
      )}
      <button onClick={onPick} disabled={busy} className="text-[11px] font-semibold text-[#1e3a5f] hover:underline">
        {row.suggestion ? "Someone else…" : "Link to a party…"}
      </button>
    </div>
  );
}

function PartyPicker({ row, parties, initialAgency, onPick, onClose }: {
  row: BankRow;
  parties: PartyRef[];
  initialAgency?: PartyRef;
  onPick: (p: PartyRef, channel?: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState(row.counterparty ?? "");
  const [agency, setAgency] = useState<PartyRef | null>(initialAgency ?? null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.select();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Match on every word typed, so the truncated bank name finds the master name.
  const words = q.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  const found = parties.filter((p) => {
    const hay = `${p.name} ${p.code ?? ""} ${p.detail ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  }).slice(0, 60);

  const choose = (p: PartyRef) => {
    if (p.party_type === "agency" && p.channels === "BOTH") setAgency(p);
    else onPick(p);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onMouseDown={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[80vh] flex flex-col" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Who paid this?</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {rupees(row.deposit, 2)} on {fmtDate(row.txn_date)}
              {row.counterparty && <> from <strong>{row.counterparty}</strong></>}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>

        {agency ? (
          <div className="px-5 py-4 space-y-3">
            <p className="text-xs text-gray-700">
              <strong>{agency.name}</strong> trades on GDS and LCC. Which account is this receipt for?
            </p>
            <div className="flex gap-2">
              {["GDS", "LCC"].map((ch) => (
                <button
                  key={ch}
                  onClick={() => onPick(agency, ch)}
                  className="flex-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold"
                >
                  {ch}
                </button>
              ))}
            </div>
            <button onClick={() => setAgency(null)} className="text-[11px] text-gray-500 hover:underline">← Pick someone else</button>
          </div>
        ) : (
          <>
            <div className="px-5 pt-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  ref={inputRef}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search corporates, employees, agencies…"
                  className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
                />
              </div>
            </div>
            <div className="overflow-y-auto px-2 py-2">
              {found.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-gray-400">
                  {parties.length === 0 ? "No corporates, employees or agencies on file yet." : "Nobody matches — shorten the search."}
                </p>
              ) : found.map((p) => (
                <button
                  key={`${p.party_type}:${p.party_id}`}
                  onClick={() => choose(p)}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-blue-50 flex items-start gap-2"
                >
                  <span className="text-[9px] font-semibold uppercase tracking-wide text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded mt-0.5 w-16 text-center shrink-0">
                    {PARTY_TYPE_LABEL[p.party_type]}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm text-gray-800 truncate">{p.name}</span>
                    {(p.code || p.detail) && (
                      <span className="block text-[10px] text-gray-400 truncate">{[p.code, p.detail].filter(Boolean).join(" · ")}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
