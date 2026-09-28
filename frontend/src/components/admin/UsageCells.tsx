"use client";

/**
 * The Subscriptions console's cost columns — OpenAI, stored files, Postgres — and the
 * platform-total tiles above the table. Shapes mirror backend/app/schemas/subscription.py;
 * how each figure is measured is documented in backend/app/services/tenant_resources.py.
 */

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { CloudUpload, Database, HardDrive, Sparkles, type LucideIcon } from "lucide-react";

export type AiUsageLine = { label: string; calls: number; tokens: number; cost_usd: number };

export type AiUsage = {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  // Priced calls only; unpriced_calls > 0 means the real figure is higher.
  cost_usd: number;
  unpriced_calls: number;
  month_calls: number;
  month_cost_usd: number;
  by_feature: AiUsageLine[];
  by_member: AiUsageLine[];
};

export type StorageLine = { label: string; files: number; bytes: number };

export type FileUsage = {
  uploads: number;      // every upload, including since-deleted files
  files: number;        // stored right now
  bytes: number;
  gcs_bytes: number;
  local_bytes: number;
  by_source: StorageLine[];
  by_member: StorageLine[];
};

export type DbUsage = {
  bytes: number;
  share: number;        // of the whole database, 0..1
  by_area: { label: string; bytes: number }[];
  measured_at: string | null;
};

export type ResourceUsage = { ai: AiUsage; files: FileUsage; database: DbUsage | null };

export type PlatformUsage = {
  ai_calls: number;
  ai_cost_usd: number;
  ai_unpriced_calls: number;
  ai_month_calls: number;
  ai_month_cost_usd: number;
  uploads: number;
  files: number;
  gcs_bytes: number;
  local_bytes: number;
  unattributed_bytes: number;
  database_bytes: number;
  database_attributed_bytes: number;
  database_measured_at: string | null;
};

// ── formatting ───────────────────────────────────────────────────────────────

export function fmtBytes(n: number): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function fmtUsd(n: number): string {
  if (!n) return "$0.00";
  if (n < 0.01) return "<$0.01";
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtShare(share: number): string {
  if (!share) return "0%";
  const pct = share * 100;
  if (pct < 0.1) return "<0.1%";
  return `${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%`;
}

/** The API sends naive UTC; without a zone suffix the browser would read it as local time. */
function fmtAgo(v: string | null): string {
  if (!v) return "";
  const at = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`).getTime();
  const min = Math.round((Date.now() - at) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  return `${Math.round(min / 60)} h ago`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

// ── hover panel ──────────────────────────────────────────────────────────────

/**
 * A table cell with a breakdown panel behind a hover.
 *
 * The panel is `position: fixed` rather than `absolute` on purpose: the table sits inside
 * `overflow-x-auto`, and a non-visible overflow on one axis makes the browser clip the
 * other too — an absolutely positioned panel would be cut off at the first and last rows.
 * Fixed escapes that, and no ancestor of the table sets transform/filter/will-change, so it
 * resolves against the viewport. It is placed after it renders, once its size is known, so
 * a panel on the right-most column or the bottom row flips back onto the screen.
 */
export function HoverCell({ panel, className = "", children }: {
  panel: ReactNode | null;
  className?: string;
  children: ReactNode;
}) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // A fixed panel does not travel with the scroll container, so drop it rather than let it
  // hang over unrelated rows.
  useEffect(() => {
    if (!anchor) return;
    const close = () => setAnchor(null);
    window.addEventListener("scroll", close, true);
    return () => window.removeEventListener("scroll", close, true);
  }, [anchor]);

  // Written to the DOM, not to state: it runs before paint, so the panel never flashes at
  // its unclamped position, and it costs no second render.
  useLayoutEffect(() => {
    const el = panelRef.current;
    if (!anchor || !el) return;
    const gap = 8;
    const left = Math.max(gap, Math.min(anchor.left, window.innerWidth - el.offsetWidth - gap));
    let top = anchor.bottom + 6;
    if (top + el.offsetHeight > window.innerHeight - gap) {
      top = Math.max(gap, anchor.top - el.offsetHeight - 6);
    }
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    el.style.visibility = "visible";
  }, [anchor]);

  return (
    <td
      className={`px-4 py-3 text-xs tabular-nums ${className}`}
      onMouseEnter={panel ? (e) => setAnchor((e.currentTarget as HTMLElement).getBoundingClientRect()) : undefined}
      onMouseLeave={panel ? () => setAnchor(null) : undefined}
    >
      {children}
      {anchor && panel && (
        <div
          ref={panelRef}
          className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1.5 px-2 min-w-44 max-w-80 pointer-events-none"
          style={{ left: anchor.left, top: anchor.bottom + 6, visibility: "hidden" }}
        >
          {panel}
        </div>
      )}
    </td>
  );
}

export function PanelTitle({ children }: { children: ReactNode }) {
  return <p className="text-[9px] uppercase tracking-wide text-gray-400 px-1 pb-1">{children}</p>;
}

function PanelSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-1.5 pt-1.5 border-t border-gray-100">
      <PanelTitle>{title}</PanelTitle>
      {children}
    </div>
  );
}

export function PanelRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 px-1 py-0.5">
      <span className="text-[10px] text-gray-600 whitespace-nowrap truncate">{label}</span>
      <span className="text-[10px] text-gray-900 font-medium tabular-nums whitespace-nowrap">{value}</span>
    </div>
  );
}

function PanelNote({ children, tone = "text-gray-400" }: { children: ReactNode; tone?: string }) {
  return <p className={`text-[9px] ${tone} px-1 pt-1.5 leading-snug whitespace-normal`}>{children}</p>;
}

/** The two-line cell value: the headline and, under it, the figure that explains it. */
function Figure({ main, sub }: { main: ReactNode; sub?: ReactNode }) {
  return (
    <div className="cursor-default">
      <span className="text-gray-700 font-medium border-b border-dotted border-gray-300 whitespace-nowrap">{main}</span>
      {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

const Zero = () => <span className="text-gray-300">0</span>;

/** Metering could not be read (the server logs why). Not zero — zero would be an answer. */
export function UnavailableCell() {
  return (
    <td className="px-4 py-3 text-xs" title="Usage could not be read — see the server log.">
      <span className="text-gray-300">—</span>
    </td>
  );
}

// ── the three columns ────────────────────────────────────────────────────────

export function AiCell({ ai }: { ai: AiUsage }) {
  if (!ai.calls) return <HoverCell panel={null}><Zero /></HoverCell>;

  const panel = (
    <>
      <PanelTitle>OpenAI usage</PanelTitle>
      <PanelRow label="This month" value={`${plural(ai.month_calls, "call")} · ${fmtUsd(ai.month_cost_usd)}`} />
      <PanelRow label="All time" value={`${plural(ai.calls, "call")} · ${fmtUsd(ai.cost_usd)}`} />
      <PanelRow label="Tokens in / out" value={`${fmtTokens(ai.prompt_tokens)} / ${fmtTokens(ai.completion_tokens)}`} />
      {ai.by_feature.length > 0 && (
        <PanelSection title="By feature">
          {ai.by_feature.map((l) => (
            <PanelRow key={l.label} label={l.label} value={`${l.calls.toLocaleString()} · ${fmtUsd(l.cost_usd)}`} />
          ))}
        </PanelSection>
      )}
      {ai.by_member.length > 0 && (
        <PanelSection title="By member">
          {ai.by_member.map((l) => (
            <PanelRow key={l.label} label={l.label} value={`${l.calls.toLocaleString()} · ${fmtUsd(l.cost_usd)}`} />
          ))}
        </PanelSection>
      )}
      {ai.unpriced_calls > 0 && (
        <PanelNote tone="text-amber-600">
          {plural(ai.unpriced_calls, "call")} ran on a model with no price set, so the cost above is
          too low. Add it to AI_MODEL_PRICES on the server.
        </PanelNote>
      )}
    </>
  );

  return (
    <HoverCell panel={panel}>
      <Figure
        main={plural(ai.calls, "call")}
        sub={
          <>
            {fmtUsd(ai.cost_usd)}
            {ai.unpriced_calls > 0 && <span className="text-amber-600"> +{ai.unpriced_calls} unpriced</span>}
          </>
        }
      />
    </HoverCell>
  );
}

export function FilesCell({ files }: { files: FileUsage }) {
  if (!files.uploads && !files.files) return <HoverCell panel={null}><Zero /></HoverCell>;

  const panel = (
    <>
      <PanelTitle>Stored files</PanelTitle>
      <PanelRow label="Stored now" value={`${plural(files.files, "file")} · ${fmtBytes(files.bytes)}`} />
      <PanelRow label="Google Cloud Storage" value={fmtBytes(files.gcs_bytes)} />
      {files.local_bytes > 0 && <PanelRow label="Local disk (GCS fallback)" value={fmtBytes(files.local_bytes)} />}
      {files.by_source.length > 0 && (
        <PanelSection title="By feature">
          {files.by_source.map((l) => (
            <PanelRow key={l.label} label={l.label} value={`${l.files.toLocaleString()} · ${fmtBytes(l.bytes)}`} />
          ))}
        </PanelSection>
      )}
      {files.by_member.length > 0 && (
        <PanelSection title="Uploads by member">
          {files.by_member.map((l) => (
            <PanelRow key={l.label} label={l.label} value={plural(l.files, "upload")} />
          ))}
        </PanelSection>
      )}
    </>
  );

  return (
    <HoverCell panel={panel}>
      <Figure main={plural(files.uploads, "upload")} sub={fmtBytes(files.bytes)} />
    </HoverCell>
  );
}

export function DbCell({ db }: { db: DbUsage | null }) {
  if (!db) return <UnavailableCell />;
  if (!db.bytes) return <HoverCell panel={null}><Zero /></HoverCell>;

  const panel = (
    <>
      <PanelTitle>Estimated Postgres footprint</PanelTitle>
      {db.by_area.map((l) => (
        <PanelRow key={l.label} label={l.label} value={fmtBytes(l.bytes)} />
      ))}
      <PanelNote>
        Each table&apos;s size on disk, indexes included, split by this workspace&apos;s share of its
        rows. Measured {fmtAgo(db.measured_at)}.
      </PanelNote>
    </>
  );

  return (
    <HoverCell panel={panel}>
      <Figure main={fmtBytes(db.bytes)} sub={`${fmtShare(db.share)} of DB`} />
    </HoverCell>
  );
}

// ── platform tiles ───────────────────────────────────────────────────────────

function UsageTile({ icon: Icon, label, value, sub, subTitle, tone }: {
  icon: LucideIcon; label: string; value: string; sub?: ReactNode; subTitle?: string; tone: string;
}) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex items-center gap-3 min-w-0">
      <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${tone}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-bold text-gray-900 leading-none tabular-nums">{value}</p>
        <p className="text-[11px] text-gray-400 mt-1">{label}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-0.5 truncate" title={subTitle}>{sub}</p>}
      </div>
    </div>
  );
}

export function UsageTiles({ usage }: { usage: PlatformUsage }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <UsageTile
        icon={Sparkles}
        label="OpenAI spend"
        value={fmtUsd(usage.ai_cost_usd)}
        sub={
          <>
            {fmtUsd(usage.ai_month_cost_usd)} this month · {plural(usage.ai_calls, "call")}
            {usage.ai_unpriced_calls > 0 && <span className="text-amber-600"> · {usage.ai_unpriced_calls} unpriced</span>}
          </>
        }
        tone="bg-violet-50 text-violet-600"
      />
      <UsageTile
        icon={CloudUpload}
        label="Files uploaded"
        value={usage.uploads.toLocaleString()}
        sub={`${plural(usage.files, "file")} stored now`}
        tone="bg-sky-50 text-sky-600"
      />
      <UsageTile
        icon={HardDrive}
        label="Cloud storage"
        value={fmtBytes(usage.gcs_bytes)}
        sub={
          usage.unattributed_bytes > 0 ? (
            <span className="text-amber-600">{fmtBytes(usage.unattributed_bytes)} owned by no workspace</span>
          ) : usage.local_bytes > 0 ? (
            `+ ${fmtBytes(usage.local_bytes)} on local disk`
          ) : undefined
        }
        subTitle={
          usage.unattributed_bytes > 0
            ? "Mostly files of deleted workspaces: deleting a workspace removes its records but leaves its files in the bucket."
            : undefined
        }
        tone="bg-teal-50 text-teal-600"
      />
      <UsageTile
        icon={Database}
        label="Database size"
        value={fmtBytes(usage.database_bytes)}
        sub={`${fmtBytes(usage.database_attributed_bytes)} across workspaces · ${fmtAgo(usage.database_measured_at)}`}
        tone="bg-indigo-50 text-indigo-600"
      />
    </div>
  );
}
