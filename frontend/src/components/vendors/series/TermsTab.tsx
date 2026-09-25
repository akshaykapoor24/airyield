"use client";

/**
 * What changing or cancelling this contract costs.
 *
 * The top of the tab answers the question an agency asks when a departure is selling
 * badly — "what would it cost to hand the whole block back today, and until when does
 * that price hold?" — from the server's `exposure`, which prices the contract's own
 * cancellation bands against its own fare. Below it, every term, in the contract's words.
 */

import { useState } from "react";
import toast from "react-hot-toast";
import { CalendarClock, Loader2, PencilLine, ShieldAlert } from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import {
  API_BASE, CABIN_LABEL, TERM_PHASE_LABEL, TERM_RULE_LABEL, TERM_RULE_TYPES, TERM_SCOPE_LABEL,
  inr, type ContractDetail, type Term,
} from "@/lib/series";
import { TermsEditor, draftToTerm, termToDraft, type TermDraft } from "./termsEditors";

export default function TermsTab({
  contract, onChanged,
}: {
  contract: ContractDetail;
  onChanged: (c: ContractDetail) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<TermDraft[]>([]);
  const [saving, setSaving] = useState(false);

  const startEdit = () => { setDraft(contract.terms.map(termToDraft)); setEditing(true); };

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put<ContractDetail>(`${API_BASE}/${contract.id}/terms`, draft.map(draftToTerm));
      onChanged(data);
      setEditing(false);
      toast.success("Terms saved — cancellation-charge reminders updated");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const grouped = TERM_RULE_TYPES
    .map((rule) => [rule, contract.terms.filter((t) => t.rule_type === rule)] as const)
    .filter(([, rows]) => rows.length);
  const unpriced = contract.fare_summary.per_pax === 0;
  const upcoming = contract.allocations.filter((a) => !a.departure_date || a.departure_date >= new Date().toISOString().slice(0, 10));

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <ShieldAlert className="w-3.5 h-3.5 text-[#1e3a5f]" />
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Cost to cancel today</p>
        </div>
        {contract.exposure.length === 0 ? (
          <p className="text-xs text-gray-400 px-4 py-6">
            {contract.terms.length === 0
              ? "No cancellation terms on this contract yet — add them below to see what backing out costs."
              : upcoming.length === 0
                ? "Every departure on this contract has already flown."
                : "None of the terms prices a whole-group cancellation."}
          </p>
        ) : (
          <div className="divide-y divide-gray-50">
            {contract.exposure.map((e) => (
              <div key={e.allocation_id} className="px-4 py-3 grid md:grid-cols-[160px_1fr_auto] gap-3 items-center">
                <div>
                  <p className="text-[11px] font-semibold text-gray-800">{e.departure_date ?? "Undated"}</p>
                  <p className="text-[10px] text-gray-400">
                    {e.days_before != null ? `${e.days_before} days out` : ""} · {e.seats} seats
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="text-[11px] text-gray-700">{e.description ?? "No band covers today"}</p>
                  {e.holds_until && (
                    <p className="text-[10px] text-amber-700 mt-0.5 flex items-center gap-1">
                      <CalendarClock className="w-3 h-3" />
                      Holds until {e.holds_until}
                      {e.next_description && <> — then {e.next_description.toLowerCase()}</>}
                      {e.next_per_pax != null && <> ({inr(e.next_per_pax)}/pax)</>}
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-base font-bold tabular-nums text-gray-900">
                    {e.amount != null ? inr(e.amount) : "—"}
                  </p>
                  <p className="text-[10px] text-gray-400">
                    {e.per_pax != null ? `${inr(e.per_pax)} per seat` : "not priceable"}{e.plus_gst ? " + GST" : ""}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
        {unpriced && contract.terms.length > 0 && (
          <p className="px-4 py-2 text-[10px] text-amber-700 bg-amber-50/50 border-t border-amber-100">
            This contract has no fare yet, so percentage penalties work out to zero. Add the fare on the Money tab.
          </p>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">
            Terms ({contract.terms.length})
          </p>
          {!editing ? (
            <button onClick={startEdit}
              className="ml-auto flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg">
              <PencilLine className="w-3 h-3" /> Edit terms
            </button>
          ) : (
            <div className="ml-auto flex gap-2">
              <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-[11px] font-semibold text-gray-500 hover:bg-gray-50 rounded-lg">
                Cancel
              </button>
              <button onClick={save} disabled={saving}
                className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-[11px] font-semibold px-3 py-1.5 rounded-lg disabled:opacity-60">
                {saving && <Loader2 className="w-3 h-3 animate-spin" />} Save terms
              </button>
            </div>
          )}
        </div>

        {editing ? (
          <div className="p-4"><TermsEditor value={draft} onChange={setDraft} /></div>
        ) : contract.terms.length === 0 ? (
          <p className="text-xs text-gray-400 px-4 py-8 text-center">
            No terms recorded. Cancellation bands, seat-release allowances and name-change charges
            belong here — they are what the cost above and the &ldquo;charge rises&rdquo; reminders are built from.
          </p>
        ) : (
          <div className="divide-y divide-gray-100">
            {grouped.map(([rule, rows]) => (
              <div key={rule} className="px-4 py-3">
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-1.5">
                  {TERM_RULE_LABEL[rule] ?? rule}
                </p>
                <ul className="space-y-1.5">
                  {rows.map((t) => <TermLine key={t.id} term={t} cabin={contract.cabin} />)}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TermLine({ term, cabin }: { term: Term; cabin?: string | null }) {
  const otherCabin = term.cabin && cabin && term.cabin !== cabin;
  const tags = [
    term.scope ? TERM_SCOPE_LABEL[term.scope] : null,
    term.phase && term.phase !== "ANY" ? TERM_PHASE_LABEL[term.phase] : null,
    term.cabin ? CABIN_LABEL[term.cabin] ?? term.cabin : null,
  ].filter(Boolean);
  return (
    <li className={`text-[11px] ${otherCabin ? "opacity-50" : ""}`}>
      <span className="text-gray-800">{term.summary ?? term.description}</span>
      {tags.length > 0 && <span className="text-gray-400"> · {tags.join(" · ")}</span>}
      {term.source_text && (
        <span className="block text-[10px] text-gray-400 italic" title={term.source_text}>
          {term.source_page ? `p.${term.source_page} ` : ""}“{term.source_text.length > 160 ? `${term.source_text.slice(0, 160)}…` : term.source_text}”
        </span>
      )}
    </li>
  );
}
