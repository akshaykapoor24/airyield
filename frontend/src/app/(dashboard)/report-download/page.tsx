"use client";

// Workspace → Report download — one Excel workbook of the user's Vendors →
// Statements uploads. Three steps on one page: pick a period and source types
// (ReportFilters), review the matching uploads (UploadPicker), queue the build
// (GenerateBar). The build is a background job, so the history below
// (ReportHistory) polls until every report has settled.
//
// The page owns all state because the steps feed each other: "Run again" on a past
// report writes its filters, options and ticks back into steps 1–3, and Generate
// and Retry must re-arm the history's polling.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";
import ReportFilters, { type SourcesStatus } from "@/components/reportDownload/ReportFilters";
import UploadPicker from "@/components/reportDownload/UploadPicker";
import GenerateBar from "@/components/reportDownload/GenerateBar";
import ReportHistory from "@/components/reportDownload/ReportHistory";
import {
  DEFAULT_REPORT_OPTIONS, MAX_INCLUDED_UPLOADS,
  apiErrorMessage, buildTypeTree, createExport, defaultFilters, deleteExport, estimateRows,
  filterProblem, findUploads, getExport, getSources, initialSelection, keysWithUploads, listExports,
  prefillFromExport, retryExport, sameFilters, statusMeta, treeKeys, uploadKey,
  type ExportListItem, type ExportPage, type FindUploadsResult, type ReportOptions,
  type SelectionPreset, type SourceCategory, type UploadFilters, type UploadRef,
} from "@/lib/reportDownload";

const POLL_MS = 3000;
// A stalled report only changes when someone clicks Retry (or its worker recovers), so it is
// re-checked slowly instead of holding a 3-second loop open indefinitely.
const STALLED_POLL_MS = 30000;
const HISTORY_PAGE_SIZE = 20;

/** The uploads found, with the filters they were found for. Generate submits these
 *  filters, never the live form, so the report matches the list the user reviewed. */
interface Listing {
  filters: UploadFilters;
  result: FindUploadsResult;
}

export default function ReportDownloadPage() {
  // ── step 1: filters ──
  const [filters, setFilters] = useState<UploadFilters>(defaultFilters);
  // Once the user (or Run again) has chosen types, a late /sources response must
  // not overwrite them with the "types you have uploads for" default.
  const typesChosen = useRef(false);
  const filtersRef = useRef<HTMLDivElement>(null);

  const [sources, setSources] = useState<SourceCategory[] | null>(null);
  const [sourcesStatus, setSourcesStatus] = useState<SourcesStatus>("loading");
  const [sourcesNonce, setSourcesNonce] = useState(0);

  // ── step 2: uploads ──
  const [listing, setListing] = useState<Listing | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState<string | null>(null);

  // ── step 3: generate ──
  const [options, setOptions] = useState<ReportOptions>(DEFAULT_REPORT_OPTIONS);
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // ── history ──
  const [history, setHistory] = useState<ExportPage | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyOffset, setHistoryOffset] = useState(0);
  // Bumped to restart the polling loop: after Generate, Retry, Delete or Refresh.
  const [pollNonce, setPollNonce] = useState(0);
  const rearmPolling = useCallback(() => setPollNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    getSources()
      .then((data) => {
        if (cancelled) return;
        setSources(data);
        setSourcesStatus("loaded");
        if (!typesChosen.current) setFilters((f) => ({ ...f, types: keysWithUploads(data) }));
      })
      .catch(() => {
        if (!cancelled) setSourcesStatus("error");
      });
    return () => { cancelled = true; };
  }, [sourcesNonce]);

  // Polling: fetch the history page; while any report on it is waiting, generating
  // or stalled, fetch again in POLL_MS. A hidden tab skips its turn and resumes on
  // visibilitychange. Any error stops the loop (Refresh re-arms it); 401 and 402
  // are already handled by the api.ts interceptors.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let resumeWhenVisible = false;

    const tick = async (force: boolean) => {
      if (!force && document.hidden) {
        resumeWhenVisible = true;
        return;
      }
      try {
        const page = await listExports(HISTORY_PAGE_SIZE, historyOffset);
        if (cancelled) return;
        if (page.items.length === 0 && historyOffset > 0) {
          // The last report on a later page was deleted: step back a page.
          setHistoryOffset(Math.max(0, historyOffset - HISTORY_PAGE_SIZE));
          return;
        }
        setHistory(page);
        setHistoryError(null);
        const busy = page.items.some((i) => i.display_status === "waiting" || i.display_status === "generating");
        if (busy) {
          timer = setTimeout(() => void tick(false), POLL_MS);
        } else if (page.items.some((i) => statusMeta(i.display_status).active)) {
          timer = setTimeout(() => void tick(false), STALLED_POLL_MS);
        }
      } catch (e) {
        if (!cancelled) setHistoryError(apiErrorMessage(e, "Generated reports could not be loaded."));
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    };

    const onVisibilityChange = () => {
      if (!document.hidden && resumeWhenVisible) {
        resumeWhenVisible = false;
        void tick(true);
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    void tick(true);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [historyOffset, pollNonce]);

  const tree = useMemo(() => buildTypeTree(sources), [sources]);

  const onFiltersChange = (next: UploadFilters) => {
    if (next.types !== filters.types) typesChosen.current = true;
    setFilters(next);
  };

  const retrySources = () => {
    setSourcesStatus("loading");
    setSourcesNonce((n) => n + 1);
  };

  // Run again can start a search while another is in flight; only the latest may
  // land, or an older response could replace the list the user is looking at.
  const findSeq = useRef(0);
  const find = useCallback(async (f: UploadFilters, preset?: SelectionPreset) => {
    const seq = ++findSeq.current;
    setFinding(true);
    setFindError(null);
    setGenerateError(null);
    try {
      const result = await findUploads(f);
      if (seq !== findSeq.current) return;
      setListing({ filters: f, result });
      setSelected(initialSelection(result.uploads, preset));
    } catch (e) {
      if (seq === findSeq.current) setFindError(apiErrorMessage(e, "Uploads could not be found. Please try again."));
    } finally {
      if (seq === findSeq.current) setFinding(false);
    }
  }, []);

  // ── derived: what Generate would submit ──
  const chosen = useMemo(
    () => (listing?.result.uploads ?? []).filter((u) => u.selectable && selected.has(uploadKey(u.source_type, u.upload_id))),
    [listing, selected],
  );
  const estimatedRows = useMemo(() => estimateRows(chosen, options.undated_rows), [chosen, options.undated_rows]);
  const showUndatedOption = useMemo(() => chosen.some((u) => (u.rows_undated ?? 0) > 0), [chosen]);

  const stale = listing != null && !sameFilters(listing.filters, filters);
  const blockedReason = stale
    ? "The filters changed. Click Find uploads to refresh the list first."
    : chosen.length === 0
      ? "Tick at least one upload."
      : chosen.length > MAX_INCLUDED_UPLOADS
        ? `A report can include at most ${MAX_INCLUDED_UPLOADS} files. Untick ${chosen.length - MAX_INCLUDED_UPLOADS}.`
        : null;

  const generate = async () => {
    if (!listing || blockedReason) return;
    const f = listing.filters;
    const included: UploadRef[] = [];
    const unticked: UploadRef[] = [];
    for (const u of listing.result.uploads) {
      // Uploads the server refused to make selectable are its exclusion, not the
      // user's, so they are not reported back as unticked.
      if (!u.selectable) continue;
      const ref = { source_type: u.source_type, upload_id: u.upload_id };
      (selected.has(uploadKey(u.source_type, u.upload_id)) ? included : unticked).push(ref);
    }

    setSubmitting(true);
    setGenerateError(null);
    try {
      const created = await createExport({
        title: title.trim() || undefined,
        date_from: f.date_from,
        date_to: f.date_to,
        basis: f.basis,
        bsp_scope: f.bsp_scope,
        source_types: f.types,
        included_uploads: included,
        unticked_uploads: unticked,
        options,
      });
      setTitle("");
      if (historyOffset === 0) {
        // Show it at once; the poll that rearmPolling starts replaces the list.
        setHistory((prev) => ({
          items: [created, ...(prev?.items ?? []).filter((i) => i.id !== created.id)].slice(0, HISTORY_PAGE_SIZE),
          total: (prev?.total ?? 0) + 1,
        }));
      } else {
        setHistoryOffset(0);
      }
      rearmPolling();
    } catch (e) {
      setGenerateError(apiErrorMessage(e, "The report could not be queued. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  const retry = useCallback(async (item: ExportListItem) => {
    const updated = await retryExport(item.id);
    setHistory((prev) => prev && { ...prev, items: prev.items.map((i) => (i.id === updated.id ? updated : i)) });
    rearmPolling();
  }, [rearmPolling]);

  const remove = useCallback(async (item: ExportListItem) => {
    await deleteExport(item.id);
    setHistory((prev) => prev && { items: prev.items.filter((i) => i.id !== item.id), total: Math.max(0, prev.total - 1) });
    rearmPolling();
  }, [rearmPolling]);

  const runAgain = useCallback(async (item: ExportListItem) => {
    const full = await getExport(item.id);
    const prefill = prefillFromExport(full, treeKeys(tree));
    typesChosen.current = true;
    setFilters(prefill.filters);
    setOptions(prefill.options);
    setTitle(prefill.title);
    filtersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    // A report whose source types this build no longer lists leaves nothing to find;
    // the form then shows why, instead of the server answering 422.
    if (!filterProblem(prefill.filters)) await find(prefill.filters, prefill.preset);
  }, [find, tree]);

  const refreshHistory = () => {
    setHistoryLoading(true);
    rearmPolling();
  };

  return (
    <div className="space-y-5">
      <div ref={filtersRef} className="scroll-mt-6">
        <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Report download</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          One Excel workbook of your Vendors → Statements uploads: every source on one Combined sheet, with each source&apos;s own detail alongside.
        </p>
      </div>

      <ReportFilters
        value={filters}
        onChange={onFiltersChange}
        sources={sources}
        sourcesStatus={sourcesStatus}
        onRetrySources={retrySources}
        onFind={() => void find(filters)}
        finding={finding}
      />

      {findError && (
        <div className="flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700" role="alert">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> {findError}
        </div>
      )}

      {listing && (
        <>
          <div className={stale ? "opacity-60 transition-opacity" : undefined}>
            <UploadPicker uploads={listing.result.uploads} selected={selected} onChange={setSelected} />
          </div>
          {listing.result.uploads.length > 0 && (
            <GenerateBar
              fileCount={chosen.length}
              estimatedRows={estimatedRows}
              options={options}
              onOptionsChange={setOptions}
              showUndatedOption={showUndatedOption}
              title={title}
              onTitleChange={setTitle}
              onGenerate={() => void generate()}
              submitting={submitting}
              blockedReason={blockedReason}
              error={generateError}
            />
          )}
        </>
      )}

      <ReportHistory
        page={history}
        loading={historyLoading}
        error={historyError}
        offset={historyOffset}
        pageSize={HISTORY_PAGE_SIZE}
        onPageChange={setHistoryOffset}
        onRefresh={refreshHistory}
        onRetry={retry}
        onRunAgain={runAgain}
        onDelete={remove}
      />
    </div>
  );
}
