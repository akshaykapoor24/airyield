"use client";

// "How GST is calculated" — the worked GST calculation, in a popup.
//
// It used to sit open under the GST Configuration field on My Profile, where a tax
// calculator with three inputs and two result grids pushed the Save button off screen for
// something a user reads once. Now the field shows the choice, and this explains it on
// request.
//
// COMPARE, THEN CHOOSE. It opens on the scheme currently picked in the form (saved or not)
// and can flip to the other one, so the two can be compared on the same sample amounts. If
// the one on screen is not the one picked, "Use this scheme" picks it — in the form only;
// like any other field it is recorded by Save Changes.
//
// Every figure still comes from GstSchemePreview → POST /gst-configurations/{id}/preview,
// the same arithmetic that bills a real ticket; nothing is recomputed here.

import { useEffect, useState } from "react";
import { Calculator, Check, X } from "lucide-react";
import GstSchemePreview from "@/components/profile/GstSchemePreview";
import { SCHEMES, schemeByKey } from "@/lib/gstSchemes";

/** One line per scheme, for the switcher and the header. Describes WHAT is taxed, never
 *  a rate, so it cannot go stale when the platform revises one. */
export const SCHEME_SUMMARY: Record<string, string> = {
  abatement: "GST on a deemed slice of the basic fare — 5% domestic, 10% international, by ticket sector.",
  normal: "GST on actual consideration — an agency customer's service charge, or a reseller's whole sale. Set per customer in User master.",
};

export default function GstSchemeDialog({ selected, onUse, onClose }: {
  /** The scheme picked in the form right now ("" = none yet). */
  selected: string;
  /** Pick a scheme in the form. Omit to make the dialog read-only. */
  onUse?: (scheme: string) => void;
  onClose: () => void;
}) {
  const [viewing, setViewing] = useState<string>(
    schemeByKey(selected) ? selected : SCHEMES[0].key,
  );
  const spec = schemeByKey(viewing);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-slate-900/50 backdrop-blur-[1px] flex items-center justify-center z-50 p-4"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
      role="presentation"
    >
      <div role="dialog" aria-modal="true" aria-labelledby="gst-dialog-title"
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-gray-100">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <span className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center shrink-0">
                <Calculator className="w-4.5 h-4.5" />
              </span>
              <div>
                <h2 id="gst-dialog-title" className="text-sm font-bold text-gray-900">How GST is calculated</h2>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  A worked example on the platform&apos;s current rates. Rates are maintained by the platform team.
                </p>
              </div>
            </div>
            <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg shrink-0" aria-label="Close">
              <X className="w-4 h-4 text-gray-500" />
            </button>
          </div>

          {/* Scheme switcher */}
          <div className="mt-4 grid grid-cols-2 gap-1 p-1 bg-gray-100 rounded-xl">
            {SCHEMES.map(s => {
              const active = s.key === viewing;
              return (
                <button key={s.key} onClick={() => setViewing(s.key)}
                  className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                    active ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
                  }`}>
                  {s.label}
                  {s.key === selected && (
                    <span className="text-[9px] font-bold uppercase tracking-wide text-emerald-600 bg-emerald-50 border border-emerald-200 rounded px-1 py-px">
                      Selected
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {spec && <p className="text-[11px] text-gray-600 mt-2.5 leading-relaxed">{SCHEME_SUMMARY[spec.key]}</p>}
        </div>

        {/* Body — the calculation itself */}
        <div className="px-6 py-4 overflow-y-auto bg-gray-50/60 flex-1">
          <GstSchemePreview scheme={viewing} bare />
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-gray-100 flex items-center justify-between gap-3 bg-white">
          <p className="text-[10px] text-gray-400">
            {onUse && viewing !== selected
              ? "Picking a scheme here fills the form — Save Changes records it."
              : "Only one column is billed on a sale — whichever the place of supply decides."}
          </p>
          <div className="flex items-center gap-2 shrink-0">
            {onUse && viewing !== selected && spec && (
              <button onClick={() => { onUse(viewing); onClose(); }}
                className="flex items-center gap-1.5 text-white rounded-lg px-3.5 py-2 text-xs font-semibold"
                style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                <Check className="w-3.5 h-3.5" /> Use {spec.label}
              </button>
            )}
            <button onClick={onClose}
              className="border border-gray-200 rounded-lg px-3.5 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
