"use client";

// Email intake → Inbox. Mail received from the parties onboarded in User Master — B2B
// (Agency Master), B2E (Corporate Master), B2C (Employee Master) — read from the connected
// mailboxes. Nothing else from the mailbox ever reaches this page (architecture/04).
//
// The bell links here as /email-intake/inbox?m=<id>, which opens that message.
//
// TABS. "Pending to upload" holds email with a statement or deal not yet uploaded (or only partly);
// once everything in it has been uploaded from "Process this email", it moves to "Uploaded".
// "All mail" and "Statements" keep every email, with an Uploaded / Partly uploaded tag on the row.
//
// MAIL HTML IS HOSTILE. The server sanitises it (services/mail/html.py: no scripts, no remote
// images) and this page still renders it inside a sandboxed iframe with scripts disabled —
// two walls. Attachments are fetched with the session token and opened from a blob URL; the
// server only lets PDFs and images display inline, after checking their real bytes.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import {
  ArrowLeft, CheckCircle2, CircleDashed, Download, Eye, FileArchive, FileImage, FileSpreadsheet, FileText, Inbox, Mail,
  MailOpen, Paperclip, RefreshCw, Search, Settings2,
} from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import ProcessPanel from "@/components/emailIntake/ProcessPanel";
import {
  SEGMENT_BADGE, SEGMENT_MASTER, STATEMENT_FAMILIES, brandOf, familyBadge, fmtListDate, fmtSize, fmtWhen,
  type MailConnection, type MailDetail, type MailList, type MailListItem, type MailboxCount, type Segment, type SyncResult,
} from "@/lib/emailIntake";

const BRAND = "#1e3a5f";
const PAGE_SIZE = 30;
const REFRESH_MS = 60_000;

type Filter = "all" | "b2b" | "b2e" | "b2c";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" }, { key: "b2b", label: "B2B" }, { key: "b2e", label: "B2E" }, { key: "b2c", label: "B2C" },
];

type Tab = "all" | "pending" | "uploaded" | "statements";

export default function InboxPage() {
  return (
    <Suspense fallback={null}>
      <InboxInner />
    </Suspense>
  );
}

function InboxInner() {
  const router = useRouter();
  const params = useSearchParams();
  const selectedId = Number(params.get("m")) || null;

  const [filter, setFilter] = useState<Filter>("all");
  const [mailbox, setMailbox] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [family, setFamily] = useState<string | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<MailList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [hasMailbox, setHasMailbox] = useState<boolean | null>(null);

  // Debounce typing into the search box.
  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const { data } = await api.get<MailList>("/mail/messages", {
        params: {
          segment: filter === "all" ? undefined : filter, q: query || undefined, unread: unreadOnly || undefined,
          mailbox: mailbox ?? undefined, kind: tab === "statements" ? "statement" : undefined, family: family ?? undefined,
          state: tab === "pending" ? "pending" : tab === "uploaded" ? "imported" : undefined,
          page, page_size: PAGE_SIZE,
        },
      });
      setList(data);
      setError("");
    } catch (e) {
      if (!quiet) setError(apiError(e));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [filter, query, unreadOnly, page, mailbox, tab, family]);

  useEffect(() => { void load(); }, [load]);

  // New mail arrives from the scheduled check — refresh quietly while the tab is visible.
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) void load(true); }, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    api.get<MailConnection[]>("/mail/connections")
      .then(({ data }) => setHasMailbox(data.some(c => c.status !== "disconnected")))
      .catch(() => setHasMailbox(null));
  }, []);

  const open = (id: number | null) => router.replace(id ? `/email-intake/inbox?m=${id}` : "/email-intake/inbox", { scroll: false });

  const checkNow = async () => {
    setSyncing(true);
    try {
      const { data } = await api.post<SyncResult>("/mail/sync");
      if (data.status === "ok" && data.new_messages > 0) toast.success(data.message);
      else if (data.status === "ok") toast(data.message);
      else toast.error(data.message);
      await load(true);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSyncing(false);
    }
  };

  const markRead = (id: number) =>
    setList(l => l && { ...l, unread: Math.max(0, l.unread - (l.items.find(i => i.id === id && !i.is_read) ? 1 : 0)),
                        items: l.items.map(i => (i.id === id ? { ...i, is_read: true } : i)) });

  const pages = list ? Math.max(1, Math.ceil(list.total / PAGE_SIZE)) : 1;

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            Email inbox
            {!!list?.unread && <span className="text-xs font-semibold text-white rounded-full px-2 py-0.5" style={{ background: BRAND }}>{list.unread} unread</span>}
          </h1>
          <p className="text-sm text-gray-500 mt-1">Mail from your onboarded agencies (B2B), corporates (B2E) and customers (B2C).</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/email-intake/mailboxes" className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-gray-600 border border-gray-200 hover:bg-gray-50">
            <Settings2 className="w-4 h-4" /> Mailboxes
          </Link>
          <button onClick={checkNow} disabled={syncing}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white shadow-sm disabled:opacity-60" style={{ background: BRAND }}>
            <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} /> {syncing ? "Checking…" : "Check for new mail"}
          </button>
        </div>
      </div>

      {hasMailbox === false && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          No mailbox is connected yet. <Link href="/email-intake/mailboxes" className="font-semibold underline">Connect your mailbox</Link> to start receiving mail from your onboarded parties.
        </div>
      )}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {list && list.mailboxes.length > 0 && (
        <MailboxPicker mailboxes={list.mailboxes} selected={mailbox}
                       onSelect={id => { setMailbox(id); setPage(1); }} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(340px,460px)_1fr] gap-4 items-start">
        {/* ── list ── */}
        <section className={`rounded-2xl border border-gray-200 bg-white overflow-hidden ${selectedId ? "hidden lg:block" : ""}`}>
          <div className="p-3 border-b border-gray-100 space-y-3">
            {/* The baseline is an inset shadow, not a border the tabs overlap, so a narrow column can scroll the row sideways. */}
            <div className="flex items-center -mx-3 px-1.5 -mt-1 overflow-x-auto whitespace-nowrap shadow-[inset_0_-1px_0_#f3f4f6] [scrollbar-width:none]">
              {([
                { key: "all", label: "All mail", count: null, pill: "", hint: undefined },
                { key: "pending", label: "Pending to upload", count: list?.pending ?? null, pill: "bg-amber-50 text-amber-700",
                  hint: "Emails with a statement or deal not yet uploaded" },
                { key: "uploaded", label: "Uploaded", count: list?.imported ?? null, pill: "bg-emerald-50 text-emerald-700",
                  hint: "Emails whose statements and deals have all been uploaded" },
                { key: "statements", label: "Statements", count: list?.statements ?? null, pill: "bg-gray-100 text-gray-600",
                  hint: "Every email that carries a statement" },
              ] as { key: Tab; label: string; count: number | null; pill: string; hint?: string }[]).map(t => (
                <button key={t.key} title={t.hint} onClick={() => { setTab(t.key); setFamily(null); setPage(1); }}
                        className={`shrink-0 px-2.5 py-2 text-xs font-semibold border-b-2 ${tab === t.key ? "border-[#1e3a5f] text-gray-900" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
                  {t.label}{t.count !== null && <span className={`ml-1.5 text-[10px] rounded-full px-1.5 py-px ${t.pill}`}>{t.count}</span>}
                </button>
              ))}
            </div>
            {tab === "statements" && (
              <div className="flex flex-wrap gap-1.5">
                <button onClick={() => { setFamily(null); setPage(1); }}
                        className={`text-[11px] font-medium border rounded-full px-2.5 py-0.5 ${family === null ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"}`}>
                  All types
                </button>
                {STATEMENT_FAMILIES.map(f => (
                  <button key={f.key} onClick={() => { setFamily(f.key); setPage(1); }}
                          className={`text-[11px] font-medium border rounded-full px-2.5 py-0.5 ${family === f.key ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : `${f.badge} hover:opacity-80`}`}>
                    {f.label}
                  </button>
                ))}
              </div>
            )}
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search sender or subject"
                     className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/20" />
            </div>
            <div className="flex items-center justify-between gap-2">
              <div className="inline-flex rounded-lg bg-gray-100 p-0.5">
                {FILTERS.map(f => (
                  <button key={f.key} onClick={() => { setFilter(f.key); setPage(1); }}
                          className={`px-3 py-1 text-xs font-semibold rounded-md ${filter === f.key ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}>
                    {f.label}
                  </button>
                ))}
              </div>
              <label className="flex items-center gap-1.5 text-xs text-gray-600">
                <input type="checkbox" checked={unreadOnly} onChange={e => { setUnreadOnly(e.target.checked); setPage(1); }} /> Unread
              </label>
            </div>
          </div>

          {loading && !list && <div className="p-3 space-y-2">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-16 rounded-lg bg-gray-100 animate-pulse" />)}</div>}
          {list && list.items.length === 0 && <EmptyList tab={tab} filtered={filter !== "all" || unreadOnly || !!query || !!family} />}
          <ul className="divide-y divide-gray-100 max-h-[calc(100vh-290px)] overflow-y-auto">
            {list?.items.map(item => (
              <ListRow key={item.id} item={item} active={item.id === selectedId} onOpen={() => open(item.id)} />
            ))}
          </ul>
          {list && list.total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 text-xs text-gray-500">
              <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, list.total)} of {list.total}</span>
              <div className="flex gap-1">
                <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40">Prev</button>
                <button disabled={page >= pages} onClick={() => setPage(p => p + 1)} className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40">Next</button>
              </div>
            </div>
          )}
        </section>

        {/* ── message ── */}
        <section className={`${selectedId ? "" : "hidden lg:block"}`}>
          {selectedId
            ? <MessageView key={selectedId} id={selectedId} onBack={() => open(null)} onLoaded={markRead}
                           onMarkedUnread={() => void load(true)} onImported={() => void load(true)} />
            : (
              <div className="rounded-2xl border border-gray-200 bg-white h-[calc(100vh-200px)] flex flex-col items-center justify-center text-center text-sm text-gray-400">
                <MailOpen className="w-10 h-10 mb-3 text-gray-300" />
                Select an email to read it
              </div>
            )}
        </section>
      </div>
    </div>
  );
}

// ── mailbox picker ─────────────────────────────────────────────────────────

function MailboxPicker({ mailboxes, selected, onSelect }: {
  mailboxes: MailboxCount[]; selected: number | null; onSelect: (id: number | null) => void;
}) {
  const total = mailboxes.reduce((n, m) => n + m.total, 0);
  const unread = mailboxes.reduce((n, m) => n + m.unread, 0);
  const chip = (active: boolean) =>
    `shrink-0 inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition ${active ? "border-[#1e3a5f] bg-[#1e3a5f]/[0.04] ring-2 ring-[#1e3a5f]/10" : "border-gray-200 bg-white hover:bg-gray-50"}`;
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      <button onClick={() => onSelect(null)} className={chip(selected === null)}>
        <div className="w-7 h-7 rounded-lg bg-gray-100 text-gray-600 flex items-center justify-center"><Inbox className="w-4 h-4" /></div>
        <div>
          <p className="text-xs font-semibold text-gray-900">All mailboxes</p>
          <p className="text-[11px] text-gray-500">{total} email{total === 1 ? "" : "s"}{unread ? ` · ${unread} unread` : ""}</p>
        </div>
      </button>
      {mailboxes.map(m => {
        const brand = brandOf(m.provider, m.provider_key);
        return (
          <button key={m.id} onClick={() => onSelect(m.id)} className={chip(selected === m.id)} title={m.email_address}>
            <div className={`w-7 h-7 rounded-lg ring-1 flex items-center justify-center text-[10px] font-bold ${brand.tile}`}>{brand.short}</div>
            <div className="max-w-[200px]">
              <p className="text-xs font-semibold text-gray-900 truncate">{m.email_address}</p>
              <p className="text-[11px] text-gray-500">
                {m.total} email{m.total === 1 ? "" : "s"}{m.statements ? ` · ${m.statements} with statements` : ""}
                {m.status !== "active" && <span className="text-amber-600"> · {m.status.replace("_", " ")}</span>}
              </p>
            </div>
            {m.unread > 0 && <span className="text-[10px] font-semibold text-white rounded-full px-1.5 py-px" style={{ background: BRAND }}>{m.unread}</span>}
          </button>
        );
      })}
    </div>
  );
}

// ── list ───────────────────────────────────────────────────────────────────

function initials(name: string): string {
  const parts = name.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

function SegmentBadge({ segment }: { segment: Segment }) {
  return <span className={`text-[10px] font-semibold border rounded px-1.5 py-px ${SEGMENT_BADGE[segment]}`}>{segment}</span>;
}

function ListRow({ item, active, onOpen }: { item: MailListItem; active: boolean; onOpen: () => void }) {
  const who = item.party?.label || item.from_name || item.from_address;
  // Someone else at the party's company: the label alone would hide who actually wrote.
  const person = item.party?.via === "domain" ? (item.from_name || item.from_address) : null;
  return (
    <li>
      <button onClick={onOpen}
              className={`w-full text-left px-4 py-3 flex gap-3 transition ${active ? "bg-[#1e3a5f]/[0.06]" : "hover:bg-gray-50"}`}>
        <div className="relative shrink-0">
          <div className="w-9 h-9 rounded-full bg-gray-100 text-gray-600 text-xs font-bold flex items-center justify-center">{initials(who)}</div>
          {!item.is_read && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-white" style={{ background: BRAND }} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`text-sm truncate ${item.is_read ? "text-gray-700" : "font-semibold text-gray-900"}`}>
              {who}{person && <span className="font-normal text-gray-500"> · {person}</span>}
            </span>
            {item.party && <SegmentBadge segment={item.party.segment} />}
            <span className="ml-auto text-[11px] text-gray-400 shrink-0">{fmtListDate(item.received_at)}</span>
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`text-xs truncate ${item.is_read ? "text-gray-600" : "font-semibold text-gray-800"}`}>{item.subject || "(no subject)"}</span>
            {item.attachment_count > 0 && <Paperclip className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
          </div>
          {item.snippet && <p className="text-xs text-gray-400 truncate mt-0.5">{item.snippet}</p>}
          {(item.statements.length > 0 || item.imported_items > 0) && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {item.imported ? (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold border rounded px-1.5 py-px bg-emerald-50 text-emerald-700 border-emerald-200">
                  <CheckCircle2 className="w-3 h-3" /> Uploaded
                </span>
              ) : item.imported_items > 0 && (
                <span title="Some of this email is uploaded; open it to upload the rest"
                      className="inline-flex items-center gap-1 text-[10px] font-semibold border rounded px-1.5 py-px bg-amber-50 text-amber-700 border-amber-200">
                  <CircleDashed className="w-3 h-3" /> Partly uploaded
                </span>
              )}
              {item.statements.map(s => (
                <span key={s.doc_type} className={`inline-flex items-center gap-1 text-[10px] font-semibold border rounded px-1.5 py-px ${familyBadge(s.family)}`}>
                  <FileSpreadsheet className="w-3 h-3" /> {s.label}
                </span>
              ))}
            </div>
          )}
        </div>
      </button>
    </li>
  );
}

const EMPTY_TAB: Record<Exclude<Tab, "all">, { title: string; text: string }> = {
  pending:    { title: "Nothing pending to upload",
                text: "Every statement and deal that came by email has been uploaded. You'll find those emails under Uploaded." },
  uploaded:   { title: "Nothing uploaded yet",
                text: "Open an email and use Process this email. Once everything in it is uploaded, it moves here." },
  statements: { title: "No statements yet",
                text: "Emails with a BSP, LCC, third-party or other statement attached appear here." },
};

function EmptyList({ tab, filtered }: { tab: Tab; filtered: boolean }) {
  if (tab !== "all" && !filtered) {
    return (
      <div className="px-6 py-14 text-center">
        <CheckCircle2 className="w-9 h-9 mx-auto text-gray-300" />
        <p className="mt-3 text-sm font-medium text-gray-700">{EMPTY_TAB[tab].title}</p>
        <p className="mt-1 text-xs text-gray-500 max-w-xs mx-auto">{EMPTY_TAB[tab].text}</p>
      </div>
    );
  }
  return (
    <div className="px-6 py-14 text-center">
      <Inbox className="w-9 h-9 mx-auto text-gray-300" />
      <p className="mt-3 text-sm font-medium text-gray-700">{filtered ? "No emails match these filters" : "No emails yet"}</p>
      {!filtered && (
        <p className="mt-1 text-xs text-gray-500 max-w-xs mx-auto">
          Mail sent by the emails in Agency, Corporate and Employee Master appears here. FareQube checks your mailbox every few minutes.
        </p>
      )}
    </div>
  );
}

// ── message ────────────────────────────────────────────────────────────────

function fileIcon(name: string, type: string) {
  const n = name.toLowerCase();
  if (type.startsWith("image/")) return FileImage;
  if (/\.(xlsx?|xlsb|xlsm|csv)$/.test(n) || type.includes("spreadsheet") || type.includes("excel")) return FileSpreadsheet;
  if (/\.(zip|rar|7z)$/.test(n)) return FileArchive;
  return FileText;
}

// The iframe document: the sanitised HTML plus a CSP that blocks everything the sanitiser
// should already have removed — scripts, remote loads, forms.
function frameDoc(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:">
<base target="_blank"><style>body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;font-size:14px;line-height:1.5;color:#1f2937;margin:0;padding:4px 2px;word-wrap:break-word}img{max-width:100%;height:auto}table{max-width:100%}a{color:#1e3a5f}</style>
</head><body>${html}</body></html>`;
}

function MessageView({ id, onBack, onLoaded, onMarkedUnread, onImported }: {
  id: number; onBack: () => void; onLoaded: (id: number) => void; onMarkedUnread: () => void; onImported: () => void;
}) {
  const [msg, setMsg] = useState<MailDetail | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  const [error, setError] = useState("");
  const [busyAtt, setBusyAtt] = useState<number | null>(null);
  const loadedRef = useRef(onLoaded);
  loadedRef.current = onLoaded;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get<MailDetail>(`/mail/messages/${id}`);
        if (cancelled) return;
        setMsg(data);
        loadedRef.current(id);
        if (data.has_html) {
          const r = await api.get<{ html: string }>(`/mail/messages/${id}/html`);
          if (!cancelled) setHtml(r.data.html);
        }
      } catch (e) {
        if (!cancelled) setError(apiError(e));
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  const files = useMemo(() => (msg?.attachments ?? []).filter(a => !a.is_inline), [msg]);

  const getFile = async (attId: number, inline: boolean) => {
    setBusyAtt(attId);
    try {
      const res = await api.get(`/mail/attachments/${attId}/download`, { params: { inline: inline || undefined }, responseType: "blob" });
      const url = URL.createObjectURL(res.data as Blob);
      const att = files.find(a => a.id === attId);
      if (inline) {
        window.open(url, "_blank", "noopener,noreferrer");
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = att?.filename ?? "attachment";
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusyAtt(null);
    }
  };

  const markUnread = async () => {
    try { await api.post(`/mail/messages/${id}/unread`); onMarkedUnread(); onBack(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (error) return <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">{error}</div>;
  if (!msg) return <div className="rounded-2xl border border-gray-200 bg-white h-[calc(100vh-200px)] animate-pulse" />;

  const who = msg.from_name || msg.from_address;
  const useHtml = msg.has_html && !showText && html !== null;

  return (
    <article className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
      <header className="px-6 pt-5 pb-4 border-b border-gray-100 space-y-3">
        <div className="flex items-start gap-3">
          <button onClick={onBack} className="lg:hidden p-1.5 -ml-1.5 rounded-lg hover:bg-gray-100" aria-label="Back"><ArrowLeft className="w-4 h-4" /></button>
          <h2 className="text-lg font-semibold text-gray-900 leading-snug flex-1">{msg.subject || "(no subject)"}</h2>
          <button onClick={markUnread} className="text-xs text-gray-500 hover:text-gray-800 inline-flex items-center gap-1 shrink-0">
            <Mail className="w-3.5 h-3.5" /> Mark unread
          </button>
        </div>

        {msg.parties.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {msg.parties.map(p => (
              <span key={`${p.party_type}-${p.party_id}`} className="inline-flex items-center gap-1.5 text-xs bg-gray-50 border border-gray-200 rounded-lg px-2 py-1">
                <SegmentBadge segment={p.segment} />
                <span className="font-medium text-gray-800">{p.label}</span>
                <span className="text-gray-400">· {SEGMENT_MASTER[p.segment]}</span>
                {p.via === "domain" && (
                  <span className="text-gray-400" title={`Not the address in the master — someone else at @${msg.from_address.split("@")[1] ?? ""}`}>
                    · same domain
                  </span>
                )}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-gray-100 text-gray-600 text-sm font-bold flex items-center justify-center shrink-0">{initials(who)}</div>
          <div className="min-w-0 flex-1 text-xs text-gray-500 space-y-0.5">
            <p><span className="text-sm font-semibold text-gray-900">{who}</span> <span>&lt;{msg.from_address}&gt;</span></p>
            {msg.to_addresses.length > 0 && <p>To: {msg.to_addresses.join(", ")}</p>}
            {msg.cc_addresses.length > 0 && <p>Cc: {msg.cc_addresses.join(", ")}</p>}
          </div>
          <div className="text-right text-xs text-gray-500 shrink-0">
            <p>{fmtWhen(msg.received_at)}</p>
            <p className="text-gray-400">via {msg.mailbox}</p>
          </div>
        </div>
      </header>

      <ProcessPanel key={msg.id} messageId={msg.id} onChanged={onImported} />

      {msg.note === "too_large" && (
        <div className="mx-6 mt-4 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
          This email was too large to download in full; only its details were kept. Open it in your mailbox and upload the file directly.
        </div>
      )}

      {files.length > 0 && (
        <div className="px-6 pt-4">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">{files.length} attachment{files.length > 1 ? "s" : ""}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
            {files.map(a => {
              const Icon = fileIcon(a.filename, a.content_type);
              return (
                <div key={a.id} className="flex items-center gap-3 rounded-xl border border-gray-200 px-3 py-2.5">
                  <Icon className="w-5 h-5 shrink-0" style={{ color: BRAND }} />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-gray-800 truncate" title={a.filename}>{a.filename}</p>
                    <p className="text-[11px] text-gray-400">
                      {fmtSize(a.size_bytes)}{a.doc_rows ? ` · ${a.doc_rows.toLocaleString("en-IN")} rows` : ""}
                    </p>
                    {a.doc_kind === "statement" && a.doc_label && (
                      <span title={a.doc_reason ?? undefined}
                            className={`inline-flex mt-1 text-[10px] font-semibold border rounded px-1.5 py-px ${familyBadge(a.doc_family ?? "")}`}>
                        {a.doc_label}
                      </span>
                    )}
                  </div>
                  {a.previewable && (
                    <button onClick={() => getFile(a.id, true)} disabled={busyAtt === a.id} title="Preview"
                            className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-50"><Eye className="w-4 h-4" /></button>
                  )}
                  <button onClick={() => getFile(a.id, false)} disabled={busyAtt === a.id} title="Download"
                          className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-50">
                    {busyAtt === a.id ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="px-6 py-4">
        {msg.has_html && msg.body_text && (
          <div className="flex justify-end mb-2">
            <button onClick={() => setShowText(s => !s)} className="text-[11px] text-gray-500 hover:text-gray-800">
              {showText ? "Show formatted" : "Show plain text"}
            </button>
          </div>
        )}
        {useHtml ? (
          // No allow-scripts and no allow-same-origin: the mail cannot run code or reach the app.
          // allow-popups lets its links open in a new tab.
          <iframe title="Email content" sandbox="allow-popups allow-popups-to-escape-sandbox"
                  srcDoc={frameDoc(html ?? "")} className="w-full min-h-[480px] h-[calc(100vh-420px)] border-0" />
        ) : msg.has_html && html === null && !showText ? (
          <div className="h-40 rounded-lg bg-gray-50 animate-pulse" />
        ) : (
          <pre className="whitespace-pre-wrap break-words font-sans text-sm text-gray-800 leading-relaxed">{msg.body_text || "(This email has no text.)"}</pre>
        )}
      </div>
    </article>
  );
}
