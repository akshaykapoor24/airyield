"use client";

// Email intake → "Process this email". Lists everything the email carries that can be imported —
// statements and deals in attachments, tables pasted in the body, a deal written as text — and
// imports each through the module's OWN screen, so validation, duplicate checks, commission
// projections and approvals are exactly those of a manual upload (architecture/07).
//
//   statement  → the matching Vendor statements wizard opens here as a modal, with the file
//                loaded and the sender's agency picked (third-party types), period / control
//                totals from the covering note where the wizard asks for them
//   deal       → the Incoming deals upload opens with the deal sheet loaded and the sender as
//                the B2B supplier (a table or a text deal becomes a sheet first)
//   bank       → the Bank statement import, directly
//   other      → "Import as…" lets the user say what it is
//
// When an import is saved, the email remembers it ("Imported ✓"), so nothing is imported twice
// by accident — "Import again" clears the mark when that is what the user wants.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import {
  CheckCircle2, ChevronDown, FileSpreadsheet, FileText, Handshake, Info, MessageSquareText, RefreshCw, Table2, Wand2,
} from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import { familyBadge, fmtWhen } from "@/lib/emailIntake";
import { getType } from "@/lib/statements";
import StatementUploadWizard from "@/components/statements/StatementUploadWizard";
import LccUploadWizard from "@/components/statements/lcc/LccUploadWizard";
import BspUploadWizard from "@/components/statements/bsp/BspUploadWizard";
import { UploadModal } from "@/components/statements/AdjustmentStatementsView";

const BRAND = "#1e3a5f";

type PlanItem = {
  key: string;
  source: "attachment" | "table" | "text";
  attachment_id?: number;
  table_index?: number;
  title: string;
  kind: "statement" | "deal" | "other";
  doc_type: string | null;
  family: string | null;
  label: string | null;
  confidence: number | null;
  reason: string | null;
  rows: number | null;
  preview?: string[][];
  preview_text?: string;
  imported: { destination: string; ref: string | null; at: string; by: number } | null;
};

type Plan = {
  message_id: number;
  subject: string | null;
  sender: { party_type: string | null; label: string | null; segment: string | null; agency_id: number | null; agency_ids: number[] };
  facts: { period_from?: string; period_to?: string; effective_from?: string; valid_to?: string;
           expected_count?: number; expected_amount?: string };
  items: PlanItem[];
};

// Statement type (classifier) → the Vendor statements screen that imports it.
const STATEMENT_TARGET: Record<string, { category: string; type: string; label: string }> = {
  "bsp":              { category: "bsp", type: "bsp", label: "BSP · Billing detail" },
  "bsp-summary":      { category: "bsp", type: "bsp", label: "BSP · Billing summary" },
  "tgq-hmpr":         { category: "bsp", type: "tgq-hmpr", label: "TGQ HMPR" },
  "ndc":              { category: "bsp", type: "ndc", label: "NDC statement" },
  "lcc-detailed":     { category: "lcc", type: "statement-detailed", label: "LCC · Detailed statement" },
  "lcc-di":           { category: "lcc", type: "di", label: "LCC · DI statement" },
  "lcc-divided-pnr":  { category: "lcc", type: "divided-pnr", label: "LCC · Divided PNR" },
  "lcc-flown-report": { category: "lcc", type: "flown-report", label: "LCC · Flown report" },
  "lcc-cta-bta":      { category: "lcc", type: "cta-bta", label: "LCC · CTA/BTA report" },
  "tp-gds":           { category: "third-party", type: "gds", label: "Third party · GDS" },
  "tp-lcc":           { category: "third-party", type: "lcc", label: "Third party · LCC" },
  "tp-api":           { category: "third-party", type: "api", label: "Third party · API" },
};
// What "Import as…" offers for a file the classifier could not place.
const IMPORT_AS: { value: string; label: string }[] = [
  ...Object.entries(STATEMENT_TARGET).filter(([k]) => k !== "bsp-summary").map(([value, t]) => ({ value, label: t.label })),
  { value: "bank", label: "Bank statement" },
  { value: "deal", label: "Deal sheet (Incoming deals)" },
];

const MENU_MAX_H = 320;

function fileUrl(messageId: number, item: PlanItem): string {
  if (item.source === "attachment") return `/mail/attachments/${item.attachment_id}/download`;
  if (item.source === "table") return `/mail/messages/${messageId}/tables/${item.table_index}/file`;
  return `/mail/messages/${messageId}/text-deals/file`;
}

async function fetchFile(url: string, fallbackName: string): Promise<File> {
  try {
    const res = await api.get(url, { responseType: "blob" });
    const cd = String(res.headers["content-disposition"] ?? "");
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : fallbackName;
    const blob = res.data as Blob;
    return new File([blob], name, { type: blob.type || "application/octet-stream" });
  } catch (e) {
    const data = (e as { response?: { data?: unknown } })?.response?.data;
    if (data instanceof Blob) {
      try { const j = JSON.parse(await data.text()); if (typeof j.detail === "string") throw new Error(j.detail); }
      catch (inner) { if (inner instanceof Error && inner.message) throw inner; }
    }
    throw new Error(apiError(e));
  }
}

type Open =
  | { kind: "mapping" | "oneshot"; item: PlanItem; docType: string; file: File; apiBase: string; title: string;
      requiresSupplier: boolean; requiresAirlineId: boolean; doneHint?: string }
  | { kind: "lcc"; item: PlanItem; docType: string; files: File[]; apiBase: string; title: string }
  | { kind: "bsp"; item: PlanItem; docType: string; detail: File | null; summary: File | null };

export default function ProcessPanel({ messageId }: { messageId: number }) {
  const router = useRouter();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [open, setOpen] = useState<Open | null>(null);

  const load = useCallback(async () => {
    try { setPlan((await api.get<Plan>(`/mail/messages/${messageId}/process`)).data); setError(""); }
    catch (e) { setError(apiError(e)); }
  }, [messageId]);
  useEffect(() => { void load(); }, [load]);

  const markDone = async (item: PlanItem, destination: string, ref?: string | null) => {
    try { await api.post(`/mail/messages/${messageId}/processed`, { key: item.key, destination, ref: ref ?? null }); }
    catch { /* the import itself succeeded; the mark is a convenience */ }
    await load();
  };

  const unmark = async (item: PlanItem) => {
    await api.delete(`/mail/messages/${messageId}/processed/${encodeURIComponent(item.key)}`).catch(() => {});
    await load();
  };

  const dealLink = (item: PlanItem) => {
    const q = new URLSearchParams({ from_mail: String(messageId), item: item.key });
    if (plan?.sender.agency_id != null) q.set("agency", String(plan.sender.agency_id));
    if (plan?.facts.effective_from) q.set("valid_from", plan.facts.effective_from);
    return `/deals/upload?${q.toString()}`;
  };

  const importAs = async (item: PlanItem, docType: string) => {
    if (docType === "deal") { router.push(dealLink(item)); return; }
    setBusyKey(item.key);
    try {
      const file = await fetchFile(fileUrl(messageId, item), item.title);
      if (docType === "bank") {
        const fd = new FormData(); fd.append("file", file);
        const { data } = await api.post<{ statement: { id: number }; inserted: number }>("/bank-statements/upload", fd);
        toast.success(`Bank statement imported · ${data.inserted} line${data.inserted === 1 ? "" : "s"}`);
        await markDone(item, "bank-statements", String(data.statement?.id ?? ""));
        return;
      }
      const target = STATEMENT_TARGET[docType];
      const cfg = target ? getType(target.category, target.type) : undefined;
      if (!target || !cfg) { toast.error("This statement type cannot be imported from here yet."); return; }
      if (cfg.kind === "bsp") {
        // A detail and its summary often arrive together — hand the wizard both.
        const other = plan?.items.find(i => i.key !== item.key && i.source === "attachment" &&
          (docType === "bsp" ? i.doc_type === "bsp-summary" : i.doc_type === "bsp"));
        const otherFile = other ? await fetchFile(fileUrl(messageId, other), other.title).catch(() => null) : null;
        setOpen({ kind: "bsp", item, docType,
                  detail: docType === "bsp" ? file : otherFile, summary: docType === "bsp-summary" ? file : otherFile });
      } else if (cfg.kind === "lcc-detailed") {
        setOpen({ kind: "lcc", item, docType, files: [file], apiBase: cfg.apiBase ?? "/lcc-detailed", title: cfg.label });
      } else {
        setOpen({
          kind: cfg.supportsMapping ? "mapping" : "oneshot", item, docType, file, apiBase: cfg.apiBase ?? "",
          title: cfg.label, requiresSupplier: !!cfg.requiresSupplier, requiresAirlineId: !!cfg.requiresAirlineId,
          doneHint: cfg.doneHint,
        });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load the file from the email.");
    } finally {
      setBusyKey(null);
    }
  };

  const facts = plan?.facts ?? {};
  const factChips: string[] = [];
  {
    const out = factChips;
    if (facts.period_from && facts.period_to) out.push(`Period ${fmtDay(facts.period_from)} – ${fmtDay(facts.period_to)}`);
    if (facts.effective_from) out.push(`Effective ${fmtDay(facts.effective_from)}`);
    if (facts.valid_to) out.push(`Valid till ${fmtDay(facts.valid_to)}`);
    if (facts.expected_count != null) out.push(`${facts.expected_count} records`);
    if (facts.expected_amount) out.push(`Net ₹${Number(facts.expected_amount).toLocaleString("en-IN")}`);
  }

  if (error) return null;               // the message itself still shows; the panel is an extra
  if (!plan) return <div className="mx-6 mt-4 h-20 rounded-xl bg-gray-50 animate-pulse" />;

  const done = plan.items.filter(i => i.imported).length;

  return (
    <section className="mx-6 mt-4 rounded-xl border border-gray-200 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 bg-gray-50 border-b border-gray-200">
        <Wand2 className="w-4 h-4" style={{ color: BRAND }} />
        <h3 className="text-sm font-semibold text-gray-900">Process this email</h3>
        {plan.items.length > 0 && (
          <span className="text-[11px] text-gray-500">{done} of {plan.items.length} imported</span>
        )}
        {plan.sender.label && (
          <span className="ml-auto text-[11px] text-gray-500 truncate">From {plan.sender.label}</span>
        )}
      </div>

      {factChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pt-3">
          <span className="text-[11px] text-gray-500">Read from the email:</span>
          {factChips.map(f => <span key={f} className="text-[11px] bg-white border border-gray-200 rounded-md px-1.5 py-px text-gray-700">{f}</span>)}
        </div>
      )}

      {plan.items.length === 0 ? (
        <div className="flex gap-2.5 px-4 py-4 text-xs text-gray-600">
          <Info className="w-4 h-4 shrink-0 text-gray-400" />
          <span>Nothing to import — this email has no statement or deal in its attachments or text.
            If the sender meant to attach one, it may have been forgotten.</span>
        </div>
      ) : (
        <ul className="divide-y divide-gray-100">
          {plan.items.map(item => (
            <ProcessRow key={item.key} item={item} busy={busyKey === item.key}
                        onImport={dt => void importAs(item, dt)} onDeal={() => router.push(dealLink(item))}
                        onAgain={() => void unmark(item)} />
          ))}
        </ul>
      )}

      {open?.kind === "mapping" && (
        <StatementUploadWizard apiBase={open.apiBase} title={open.title} requireSupplier={open.requiresSupplier}
          doneHint={open.doneHint}
          initialFile={open.file} initialAgencyId={plan.sender.agency_id}
          onClose={() => setOpen(null)}
          onDone={() => { const it = open.item; const dt = open.docType; setOpen(null); void markDone(it, `statements:${dt}`); }} />
      )}
      {open?.kind === "oneshot" && (
        <UploadModal apiBase={open.apiBase} title={open.title} requiresSupplier={open.requiresSupplier}
          requiresAirlineId={open.requiresAirlineId} initialFile={open.file} initialAgencyId={plan.sender.agency_id}
          onClose={() => setOpen(null)}
          onDone={() => { const it = open.item; const dt = open.docType; setOpen(null); void markDone(it, `statements:${dt}`); }} />
      )}
      {open?.kind === "lcc" && (
        <LccUploadWizard apiBase={open.apiBase} title={open.title} initialFiles={open.files}
          onClose={() => setOpen(null)}
          onDone={() => { const it = open.item; setOpen(null); void markDone(it, "lcc-detailed"); }} />
      )}
      {open?.kind === "bsp" && (
        <BspUploadWizard initialDetailFile={open.detail} initialSummaryFile={open.summary}
          onClose={() => setOpen(null)}
          onDone={() => { const it = open.item; setOpen(null); void markDone(it, "bsp"); }} />
      )}
    </section>
  );
}

function fmtDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function ProcessRow({ item, busy, onImport, onDeal, onAgain }: {
  item: PlanItem; busy: boolean; onImport: (docType: string) => void; onDeal: () => void; onAgain: () => void;
}) {
  // Where the open "Import as…" menu sits on screen; null when closed.
  const [choosing, setChoosing] = useState<{ right: number; top?: number; bottom?: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!choosing) return;
    const close = () => setChoosing(null);
    // The menu is fixed, so a page scroll would detach it — but scrolling the menu's own list is fine.
    const onScroll = (e: Event) => { if (!menuRef.current?.contains(e.target as Node)) close(); };
    window.addEventListener("resize", close);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("resize", close); window.removeEventListener("scroll", onScroll, true); };
  }, [choosing]);
  const Icon = item.source === "table" ? Table2 : item.source === "text" ? MessageSquareText
    : item.kind === "deal" ? Handshake : item.kind === "statement" ? FileSpreadsheet : FileText;
  const known = item.kind === "statement" && item.doc_type && item.doc_type !== "unknown" &&
    (STATEMENT_TARGET[item.doc_type] || item.doc_type === "bank");
  const badge = item.kind === "deal" ? "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200"
    : item.kind === "statement" ? familyBadge(item.family ?? "") : "bg-gray-50 text-gray-500 border-gray-200";

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <Icon className="w-5 h-5 shrink-0" style={{ color: BRAND }} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium text-gray-900 truncate max-w-[340px]" title={item.title}>{item.title}</p>
            <span className={`text-[10px] font-semibold border rounded px-1.5 py-px ${badge}`}>
              {item.kind === "other" ? "Not recognised" : item.label}
            </span>
          </div>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {item.reason}{item.rows ? ` · ${item.rows.toLocaleString("en-IN")} rows` : ""}
          </p>
        </div>

        {item.imported ? (
          <div className="flex items-center gap-2 text-[11px]">
            <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
              <CheckCircle2 className="w-4 h-4" /> Imported · {fmtWhen(item.imported.at)}
            </span>
            <button onClick={onAgain} className="text-gray-500 underline underline-offset-2 hover:text-gray-800">Import again</button>
          </div>
        ) : item.kind === "deal" ? (
          <button onClick={onDeal} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white" style={{ background: BRAND }}>
            <Handshake className="w-3.5 h-3.5" /> {item.source === "text" ? "Read deal & review" : "Review & save deal"}
          </button>
        ) : known ? (
          <button disabled={busy} onClick={() => onImport(item.doc_type as string)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-50" style={{ background: BRAND }}>
            {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5" />} Review & import
          </button>
        ) : item.doc_type === "mo-gds" ? (
          <a href="/vendors/payment-module" className="text-xs font-medium text-gray-700 underline">Open Payment Module</a>
        ) : (
          <div>
            <button disabled={busy} onClick={e => {
                      if (choosing) { setChoosing(null); return; }
                      // Fixed to the viewport so the message card's overflow cannot clip it;
                      // opens upward when the button sits near the bottom of the screen.
                      const r = e.currentTarget.getBoundingClientRect();
                      const up = window.innerHeight - r.bottom < MENU_MAX_H + 12 && r.top > window.innerHeight - r.bottom;
                      setChoosing({ right: window.innerWidth - r.right, ...(up ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }) });
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-700 border border-gray-200 hover:bg-gray-50 disabled:opacity-50">
              {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null} Import as… <ChevronDown className="w-3.5 h-3.5" />
            </button>
            {choosing && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setChoosing(null)} />
                <div ref={menuRef} className="fixed z-50 w-64 overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-xl py-1"
                     style={{ ...choosing, maxHeight: MENU_MAX_H }}>
                  <p className="px-3 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">This file is a…</p>
                  {IMPORT_AS.map(o => (
                    <button key={o.value} onClick={() => { setChoosing(null); if (o.value === "deal") onDeal(); else onImport(o.value); }}
                            className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50">{o.label}</button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {item.preview && item.preview.length > 0 && !item.imported && (
        <div className="mt-2 ml-8 overflow-x-auto rounded-lg border border-gray-100">
          <table className="text-[11px]">
            <tbody>
              {item.preview.map((r, i) => (
                <tr key={i} className={i === 0 ? "bg-gray-50 font-semibold text-gray-700" : "text-gray-600"}>
                  {r.slice(0, 8).map((c, j) => <td key={j} className="px-2 py-1 whitespace-nowrap max-w-[160px] truncate">{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {item.preview_text && !item.imported && (
        <pre className="mt-2 ml-8 max-h-28 overflow-y-auto whitespace-pre-wrap rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-[11px] text-gray-600 font-sans">{item.preview_text}</pre>
      )}
    </li>
  );
}
