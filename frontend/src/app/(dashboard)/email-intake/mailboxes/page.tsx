"use client";

// Email intake → Mailboxes. Connect the mailbox where deals and statements arrive: Gmail /
// Google Workspace or Microsoft 365 by signing in, any other host (Zoho, GoDaddy, Rediff…)
// by IMAP, or no mailbox access at all through a forwarding address.
//
// THE ADDRESS COMES FIRST. The connect dialog asks for it, /mail/detect reads the domain's
// MX record and the right connector is pre-selected — "my mail is on Google but I picked
// IMAP" is the support call this saves. Every available connector stays pickable.
//
// The Google / Microsoft round trip leaves the app and comes back here with ?connected=…
// or ?error=… (api/v1/mail.py::oauth_callback). That is read once — a toast for success,
// a banner for a failure — and stripped from the URL so a refresh does not repeat it.

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronDown, Copy, ExternalLink, Forward, Inbox, Lock, Mail,
  MoreHorizontal, Pause, Play, Plus, RefreshCw, ShieldCheck, Trash2, X,
} from "lucide-react";
import api from "@/lib/api";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { ModalShell, apiError } from "@/components/userMaster/shared";
import {
  BACKFILL_OPTIONS, BRAND, IMAP_PORTS, STATUS_META, brandOf, fmtWhen,
  type ConnectResult, type DetectResult, type MailConfig, type MailConnection, type ProviderInfo,
} from "@/lib/emailIntake";

const BRAND_COLOR = "#1e3a5f";
const INPUT = "w-full px-3 py-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/25 focus:border-[#1e3a5f]/40";
const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5";
// Display names for the provider keys stored on a mailbox (settings.provider_key).
const PROVIDER_NAME: Record<string, string> = {
  google: "Google", microsoft: "Microsoft", godaddy: "GoDaddy", zoho: "Zoho Mail", titan: "Titan",
  yahoo: "Yahoo Mail", icloud: "iCloud Mail", rediff: "Rediffmail Pro", hostinger: "Hostinger",
  namecheap: "Namecheap", aol: "AOL Mail", yandex: "Yandex Mail", fastmail: "Fastmail", other: "IMAP",
};
const PRIMARY = "inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white shadow-sm hover:opacity-95 disabled:opacity-50";

export default function MailboxesPage() {
  return (
    <Suspense fallback={null}>
      <MailboxesInner />
    </Suspense>
  );
}

function MailboxesInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [config, setConfig] = useState<MailConfig | null>(null);
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState("");
  const [connectFor, setConnectFor] = useState<string | null>(null);   // null = closed; "" = blank form
  const [disconnecting, setDisconnecting] = useState<MailConnection | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: cfg } = await api.get<MailConfig>("/mail/config");
      setConfig(cfg);
      if (cfg.enabled) setConnections((await api.get<MailConnection[]>("/mail/connections")).data);
    } catch (e) {
      setFailure(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Back from Google / Microsoft: show the outcome once, then clean the URL.
  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (!connected && !error) return;
    if (connected) {
      toast.success(`${params.get("account") ?? "Mailbox"} connected`);
      if (params.get("hint_mismatch")) {
        setFailure(`You signed in as ${params.get("account")}, not the address you entered. If that is the wrong account, disconnect it and connect again.`);
      }
    }
    if (error) setFailure(error);
    router.replace("/email-intake/mailboxes");
  }, [params, router]);

  const upsert = (c: MailConnection) =>
    setConnections(cs => (cs.some(x => x.id === c.id) ? cs.map(x => (x.id === c.id ? c : x)) : [c, ...cs]));

  const live = connections.filter(c => c.status !== "disconnected");
  const canConnect = !!config?.enabled && config.can_connect;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Mailboxes</h1>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">
            Connect the inbox where your suppliers and airlines send deals and statements. FareQube reads only
            mail from senders you onboarded in Agency, Corporate and Employee Master.
          </p>
        </div>
        {canConnect && live.length > 0 && (
          <button onClick={() => setConnectFor("")} className={PRIMARY} style={{ background: BRAND_COLOR }}>
            <Plus className="w-4 h-4" /> Connect mailbox
          </button>
        )}
      </div>

      {failure && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="flex-1">{failure}</span>
          <button onClick={() => setFailure("")} aria-label="Dismiss"><X className="w-4 h-4 opacity-60" /></button>
        </div>
      )}

      {loading && <div className="h-40 rounded-2xl bg-gray-100 animate-pulse" />}

      {!loading && config && !config.enabled && (
        <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
          Email intake is not switched on for this workspace yet.
        </div>
      )}

      {!loading && config?.enabled && live.length === 0 && (
        <EmptyState canConnect={canConnect} onConnect={() => setConnectFor("")} />
      )}

      {!loading && live.length > 0 && (
        <div className="space-y-3">
          {live.map(c => (
            <MailboxCard key={c.id} conn={c} onChanged={upsert}
                         onReconnect={() => setConnectFor(c.email_address)}
                         onDisconnect={() => setDisconnecting(c)} />
          ))}
        </div>
      )}

      {connectFor !== null && config && (
        <ConnectDialog
          config={config}
          initialEmail={connectFor}
          onClose={() => setConnectFor(null)}
          onConnected={(c, folders) => {
            upsert(c);
            setConnectFor(null);
            toast.success(folders ? `${c.email_address} connected · ${folders} folders found` : `${c.email_address} connected`);
          }}
        />
      )}

      {disconnecting && (
        <ConfirmDialog
          title={`Disconnect ${disconnecting.email_address}?`}
          confirmLabel="Disconnect"
          onClose={() => setDisconnecting(null)}
          onConfirm={async () => {
            await api.delete(`/mail/connections/${disconnecting.id}`);
            setDisconnecting(null);
            toast.success("Mailbox disconnected");
            await load();
          }}
        >
          FareQube stops reading this mailbox and deletes its stored access
          {disconnecting.provider === "gmail" ? " (and revokes it with Google)" : ""}.
          {disconnecting.provider === "relay" ? " The forwarding address stops working." : ""} Documents already
          imported from it are kept.
        </ConfirmDialog>
      )}
    </div>
  );
}

// ── empty state ─────────────────────────────────────────────────────────────

function EmptyState({ canConnect, onConnect }: { canConnect: boolean; onConnect: () => void }) {
  const points = [
    { icon: Inbox, title: "Only onboarded senders", text: "Mail from your masters' addresses and their company domains. Anyone else is never opened." },
    { icon: Lock, title: "Read-only", text: "FareQube cannot send, delete, move or mark mail as read." },
    { icon: ShieldCheck, title: "Encrypted access", text: "Passwords and tokens are stored encrypted." },
  ];
  return (
    <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
      <div className="px-8 pt-10 pb-8 text-center">
        <div className="mx-auto w-12 h-12 rounded-2xl flex items-center justify-center bg-[#1e3a5f]/10">
          <Mail className="w-6 h-6" style={{ color: BRAND_COLOR }} />
        </div>
        <h2 className="mt-4 text-base font-semibold text-gray-900">Connect your first mailbox</h2>
        <p className="mt-1 text-sm text-gray-500 max-w-md mx-auto">
          Works with Gmail, Microsoft 365, Zoho, GoDaddy, Rediff and any IMAP mailbox.
        </p>
        {canConnect
          ? <button onClick={onConnect} className={`${PRIMARY} mt-5`} style={{ background: BRAND_COLOR }}><Plus className="w-4 h-4" /> Connect mailbox</button>
          : <p className="mt-5 text-xs text-gray-500">Ask your Super Admin to connect a mailbox.</p>}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 border-t border-gray-100 bg-gray-50/60">
        {points.map(p => (
          <div key={p.title} className="px-6 py-4 flex gap-3">
            <p.icon className="w-4 h-4 mt-0.5 text-emerald-600 shrink-0" />
            <div>
              <p className="text-xs font-semibold text-gray-800">{p.title}</p>
              <p className="text-xs text-gray-500 mt-0.5">{p.text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── a connected mailbox ─────────────────────────────────────────────────────

function Toggle({ checked, disabled, onChange }: { checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${checked ? "bg-emerald-500" : "bg-gray-300"}`}>
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
    </button>
  );
}

function MailboxCard({ conn, onChanged, onReconnect, onDisconnect }: {
  conn: MailConnection;
  onChanged: (c: MailConnection) => void;
  onReconnect: () => void;
  onDisconnect: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const style = brandOf(conn.provider, conn.settings.provider_key);
  const meta = STATUS_META[conn.status];
  const needsReauth = conn.status === "needs_reauth";

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  const call = async (fn: () => Promise<MailConnection>, ok?: string) => {
    setBusy(true); setMenu(false);
    try { onChanged(await fn()); if (ok) toast.success(ok); }
    catch (e) { toast.error(apiError(e)); }
    finally { setBusy(false); }
  };
  const save = (patch: Partial<MailConnection["settings"]>) =>
    call(async () => (await api.patch<MailConnection>(`/mail/connections/${conn.id}`, patch)).data);
  const pauseOrResume = () => {
    const action = conn.status === "paused" ? "resume" : "pause";
    return call(async () => (await api.post<MailConnection>(`/mail/connections/${conn.id}/${action}`)).data,
                action === "pause" ? "Mailbox paused" : "Mailbox resumed");
  };

  const providerName = PROVIDER_NAME[conn.settings.provider_key ?? ""] ??
    (conn.provider === "gmail" ? "Google" : conn.provider === "microsoft" ? "Microsoft" : conn.provider === "relay" ? "Forwarding" : "IMAP");
  const subtitle = conn.provider === "imap" ? `${providerName} · ${conn.imap_host}`
    : conn.provider === "relay" ? "Forwarding address" : `${providerName} sign-in`;

  return (
    <div className="rounded-2xl border border-gray-200 bg-white">
      <div className="flex items-center gap-4 p-5">
        <div className={`w-11 h-11 rounded-xl ring-1 flex items-center justify-center text-sm font-bold ${style.tile}`}>{style.short}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-gray-900 truncate">{conn.email_address}</p>
            <span className={`inline-flex items-center gap-1 text-[11px] font-medium border rounded-full px-2 py-0.5 ${meta.badge}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${conn.status === "active" ? "bg-emerald-500" : conn.status === "paused" ? "bg-slate-400" : "bg-amber-500"}`} />
              {meta.label}
            </span>
            {conn.visibility === "workspace" && (
              <span className="text-[11px] font-medium border rounded-full px-2 py-0.5 bg-violet-50 text-violet-700 border-violet-200">Shared</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 truncate">
            {subtitle} · connected {fmtWhen(conn.created_at)}{!conn.is_mine && ` by ${conn.owner.name}`}
          </p>
        </div>

        <div className="relative" ref={menuRef}>
          <button onClick={() => setMenu(m => !m)} disabled={busy} aria-label="Mailbox actions"
                  className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-50">
            {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <MoreHorizontal className="w-4 h-4" />}
          </button>
          {menu && (
            <div className="absolute right-0 mt-1 w-44 rounded-xl border border-gray-200 bg-white shadow-lg py-1 z-10 text-sm">
              {(conn.status === "active" || conn.status === "paused" || conn.status === "error") && (
                <button onClick={pauseOrResume} className="w-full flex items-center gap-2 px-3 py-2 text-gray-700 hover:bg-gray-50">
                  {conn.status === "paused" ? <><Play className="w-4 h-4" /> Resume</> : <><Pause className="w-4 h-4" /> Pause</>}
                </button>
              )}
              {needsReauth && (
                <button onClick={() => { setMenu(false); onReconnect(); }} className="w-full flex items-center gap-2 px-3 py-2 text-gray-700 hover:bg-gray-50">
                  <RefreshCw className="w-4 h-4" /> Reconnect
                </button>
              )}
              <button onClick={() => { setMenu(false); onDisconnect(); }} className="w-full flex items-center gap-2 px-3 py-2 text-red-600 hover:bg-red-50">
                <Trash2 className="w-4 h-4" /> Disconnect
              </button>
            </div>
          )}
        </div>
      </div>

      {needsReauth && (
        <div className="mx-5 mb-4 flex flex-wrap items-center gap-3 rounded-xl bg-amber-50 border border-amber-200 px-4 py-2.5 text-xs text-amber-800">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{conn.status_reason ?? "FareQube can no longer sign in to this mailbox."}</span>
          <button onClick={onReconnect} className="font-semibold underline underline-offset-2">Reconnect</button>
        </div>
      )}

      {conn.forwarding_address && <ForwardingHelp address={conn.forwarding_address} />}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-gray-100 border-t border-gray-100 rounded-b-2xl overflow-hidden">
        <div className="bg-white px-5 py-3.5">
          <p className={LABEL}>Folders</p>
          <div className="flex flex-wrap gap-1.5">
            {(conn.settings.folders ?? ["INBOX"]).map(f => (
              <span key={f} className="text-xs bg-gray-100 text-gray-700 rounded-md px-2 py-0.5">{f === "INBOX" ? "Inbox" : f}</span>
            ))}
          </div>
        </div>
        <div className="bg-white px-5 py-3.5">
          <p className={LABEL}>Junk / Spam</p>
          <div className="flex items-center gap-2.5">
            <Toggle checked={conn.settings.include_spam ?? true} disabled={busy} onChange={v => save({ include_spam: v })} />
            <span className="text-xs text-gray-600">Check for onboarded senders</span>
          </div>
        </div>
        <div className="bg-white px-5 py-3.5">
          <p className={LABEL}>Earlier mail</p>
          <select className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white" disabled={busy}
                  value={conn.settings.backfill_days ?? 30} onChange={e => save({ backfill_days: Number(e.target.value) })}>
            {BACKFILL_OPTIONS.map(d => <option key={d} value={d}>Import the last {d} days</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}

function ForwardingHelp({ address }: { address: string }) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(address); toast.success("Address copied"); } catch { /* clipboard blocked */ }
  };
  return (
    <div className="mx-5 mb-4 rounded-xl border border-violet-100 bg-violet-50/50 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-700">Forward mail to</span>
        <code className="text-xs px-2.5 py-1 bg-white border border-gray-200 rounded-md font-mono text-gray-900">{address}</code>
        <button onClick={copy} className="inline-flex items-center gap-1 text-xs font-medium text-violet-700 hover:underline">
          <Copy className="w-3.5 h-3.5" /> Copy
        </button>
      </div>
      <ul className="text-xs text-gray-600 space-y-1.5">
        <li><b>Gmail</b> — Settings → Forwarding and POP/IMAP → Add a forwarding address, then a filter for your onboarded senders → Forward it to this address.</li>
        <li><b>Outlook / Microsoft 365</b> — Rules → Forward to this address. If your organisation blocks forwarding outside, use Sign in with Microsoft instead.</li>
        <li><b>Zoho and others</b> — a filter that forwards mail from your onboarded senders to this address.</li>
      </ul>
    </div>
  );
}

// ── connect dialog ──────────────────────────────────────────────────────────
//
// Step 1: the address. Step 2: the provider — the detected one is pre-selected, the popular
// ones are tiles, the rest sit under "More providers". Step 3: what that provider needs —
// "Continue with Google / Microsoft", or the IMAP form pre-filled with the provider's server
// and its exact app-password steps (services/mail/providers.py is the single source).

function ConnectDialog({ config, initialEmail, onClose, onConnected }: {
  config: MailConfig;
  initialEmail: string;
  onClose: () => void;
  onConnected: (c: MailConnection, folders?: number) => void;
}) {
  const [step, setStep] = useState<"email" | "provider">("email");
  const [email, setEmail] = useState(initialEmail);
  const [detected, setDetected] = useState<DetectResult | null>(null);
  const [catalogue, setCatalogue] = useState<ProviderInfo[]>([]);
  const [choice, setChoice] = useState<string | null>(null);      // provider key, or "relay"
  const [showMore, setShowMore] = useState(false);
  const [workspace, setWorkspace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const visibility = workspace ? "workspace" : "personal";

  useEffect(() => {
    api.get<ProviderInfo[]>("/mail/providers").then(({ data }) => setCatalogue(data)).catch(() => setCatalogue([]));
  }, []);

  const runDetect = async () => {
    setError(""); setBusy(true);
    try {
      const { data } = await api.get<DetectResult>("/mail/detect", { params: { email } });
      setDetected(data);
      setEmail(data.email_address);
      setChoice(data.provider_key);
      setStep("provider");
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };

  // Reconnect opens straight onto the provider step — once, when the dialog opens.
  useEffect(() => {
    if (initialEmail) void runDetect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startOAuth = async (connector: "gmail" | "microsoft") => {
    setError(""); setBusy(true);
    try {
      const path = connector === "gmail" ? "google" : "microsoft";
      const { data } = await api.post<{ url: string }>(`/mail/connections/${path}/start`, { login_hint: email, visibility });
      window.location.href = data.url;           // leaves the app; the callback brings the user back
    } catch (e) { setError(apiError(e)); setBusy(false); }
  };

  const chosen = catalogue.find(p => p.key === choice) ?? null;
  const popular = catalogue.filter(p => p.popular);
  const more = catalogue.filter(p => !p.popular);
  const chosenIsMore = !!chosen && !chosen.popular;

  const tile = (p: ProviderInfo) => {
    const active = choice === p.key;
    const brand = BRAND[p.key] ?? BRAND.other;
    return (
      <button key={p.key} type="button" disabled={!p.available}
              onClick={() => { setChoice(p.key); setError(""); }}
              className={`relative text-left rounded-xl border p-3.5 transition disabled:cursor-not-allowed disabled:opacity-55 ${active ? "border-[#1e3a5f] bg-[#1e3a5f]/[0.03] ring-2 ring-[#1e3a5f]/15" : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"}`}>
        <div className="flex items-center gap-2.5">
          <div className={`w-8 h-8 rounded-lg ring-1 flex items-center justify-center text-[11px] font-bold shrink-0 ${brand.tile}`}>{brand.short}</div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900">{p.name}</p>
            <p className="text-[11px] text-gray-500 line-clamp-2">
              {!p.available ? p.reason : p.connector !== "imap" && !p.oauth_available ? `${p.blurb} · app password` : p.blurb}
            </p>
          </div>
        </div>
        {detected?.provider_key === p.key && (
          <span className="absolute top-2 right-2 text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">Detected</span>
        )}
        {active && <Check className="absolute bottom-2.5 right-2.5 w-4 h-4" style={{ color: BRAND_COLOR }} />}
      </button>
    );
  };

  return (
    <ModalShell title="Connect a mailbox" onClose={onClose} wide>
      {step === "email" && (
        <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (email.trim()) void runDetect(); }}>
          <div>
            <label className={LABEL}>Email address</label>
            <input autoFocus className={INPUT} type="email" placeholder="accounts@youragency.in"
                   value={email} onChange={e => setEmail(e.target.value)} />
            <p className="text-xs text-gray-500 mt-1.5">
              The address where your suppliers and airlines send deals and statements. Works with Gmail, Microsoft 365,
              Outlook, GoDaddy, Zoho, Yahoo, iCloud, Rediffmail and any other mail host.
            </p>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex justify-end">
            <button type="submit" disabled={busy || !email.trim()} className={PRIMARY} style={{ background: BRAND_COLOR }}>
              {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Continue
            </button>
          </div>
        </form>
      )}

      {step === "provider" && detected && (
        <div className="space-y-5">
          <div className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-gray-900 truncate">{email}</p>
              <p className="text-xs text-gray-500">{detected.provider_key ? `Looks like ${detected.label}` : "Pick your mail provider below"}</p>
            </div>
            <button onClick={() => { setStep("email"); setChoice(null); setError(""); }}
                    className="inline-flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900">
              <ArrowLeft className="w-3.5 h-3.5" /> Change
            </button>
          </div>

          <div>
            <p className={LABEL}>Mail provider</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {popular.map(tile)}
              {config.providers.relay?.available && (
                <button type="button" onClick={() => { setChoice("relay"); setError(""); }}
                        className={`relative text-left rounded-xl border p-3.5 transition ${choice === "relay" ? "border-[#1e3a5f] bg-[#1e3a5f]/[0.03] ring-2 ring-[#1e3a5f]/15" : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"}`}>
                  <div className="flex items-center gap-2.5">
                    <div className={`w-8 h-8 rounded-lg ring-1 flex items-center justify-center text-[11px] font-bold ${BRAND.relay.tile}`}>{BRAND.relay.short}</div>
                    <div><p className="text-sm font-semibold text-gray-900">Forwarding</p><p className="text-[11px] text-gray-500">No sign-in — your mail rule forwards to FareQube</p></div>
                  </div>
                  {choice === "relay" && <Check className="absolute bottom-2.5 right-2.5 w-4 h-4" style={{ color: BRAND_COLOR }} />}
                </button>
              )}
            </div>
            {more.length > 0 && (
              <div className="mt-2.5">
                <button type="button" onClick={() => setShowMore(s => !s)}
                        className="inline-flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900">
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showMore || chosenIsMore ? "rotate-180" : ""}`} />
                  More providers ({more.map(p => p.name).join(", ")})
                </button>
                {(showMore || chosenIsMore) && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mt-2.5">{more.map(tile)}</div>
                )}
              </div>
            )}
          </div>

          {config.can_connect_workspace && choice && (
            <label className="flex items-start gap-2.5 text-xs text-gray-600">
              <input type="checkbox" className="mt-0.5" checked={workspace} onChange={e => setWorkspace(e.target.checked)} />
              <span><b className="text-gray-800">Shared workspace mailbox</b> (such as accounts@) — documents go to whichever colleague onboarded the sender.</span>
            </label>
          )}

          {chosen && chosen.connector !== "imap" && chosen.oauth_available && (
            <OAuthPanel provider={chosen} busy={busy} onStart={() => startOAuth(chosen.connector as "gmail" | "microsoft")} />
          )}
          {chosen && chosen.connector !== "imap" && !chosen.oauth_available && chosen.imap_alternative && (
            // Google without a sign-in app on this server: the same mailbox over IMAP with an app password.
            <ImapForm key={`${chosen.key}-imap`} provider={asImap(chosen)} email={email} detectedHost={null}
                      intro={`${chosen.name} sign-in is not set up on this server yet, so connect with a ${chosen.name} app password — it takes a minute and is just as read-only.`}
                      visibility={visibility} onConnected={r => onConnected(r.connection, r.test.folders?.length)} />
          )}
          {chosen && chosen.connector !== "imap" && !chosen.oauth_available && !chosen.imap_alternative && (
            <div className="flex gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{chosen.reason} Until then, a forwarding rule in {chosen.name} to FareQube works without sign-in.</span>
            </div>
          )}
          {chosen && chosen.connector === "imap" && (
            <ImapForm key={chosen.key} provider={chosen} email={email}
                      detectedHost={detected.provider_key === chosen.key ? detected.imap_host : null}
                      catalogue={chosen.key === "other" ? catalogue : undefined}
                      onSwitch={key => { setChoice(key); setError(""); }}
                      visibility={visibility} onConnected={r => onConnected(r.connection, r.test.folders?.length)} />
          )}
          {choice === "relay" && (
            <RelayPanel email={email} visibility={visibility} onConnected={r => onConnected(r.connection)} />
          )}

          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}
    </ModalShell>
  );
}

function Steps({ provider }: { provider: ProviderInfo }) {
  if (!provider.steps.length) return null;
  return (
    <div className="rounded-lg bg-sky-50 border border-sky-100 px-3.5 py-3 text-xs text-sky-900 space-y-1.5">
      <ol className="list-decimal pl-4 space-y-1">
        {provider.steps.map(s => <li key={s}>{s}</li>)}
      </ol>
      {provider.help_url && (
        <a href={provider.help_url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 font-semibold text-sky-800 hover:underline">
          Open {provider.name} settings <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}

function OAuthPanel({ provider, busy, onStart }: { provider: ProviderInfo; busy: boolean; onStart: () => void }) {
  return (
    <div className="rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex gap-2.5 text-xs text-gray-600">
        <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
        <p>
          You sign in on {provider.name}&apos;s own page — FareQube never sees your password — and allow FareQube to
          <b> read</b> your mail. It cannot send, delete or change anything.
        </p>
      </div>
      <Steps provider={provider} />
      <div className="flex justify-end">
        <button disabled={busy} onClick={onStart} className={PRIMARY} style={{ background: BRAND_COLOR }}>
          {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Continue with {provider.name}
        </button>
      </div>
    </div>
  );
}

/** A sign-in provider seen as its IMAP route (Google with an app password). */
function asImap(p: ProviderInfo): ProviderInfo {
  const alt = p.imap_alternative!;
  return { ...p, connector: "imap", imap_host: alt.host, imap_port: alt.port, password_label: alt.password_label,
           steps: alt.steps, help_url: alt.help_url, regions: [] };
}

// "Other (IMAP)": the user may not know their provider is one we list, or only knows who hosts
// their website. Picking from this list fills the server, port and steps — a listed provider
// switches to its own tile (Zoho's data centre, iCloud's username, Google's app password…);
// a web-host pattern fills the server from the address's domain.
const HOST_PATTERNS: { value: string; label: (domain: string) => string; host: (domain: string) => string; note: string }[] = [
  { value: "pattern:mail", label: d => `cPanel / Plesk / my web host (mail.${d})`, host: d => `mail.${d}`,
    note: "Most web hosts (cPanel, Plesk, Bluehost, HostGator, BigRock, shared hosting) use mail.<your domain> on port 993 with your email password." },
  { value: "pattern:imap", label: d => `My host uses imap.${d}`, host: d => `imap.${d}`,
    note: "Some hosts name the server imap.<your domain>. Your host's email setup page shows the exact name." },
];

function ProviderPicker({ catalogue, email, onSwitch, onPattern }: {
  catalogue: ProviderInfo[]; email: string; onSwitch: (key: string) => void;
  onPattern: (host: string, note: string) => void;
}) {
  const [value, setValue] = useState("");
  const domain = email.split("@")[1] ?? "yourdomain.com";
  const listed = catalogue.filter(p => p.key !== "other");
  const server = (p: ProviderInfo) =>
    p.imap_host ? ` — ${p.imap_host}`
      : p.imap_alternative && !p.oauth_available ? ` — ${p.imap_alternative.host} (app password)`
      : p.oauth_available ? " — sign in" : "";
  return (
    <div>
      <label className={LABEL}>Who provides this mailbox?</label>
      <select className={INPUT} value={value} onChange={e => {
        const v = e.target.value; setValue(v);
        const pat = HOST_PATTERNS.find(p => p.value === v);
        if (pat) onPattern(pat.host(domain), pat.note);
        else if (v && v !== "manual") onSwitch(v);
      }}>
        <option value="">Choose your provider — the server fills in for you</option>
        <optgroup label="Mail providers">
          {listed.map(p => (
            <option key={p.key} value={p.key}>{p.name}{server(p)}{!p.available ? " (needs admin setup)" : ""}</option>
          ))}
        </optgroup>
        <optgroup label="Website hosting">
          {HOST_PATTERNS.map(p => <option key={p.value} value={p.value}>{p.label(domain)}</option>)}
        </optgroup>
        <option value="manual">Not listed — I&apos;ll type the server</option>
      </select>
    </div>
  );
}

function ImapForm({ provider, email, detectedHost, visibility, onConnected, catalogue, onSwitch, intro }: {
  provider: ProviderInfo; email: string; detectedHost: string | null; visibility: string;
  onConnected: (r: ConnectResult) => void;
  /** "Other (IMAP)" only: the catalogue for the provider dropdown. */
  catalogue?: ProviderInfo[];
  onSwitch?: (key: string) => void;
  intro?: string;
}) {
  const [patternNote, setPatternNote] = useState("");
  const isZoho = provider.regions.length > 0;
  const initialHost = detectedHost ?? provider.imap_host ?? "";
  const [region, setRegion] = useState(() => provider.regions.find(r => r.host === initialHost || r.free_host === initialHost)?.code ?? provider.regions[0]?.code ?? "");
  const [host, setHost] = useState(initialHost);
  const [port, setPort] = useState<number>(provider.imap_port || 993);
  // iCloud logs in with the part before the @; everyone else with the full address.
  const [username, setUsername] = useState(provider.key === "icloud" ? email.split("@")[0] : email);
  const [password, setPassword] = useState("");
  const [includeSpam, setIncludeSpam] = useState(true);
  const [advanced, setAdvanced] = useState(provider.key === "other" || !initialHost);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const pickRegion = (code: string) => {
    setRegion(code);
    const r = provider.regions.find(x => x.code === code);
    if (r) setHost(r.host);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const { data } = await api.post<ConnectResult>("/mail/connections/imap", {
        email_address: email, host, port, username, password, visibility, include_spam: includeSpam,
        provider_key: provider.key,
      });
      setPassword("");
      onConnected(data);
    } catch (err) { setError(apiError(err)); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="rounded-xl border border-gray-200 p-4 space-y-4">
      {intro && <p className="text-xs text-gray-600">{intro}</p>}
      {catalogue && onSwitch && (
        <ProviderPicker catalogue={catalogue} email={email} onSwitch={onSwitch}
                        onPattern={(h, note) => { setHost(h); setPort(993); setPatternNote(note); setAdvanced(true); }} />
      )}
      {patternNote ? (
        <p className="rounded-lg bg-sky-50 border border-sky-100 px-3.5 py-2.5 text-xs text-sky-900">{patternNote}</p>
      ) : <Steps provider={provider} />}

      {isZoho && (
        <div>
          <label className={LABEL}>Zoho data centre</label>
          <select className={INPUT} value={region} onChange={e => pickRegion(e.target.value)}>
            {provider.regions.map(r => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
          <p className="text-[11px] text-gray-400 mt-1">Paid and free Zoho accounts use different servers — FareQube tries both.</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Username</label>
          <input className={INPUT} required value={username} onChange={e => setUsername(e.target.value)} />
        </div>
        <div>
          <label className={LABEL}>{provider.password_label}</label>
          <input className={INPUT} required type="password" autoComplete="new-password" value={password}
                 onChange={e => setPassword(e.target.value)} />
        </div>
      </div>

      {advanced ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="sm:col-span-2">
            <label className={LABEL}>IMAP server</label>
            <input className={INPUT} required placeholder="mail.yourdomain.com" value={host} onChange={e => setHost(e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>Port</label>
            <select className={INPUT} value={port} onChange={e => setPort(Number(e.target.value))}>
              {IMAP_PORTS.map(p => <option key={p.port} value={p.port}>{p.label}</option>)}
            </select>
          </div>
        </div>
      ) : (
        <p className="text-xs text-gray-500">
          Server <span className="font-mono text-gray-700">{host}:{port}</span> ·{" "}
          <button type="button" onClick={() => setAdvanced(true)} className="font-medium text-gray-700 underline underline-offset-2">change</button>
        </p>
      )}

      <label className="flex items-center gap-2.5 text-xs text-gray-600">
        <input type="checkbox" checked={includeSpam} onChange={e => setIncludeSpam(e.target.checked)} />
        Also check Junk / Spam — a supplier&apos;s statement there is still a statement
      </label>
      {error && (
        <div className="flex gap-2 rounded-lg bg-red-50 border border-red-100 px-3 py-2.5 text-xs text-red-700">
          <AlertTriangle className="w-4 h-4 shrink-0" /><span>{error}</span>
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[11px] text-gray-400"><Lock className="w-3.5 h-3.5" /> Stored encrypted. Read-only.</p>
        <button disabled={busy || !host} className={PRIMARY} style={{ background: BRAND_COLOR }}>
          {busy ? <><RefreshCw className="w-4 h-4 animate-spin" /> Connecting…</> : <>Connect {provider.name}</>}
        </button>
      </div>
    </form>
  );
}

function RelayPanel({ email, visibility, onConnected }: {
  email: string; visibility: string; onConnected: (r: ConnectResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const create = async () => {
    setError(""); setBusy(true);
    try {
      const { data } = await api.post<ConnectResult>("/mail/connections/relay", { email_address: email, visibility });
      onConnected(data);
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border border-gray-200 p-4 space-y-3">
      <p className="text-xs text-gray-600">
        FareQube creates a private address for you. A rule in your mail forwards mail from your onboarded senders to
        it — FareQube never signs in to your mailbox.
      </p>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex justify-end">
        <button disabled={busy} onClick={create} className={PRIMARY} style={{ background: BRAND_COLOR }}>
          {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Forward className="w-4 h-4" />} Create forwarding address
        </button>
      </div>
    </div>
  );
}
