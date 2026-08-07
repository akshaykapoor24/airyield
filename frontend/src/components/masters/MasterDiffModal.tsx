"use client";

import { useState } from "react";
import { RefreshCw, X } from "lucide-react";

/** How one field is compared and drawn in the diff. */
export type DiffFieldSpec = {
  /** Key read from each of the three record objects. */
  key: string;
  label: string;
  /** Draw a value. Defaults to its string form, or an em dash when blank. */
  render?: (value: unknown) => React.ReactNode;
  /**
   * Whether two values count as the same. Defaults to a blank-insensitive
   * string compare; override for values whose ORDER carries no meaning —
   * airport categorization groups, supplier branches — so that reordering
   * is not reported as a change.
   */
  equals?: (a: unknown, b: unknown) => boolean;
};

type Record_ = Record<string, unknown>;

export type MasterDiffModalProps = {
  title: string;
  subtitle?: string;
  fields: DiffFieldSpec[];
  /** Live master record. Omit to hide the "Current" column (new requests). */
  master?: Record_ | null;
  /** The values as the submitter sent them. Always shown. */
  submitted: Record_;
  /** Values after the admin's edit. Omit to hide the column (nothing edited). */
  edited?: Record_ | null;
  masterLabel?: string;
  submittedLabel?: string;
  editedLabel?: string;
  editedBy?: { full_name: string; email: string } | null;
  editedAt?: string | null;
  /** Shows a spinner instead of the table while the master record loads. */
  loading?: boolean;
  onClose: () => void;
};

const isBlank = (v: unknown) =>
  v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);

const defaultEquals = (a: unknown, b: unknown) =>
  (isBlank(a) && isBlank(b)) || String(a ?? "") === String(b ?? "");

const defaultRender = (v: unknown) =>
  isBlank(v) ? <span className="text-gray-300">—</span> : String(v);

/**
 * One diff view for every master request.
 *
 * Columns appear only when they carry information, which is what lets a single
 * component serve all the cases:
 *   Current master  — only for an "update" request, once the record is loaded
 *   Proposed        — always
 *   Admin changed to — only when a platform admin actually changed something
 *
 * So an unedited update request renders the same two columns it always has, and
 * an edited one simply gains a third.
 */
export default function MasterDiffModal({
  title,
  subtitle,
  fields,
  master,
  submitted,
  edited,
  masterLabel = "Current",
  submittedLabel = "Proposed",
  editedLabel = "Admin changed to",
  editedBy,
  editedAt,
  loading = false,
  onClose,
}: MasterDiffModalProps) {
  const [showAll, setShowAll] = useState(false);

  const showMaster = !!master;
  const showEdited = !!edited;

  const rows = fields.map((f) => {
    const eq = f.equals ?? defaultEquals;
    const was = submitted[f.key];
    const now = edited ? edited[f.key] : undefined;
    return {
      ...f,
      cur: master ? master[f.key] : undefined,
      was,
      now,
      // Differs from what is in the master today.
      proposedChanged: showMaster ? !eq(master![f.key], was) : false,
      // The admin altered what the submitter sent.
      adminChanged: showEdited ? !eq(was, now) : false,
    };
  });

  const interesting = rows.filter((r) => r.proposedChanged || r.adminChanged);
  const visible = showAll ? rows : interesting;
  const colCount = 1 + (showMaster ? 1 : 0) + 1 + (showEdited ? 1 : 0);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{title}</h2>
            {subtitle && <p className="text-[10px] text-gray-400 mt-0.5">{subtitle}</p>}
            {showEdited && editedBy && (
              <p className="text-[10px] text-amber-600 mt-1 font-medium">
                Edited by {editedBy.full_name}
                {editedAt && ` on ${new Date(editedAt).toLocaleString()}`}
              </p>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg shrink-0">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 overflow-y-auto">
          {loading ? (
            <div className="py-8 text-center text-xs text-gray-400">
              <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
              Loading current record...
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide w-36">
                    Field
                  </th>
                  {showMaster && (
                    <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                      {masterLabel}
                    </th>
                  )}
                  <th className="text-left py-2 pr-3 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                    {submittedLabel}
                  </th>
                  {showEdited && (
                    <th className="text-left py-2 text-[10px] font-semibold text-amber-500 uppercase tracking-wide">
                      {editedLabel}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {visible.length === 0 ? (
                  <tr>
                    <td colSpan={colCount} className="py-6 text-center text-gray-400">
                      No differences to show.
                    </td>
                  </tr>
                ) : (
                  visible.map((r) => {
                    const draw = r.render ?? defaultRender;
                    const highlight = r.proposedChanged || r.adminChanged;
                    return (
                      <tr
                        key={r.key}
                        className={`border-b border-gray-50 ${highlight ? "bg-amber-50/60" : ""}`}
                      >
                        <td className="py-2 pr-3 font-semibold text-gray-600 text-[11px] align-top">
                          {r.label}
                        </td>
                        {showMaster && (
                          <td className="py-2 pr-3 text-gray-500 align-top">{draw(r.cur)}</td>
                        )}
                        <td
                          className={`py-2 pr-3 align-top ${
                            r.proposedChanged ? "text-amber-700 font-medium" : "text-gray-700"
                          }`}
                        >
                          {draw(r.was)}
                          {r.proposedChanged && (
                            <span className="ml-1.5 text-[9px] bg-amber-200 text-amber-800 px-1 py-0.5 rounded font-bold">
                              CHANGED
                            </span>
                          )}
                        </td>
                        {showEdited && (
                          <td
                            className={`py-2 align-top ${
                              r.adminChanged ? "text-amber-700 font-medium" : "text-gray-400"
                            }`}
                          >
                            {r.adminChanged ? (
                              <>
                                {draw(r.now)}
                                <span className="ml-1.5 text-[9px] bg-amber-500 text-white px-1 py-0.5 rounded font-bold">
                                  EDITED
                                </span>
                              </>
                            ) : (
                              <span className="text-gray-300">— unchanged</span>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 pb-4 pt-2 flex items-center gap-3 border-t border-gray-50 shrink-0">
          {!loading && rows.length > interesting.length && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="text-[11px] font-semibold text-blue-600 hover:underline"
            >
              {showAll ? "Show only changes" : `Show all ${rows.length} fields`}
            </button>
          )}
          <button
            onClick={onClose}
            className="ml-auto border border-gray-200 rounded-lg px-5 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
