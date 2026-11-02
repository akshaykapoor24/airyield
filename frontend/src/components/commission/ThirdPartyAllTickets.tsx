"use client";

// Commission income → Third Party GDS → All tickets: every ticket line of every statement in
// the tab's filters, in one table — the same cards and pinned commission check as one
// statement's detail (ThirdPartyStatementLines), plus each line's agency and statement.
//
// Selection and running live here, as the detail page keeps them for its own lines. A
// selection can span statements, so it goes to `…/run-lines`, which runs each statement's
// share inline as that statement's own selection. While lines are ticked, the toolbar's
// right end swaps the tab's Run all for Run selected — as one statement's header does.

import { useState } from "react";
import { Play, X } from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import type { CommissionSource } from "@/lib/commissionSources";
import ThirdPartyStatementLines, { type LinesToolbar } from "./ThirdPartyStatementLines";
import { RunLinesResponse, inr } from "./types";

const MAX_SELECTION = 500;   // matches MAX_INLINE_ROWS on the API

const errText = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

export default function ThirdPartyAllTickets({
  source, params, toolbar, refreshKey, onOpenStatement, onRan,
}: {
  source: CommissionSource;
  /** The tab's scope: `batches` (Agency / Statement) and the booking period. */
  params: Record<string, string | undefined>;
  /** The tab's sub-tabs, filters and buttons — drawn in one row with the table's filters. */
  toolbar: LinesToolbar;
  /** Changes when a statement in scope finishes a run, or on Refresh. */
  refreshKey: string;
  onOpenStatement: (batchId: string) => void;
  /** After a selection ran — the parent reloads its statements' totals. */
  onRan: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busyRows, setBusyRows] = useState<Set<number>>(new Set());

  // A new scope drops the selection, so Run selected never acts on lines that left the view.
  const scope = JSON.stringify(params);
  const [seenScope, setSeenScope] = useState(scope);
  if (scope !== seenScope) { setSeenScope(scope); setSelected(new Set()); }

  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleMany = (ids: number[], on: boolean) => setSelected((prev) => {
    const next = new Set(prev);
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
    return next;
  });

  const runLines = async (ids: number[]) => {
    if (!ids.length) return;
    setBusyRows((prev) => new Set([...prev, ...ids]));
    try {
      const { data } = await api.post<RunLinesResponse>(`${source.apiBase}/run-lines`, { line_ids: ids });
      const bits = [
        data.calculated && `${data.calculated} calculated`,
        data.reversed && `${data.reversed} reversed`,
        data.excluded && `${data.excluded} excluded`,
        data.skipped && `${data.skipped} skipped`,
        (data.unmatched + data.needs_data) && `${data.unmatched + data.needs_data} unmatched`,
      ].filter(Boolean).join(", ");
      if (data.lines) {
        toast.success(
          `${data.lines} ticket${data.lines === 1 ? "" : "s"}` +
          (data.statements > 1 ? ` across ${data.statements} statements` : "") +
          ` — ${bits || "no change"}` +
          (data.expected_total ? ` · ₹${inr(data.expected_total)} expected` : ""),
        );
      }
      for (const s of data.not_run) {
        toast.error(`${s.statement_name ?? "A statement"}: ${s.reason}`);
      }
      onRan();   // its reload moves refreshKey once the statements' new runs are seen
    } catch (e: unknown) {
      toast.error(errText(e, "Calculation failed."));
    } finally {
      setBusyRows((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  };

  const tooMany = selected.size > MAX_SELECTION;
  const end = selected.size > 0 ? (
    <>
      {tooMany && (
        <span className="text-[11px] text-orange-600 whitespace-nowrap">max {MAX_SELECTION} at a time</span>
      )}
      <button onClick={() => setSelected(new Set())} title="Clear the selection"
        className="flex items-center gap-1 px-2 py-1.5 text-xs text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 whitespace-nowrap">
        <X className="w-3 h-3" /> {selected.size} selected
      </button>
      <button onClick={() => runLines([...selected])} disabled={busyRows.size > 0 || tooMany}
        title={tooMany ? `Run at most ${MAX_SELECTION} lines at a time, or clear the selection and use Run all.` : undefined}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50 whitespace-nowrap">
        <Play className="w-3.5 h-3.5" />
        {busyRows.size > 0 ? "Calculating…" : `Run selected (${selected.size})`}
      </button>
    </>
  ) : toolbar.end;

  return (
    <div>
      <ThirdPartyStatementLines
        source={source}
        url={`${source.apiBase}/lines`}
        params={params}
        toolbar={{ ...toolbar, end }}
        showStatement
        onOpenStatement={onOpenStatement}
        refreshKey={refreshKey}
        selected={selected}
        onToggle={toggle}
        onToggleMany={toggleMany}
        busyRows={busyRows}
        onRun={runLines}
      />
    </div>
  );
}
