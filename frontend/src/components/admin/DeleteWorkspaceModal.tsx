"use client";

// The destructive half of the Subscriptions console.
//
// The operator ticks what to delete. Some ticks force others — deals.agency_id
// is ON DELETE RESTRICT, so deleting Agencies without Deals is not something
// the database will honour, and billings.agency_id is ON DELETE CASCADE, so it
// would take the billings whether or not they were ticked. The API tells us
// which via `requires`; we tick those ourselves and mark them, so the count on
// screen is always the count that will go.
//
// Nothing happens until the workspace's own name is typed back.

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Link2, Loader2, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { INPUT, LABEL, ModalShell, apiError } from "@/components/userMaster/shared";

type Group = {
  key: string;
  label: string;
  blurb: string;
  category: "records" | "setup";
  rows: number;
  requires: string[];
};

type DeletionPreview = {
  tenant_id: number;
  tenant_name: string | null;
  tenant_type: "corporate" | "individual";
  owner_email: string | null;
  user_emails: string[];
  confirm_phrase: string;
  groups: Group[];
};

type DeletionResult = {
  tenant_id: number;
  tenant_name: string | null;
  requested: string[];
  deleted_groups: string[];
  deleted: { key: string; label: string; rows: number }[];
  total: number;
  workspace_removed: boolean;
};

export default function DeleteWorkspaceModal({
  tenantId,
  fallbackName,
  onClose,
  onDeleted,
}: {
  tenantId: number;
  /** Shown in the title while the preview is still loading. */
  fallbackName: string;
  onClose: () => void;
  onDeleted: (result: DeletionResult) => void;
}) {
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // What the operator actually clicked, before requirements are applied.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get<DeletionPreview>(`/subscriptions/${tenantId}/deletion-preview`);
      setPreview(data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const groups = useMemo(() => preview?.groups ?? [], [preview]);
  const byKey = useMemo(() => new Map(groups.map((g) => [g.key, g])), [groups]);

  /** Close a selection over `requires`, the same way the API will. */
  const expand = useCallback((keys: Set<string>) => {
    const out = new Set(keys);
    for (;;) {
      const before = out.size;
      for (const key of Array.from(out)) {
        for (const dep of byKey.get(key)?.requires ?? []) out.add(dep);
      }
      if (out.size === before) return out;
    }
  }, [byKey]);

  const effective = useMemo(() => expand(picked), [picked, expand]);
  const total = useMemo(
    () => groups.filter((g) => effective.has(g.key)).reduce((sum, g) => sum + g.rows, 0),
    [groups, effective],
  );

  const toggle = (key: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        // Unticking something that another pick still requires would show a box
        // clearing and then re-filling, so drop the picks that depend on it too.
        for (const p of Array.from(next)) {
          if (expand(new Set([p])).has(key)) next.delete(p);
        }
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const selectAll = (category: Group["category"] | "all") => {
    setPicked(new Set(
      groups.filter((g) => category === "all" || g.category === category).map((g) => g.key),
    ));
  };

  const phrase = preview?.confirm_phrase ?? "";
  // Compared trimmed, the same way the API compares it, so a trailing space
  // pasted along with the name does not silently block the button.
  const confirmed = phrase.length > 0 && typed.trim() === phrase;
  const removingWorkspace = effective.has("workspace");
  const canDelete = confirmed && effective.size > 0 && !deleting && !loading;

  const run = async () => {
    if (!canDelete) return;
    setDeleting(true);
    setError("");
    try {
      // Only the operator's own picks go over the wire; the API expands them
      // itself, so the two sides can never disagree about what that means.
      //
      // Built by hand rather than passed as `params`: axios serialises an array
      // as `groups[]=deals`, and the endpoint reads repeated `groups=deals`, so
      // the picks would arrive under a name nothing is listening on and the
      // request would 422 with `groups` reported missing.
      const query = new URLSearchParams();
      for (const key of picked) query.append("groups", key);
      query.append("confirm", typed.trim());

      const { data } = await api.delete<DeletionResult>(
        `/subscriptions/${tenantId}?${query.toString()}`,
      );
      onDeleted(data);
    } catch (e) {
      setError(apiError(e));
      setDeleting(false);
    }
  };

  const renderGroup = (g: Group) => {
    const chosen = effective.has(g.key);
    const forced = chosen && !picked.has(g.key);
    // Who pulled it in, for the "required by" note.
    const pulledBy = forced
      ? groups.filter((o) => picked.has(o.key) && expand(new Set([o.key])).has(g.key)).map((o) => o.label)
      : [];
    return (
      <label
        key={g.key}
        className={`flex gap-2.5 items-start px-3 py-2 cursor-pointer transition-colors ${
          chosen ? "bg-red-50/60" : "hover:bg-gray-50"
        }`}
      >
        <input
          type="checkbox"
          checked={chosen}
          onChange={() => toggle(g.key)}
          className="mt-0.5 w-3.5 h-3.5 rounded border-gray-300 text-red-600 focus:ring-red-400"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-xs font-semibold text-gray-900">
              {g.label}
              {forced && (
                <span className="ml-1.5 inline-flex items-center gap-0.5 text-[9px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 py-px align-middle">
                  <Link2 className="w-2.5 h-2.5" /> required
                </span>
              )}
            </p>
            <span className={`text-[11px] tabular-nums shrink-0 ${g.rows ? "text-gray-900 font-medium" : "text-gray-300"}`}>
              {g.key === "workspace" ? "—" : g.rows.toLocaleString()}
            </span>
          </div>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-relaxed">{g.blurb}</p>
          {forced && pulledBy.length > 0 && (
            <p className="text-[10px] text-amber-700 mt-0.5">
              The database forces this along with {pulledBy.join(", ")}.
            </p>
          )}
        </div>
      </label>
    );
  };

  const records = groups.filter((g) => g.category === "records");
  const setup = groups.filter((g) => g.category === "setup");

  return (
    <ModalShell title={`Delete — ${preview?.tenant_name || fallbackName}`} onClose={onClose} wide>
      <div className="space-y-4">
        {loading && (
          <div className="flex items-center gap-2 py-8 justify-center text-xs text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" /> Working out what this workspace holds…
          </div>
        )}

        {!loading && preview && (
          <>
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
              <AlertTriangle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-[11px] text-red-700 leading-relaxed">
                This cannot be undone. There is no archive and no restore — the rows are removed from
                the database. To switch a workspace off without losing anything, close this and set
                its plan to <span className="font-semibold">Suspended</span> instead.
              </p>
            </div>

            <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 text-[11px] text-gray-500">
              {preview.owner_email || "no owner"} · {preview.user_emails.length} user
              {preview.user_emails.length !== 1 ? "s" : ""} · {preview.tenant_type}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span className={LABEL} style={{ marginBottom: 0 }}>Tick what to delete</span>
              <div className="flex-1" />
              {[
                { label: "All records", onClick: () => selectAll("records") },
                { label: "Everything", onClick: () => selectAll("all") },
                { label: "Clear", onClick: () => setPicked(new Set()) },
              ].map((b) => (
                <button
                  key={b.label}
                  type="button"
                  onClick={b.onClick}
                  className="text-[10px] font-medium text-gray-500 hover:text-gray-900 border border-gray-200 rounded px-2 py-1 hover:bg-gray-50"
                >
                  {b.label}
                </button>
              ))}
            </div>

            <div className="border border-gray-200 rounded-lg overflow-hidden max-h-72 overflow-y-auto">
              <p className="px-3 py-1.5 bg-gray-50 border-b border-gray-100 text-[9px] uppercase tracking-wide text-gray-400 font-semibold sticky top-0">
                Records — what it produced by using the product
              </p>
              <div className="divide-y divide-gray-50">{records.map(renderGroup)}</div>
              <p className="px-3 py-1.5 bg-gray-50 border-y border-gray-100 text-[9px] uppercase tracking-wide text-gray-400 font-semibold">
                Setup — who it is and how it is configured
              </p>
              <div className="divide-y divide-gray-50">{setup.map(renderGroup)}</div>
            </div>

            {removingWorkspace && preview.user_emails.length > 0 && (
              <div>
                <p className={LABEL}>Accounts that will be removed</p>
                <div className="flex flex-wrap gap-1">
                  {preview.user_emails.map((e) => (
                    <span key={e} className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">
                      {e}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 text-[11px]">
              {effective.size === 0 ? (
                <span className="text-gray-400">Nothing selected.</span>
              ) : (
                <span className="text-gray-700">
                  <span className="font-semibold">{total.toLocaleString()}</span> record
                  {total !== 1 ? "s" : ""} across{" "}
                  <span className="font-semibold">{effective.size}</span>{" "}
                  {effective.size === 1 ? "item" : "items"}
                  {removingWorkspace && (
                    <span className="text-red-600 font-semibold"> · the workspace itself will be removed</span>
                  )}
                </span>
              )}
            </div>

            <div>
              <label className={LABEL}>
                Type <span className="font-mono text-gray-900 normal-case">{phrase}</span> to confirm
              </label>
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={phrase}
                autoComplete="off"
                className={INPUT}
              />
            </div>
          </>
        )}

        {error && <p className="text-[11px] text-red-500">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            disabled={deleting}
            className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={run}
            disabled={!canDelete}
            title={
              effective.size === 0 ? "Tick at least one thing to delete"
                : !confirmed ? "Type the workspace name to enable this"
                : undefined
            }
            className="flex-1 flex items-center justify-center gap-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-40 disabled:hover:bg-red-600"
          >
            {deleting
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Deleting…</>
              : <><Trash2 className="w-3.5 h-3.5" />
                  {removingWorkspace ? "Delete workspace" : `Delete selected (${total.toLocaleString()})`}</>}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
