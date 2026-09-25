"use client";

/**
 * The editors a contract read from a PDF needs beyond the original three: its priced
 * terms (what cancelling, releasing or renaming costs), its deadline rules (name list,
 * ticketing, no-show), and its passenger list. Plus `AiMark`, the little badge that says
 * "this value was read from the document" and jumps the PDF to where.
 *
 * Same conventions as editors.tsx: controlled, string-typed while editing so a half-typed
 * number never becomes NaN, and shared by the create wizard and the contract screen.
 */

import { Sparkles } from "lucide-react";
import {
  CABINS, CABIN_LABEL, DEADLINE_TYPE_LABEL, FARE_BASES, FARE_BASIS_LABEL,
  MANUAL_DEADLINE_TYPES, PAX_TYPES, PAX_TYPE_LABEL, TERM_CHARGE_LABEL, TERM_CHARGE_TYPES,
  TERM_PHASES, TERM_PHASE_LABEL, TERM_RULE_LABEL, TERM_RULE_TYPES, TERM_SCOPES,
  TERM_SCOPE_LABEL, type Evidence, type Term,
} from "@/lib/series";
import { LABEL, SMALL_INPUT, num } from "./editors";
import { Plus, Trash2 } from "lucide-react";

const Add = ({ onClick, label, disabled }: { onClick: () => void; label: string; disabled?: boolean }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className="flex items-center gap-1.5 text-[11px] font-semibold text-[#1e3a5f] hover:text-[#16304f] disabled:opacity-40 mt-2"
  >
    <Plus className="w-3.5 h-3.5" /> {label}
  </button>
);

const Remove = ({ onClick, title }: { onClick: () => void; title: string }) => (
  <button type="button" onClick={onClick} title={title} className="p-1.5 hover:bg-red-50 rounded-lg">
    <Trash2 className="w-3.5 h-3.5 text-red-400" />
  </button>
);

// ── Evidence ─────────────────────────────────────────────────────────────────

/**
 * "Read from page 3: “Net fare per passenger 64 600.00 INR”". Shown beside a field the AI
 * filled; clicking it turns the PDF beside the form to that page. Matches the exact path
 * first, then any evidence under it (a section-level mark).
 */
export function AiMark({
  path, evidence, onJump,
}: {
  path: string;
  evidence?: Evidence | null;
  onJump?: (page: number) => void;
}) {
  if (!evidence) return null;
  const hit = evidence[path]
    ?? Object.entries(evidence).find(([k]) => k.startsWith(`${path}.`) || k.startsWith(`${path}[`))?.[1];
  if (!hit) return null;
  const page = hit.page ?? null;
  const tip = `Read from ${page ? `page ${page}` : "the document"}${hit.quote ? `: “${hit.quote}”` : ""}`;
  return (
    <button
      type="button"
      title={tip}
      onClick={(e) => { e.preventDefault(); if (page && onJump) onJump(page); }}
      className="inline-flex items-center gap-0.5 ml-1 px-1 py-px rounded bg-violet-50 text-violet-600 text-[9px] font-bold normal-case tracking-normal align-middle hover:bg-violet-100"
    >
      <Sparkles className="w-2.5 h-2.5" /> {page ? `p.${page}` : "AI"}
    </button>
  );
}

// ── Terms ────────────────────────────────────────────────────────────────────

export type TermDraft = {
  rule_type: string;
  scope: string;
  phase: string;
  days_before_max: string;
  days_before_min: string;
  share_min_pct: string;
  share_max_pct: string;
  charge_type: string;
  charge_value: string;
  charge_basis: string;
  cabin: string;
  plus_gst: boolean;
  description: string;
  source_text: string;
  source_page: string;
};

export const blankTerm = (): TermDraft => ({
  rule_type: "CANCELLATION", scope: "GROUP", phase: "ANY", days_before_max: "",
  days_before_min: "", share_min_pct: "", share_max_pct: "", charge_type: "PCT_OF_BASIS",
  charge_value: "", charge_basis: "NET_FARE", cabin: "", plus_gst: false, description: "",
  source_text: "", source_page: "",
});

const str = (v: unknown) => (v == null ? "" : String(v));

export const termToDraft = (t: Partial<Term>): TermDraft => ({
  rule_type: t.rule_type ?? "CANCELLATION",
  scope: str(t.scope),
  phase: t.phase ?? "ANY",
  days_before_max: str(t.days_before_max),
  days_before_min: str(t.days_before_min),
  share_min_pct: str(t.share_min_pct),
  share_max_pct: str(t.share_max_pct),
  charge_type: t.charge_type ?? "PCT_OF_BASIS",
  charge_value: str(t.charge_value),
  charge_basis: str(t.charge_basis),
  cabin: str(t.cabin),
  plus_gst: !!t.plus_gst,
  description: str(t.description),
  source_text: str(t.source_text),
  source_page: str(t.source_page),
});

export const draftToTerm = (t: TermDraft) => ({
  rule_type: t.rule_type,
  scope: t.scope || null,
  phase: t.phase || "ANY",
  days_before_max: num(t.days_before_max),
  days_before_min: num(t.days_before_min),
  share_min_pct: num(t.share_min_pct),
  share_max_pct: num(t.share_max_pct),
  charge_type: t.charge_type,
  charge_value: num(t.charge_value),
  charge_basis: t.charge_type === "PCT_OF_BASIS" ? t.charge_basis || "NET_FARE" : null,
  cabin: t.cabin || null,
  plus_gst: t.plus_gst,
  description: t.description.trim() || null,
  source_text: t.source_text.trim() || null,
  source_page: num(t.source_page),
});

const NEEDS_VALUE = new Set(["PCT_OF_BASIS", "FIXED_PER_PAX", "FIXED_TOTAL"]);

export function TermsEditor({
  value, onChange, onJump,
}: {
  value: TermDraft[];
  onChange: (v: TermDraft[]) => void;
  onJump?: (page: number) => void;
}) {
  const setAt = (i: number, patch: Partial<TermDraft>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <div>
      {value.length === 0 && (
        <p className="text-[11px] text-gray-400 py-3">
          No terms yet. Add the airline&apos;s cancellation bands, seat-release allowance and
          name-change charges — they price every change you make to this group.
        </p>
      )}
      <div className="space-y-2">
        {value.map((t, i) => (
          <div key={i} className="border border-gray-200 rounded-lg p-2.5 bg-gray-50/40">
            <div className="grid grid-cols-[130px_110px_150px_1fr_28px] gap-1.5 items-end">
              <div>
                <label className={LABEL}>Rule</label>
                <select value={t.rule_type} onChange={(e) => setAt(i, { rule_type: e.target.value })} className={SMALL_INPUT}>
                  {TERM_RULE_TYPES.map((r) => <option key={r} value={r}>{TERM_RULE_LABEL[r]}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>Applies to</label>
                <select value={t.scope} onChange={(e) => setAt(i, { scope: e.target.value })} className={SMALL_INPUT}>
                  <option value="">—</option>
                  {TERM_SCOPES.map((r) => <option key={r} value={r}>{TERM_SCOPE_LABEL[r]}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>When</label>
                <select value={t.phase} onChange={(e) => setAt(i, { phase: e.target.value })} className={SMALL_INPUT}>
                  {TERM_PHASES.map((r) => <option key={r} value={r}>{TERM_PHASE_LABEL[r]}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-[1fr_1fr_1fr_1fr] gap-1.5">
                <div>
                  <label className={LABEL} title="Far edge of the window, in days before departure. Empty = open.">
                    From day
                  </label>
                  <input type="number" min="0" value={t.days_before_max} placeholder="∞"
                    onChange={(e) => setAt(i, { days_before_max: e.target.value })} className={SMALL_INPUT} />
                </div>
                <div>
                  <label className={LABEL} title="Near edge of the window, in days before departure.">To day</label>
                  <input type="number" min="0" value={t.days_before_min} placeholder="0"
                    onChange={(e) => setAt(i, { days_before_min: e.target.value })} className={SMALL_INPUT} />
                </div>
                <div>
                  <label className={LABEL} title="Share of the seats this covers — e.g. the first 20% free">Seats from %</label>
                  <input type="number" min="0" max="100" value={t.share_min_pct}
                    onChange={(e) => setAt(i, { share_min_pct: e.target.value })} className={SMALL_INPUT} />
                </div>
                <div>
                  <label className={LABEL}>Seats to %</label>
                  <input type="number" min="0" max="100" value={t.share_max_pct}
                    onChange={(e) => setAt(i, { share_max_pct: e.target.value })} className={SMALL_INPUT} />
                </div>
              </div>
              <Remove onClick={() => onChange(value.filter((_, x) => x !== i))} title="Remove term" />
            </div>

            <div className="grid grid-cols-[150px_90px_1fr_130px_70px] gap-1.5 items-end mt-1.5">
              <div>
                <label className={LABEL}>Charge</label>
                <select value={t.charge_type} onChange={(e) => setAt(i, { charge_type: e.target.value })} className={SMALL_INPUT}>
                  {TERM_CHARGE_TYPES.map((r) => <option key={r} value={r}>{TERM_CHARGE_LABEL[r]}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>{t.charge_type === "PCT_OF_BASIS" ? "%" : "Amount"}</label>
                <input type="number" step="0.01" value={t.charge_value} disabled={!NEEDS_VALUE.has(t.charge_type)}
                  onChange={(e) => setAt(i, { charge_value: e.target.value })}
                  className={`${SMALL_INPUT} tabular-nums text-right disabled:bg-gray-100`} />
              </div>
              <div>
                <label className={LABEL}>Of</label>
                <select value={t.charge_basis} disabled={t.charge_type !== "PCT_OF_BASIS"}
                  onChange={(e) => setAt(i, { charge_basis: e.target.value })} className={`${SMALL_INPUT} disabled:bg-gray-100`}>
                  <option value="">—</option>
                  {FARE_BASES.map((b) => <option key={b} value={b}>{FARE_BASIS_LABEL[b]}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>Cabin</label>
                <select value={t.cabin} onChange={(e) => setAt(i, { cabin: e.target.value })} className={SMALL_INPUT}>
                  <option value="">Any cabin</option>
                  {CABINS.map((c) => <option key={c} value={c}>{CABIN_LABEL[c]}</option>)}
                </select>
              </div>
              <label className="flex items-center gap-1 text-[11px] text-gray-600 pb-1.5">
                <input type="checkbox" checked={t.plus_gst} onChange={(e) => setAt(i, { plus_gst: e.target.checked })}
                  className="w-3.5 h-3.5 accent-[#1e3a5f]" /> + GST
              </label>
            </div>

            <input
              value={t.description}
              onChange={(e) => setAt(i, { description: e.target.value })}
              placeholder="Plain-English summary, e.g. Total cancellation 120–101 days out costs 15% of the net fare"
              className={`${SMALL_INPUT} mt-1.5`}
            />
            {t.source_text && (
              <p className="text-[10px] text-gray-400 mt-1 italic">
                {t.source_page && (
                  <button type="button" onClick={() => onJump?.(Number(t.source_page))}
                    className="not-italic font-semibold text-violet-600 hover:underline mr-1">
                    p.{t.source_page}
                  </button>
                )}
                “{t.source_text}”
              </p>
            )}
          </div>
        ))}
      </div>
      <Add label="Add term" disabled={value.length >= 80} onClick={() => onChange([...value, blankTerm()])} />
    </div>
  );
}

// ── Deadline rules ───────────────────────────────────────────────────────────

export type DeadlineDraft = {
  deadline_type: string;
  offset_days: string;
  offset_hours: string;
  stated_date: string;
  action_required: string;
};

export const blankDeadline = (): DeadlineDraft => ({
  deadline_type: "NAME_LIST", offset_days: "", offset_hours: "", stated_date: "", action_required: "",
});

export function DeadlineRulesEditor({
  value, onChange,
}: {
  value: DeadlineDraft[];
  onChange: (v: DeadlineDraft[]) => void;
}) {
  const setAt = (i: number, patch: Partial<DeadlineDraft>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const types = [...MANUAL_DEADLINE_TYPES, "OPTION_EXPIRY"];

  return (
    <div>
      <div className="grid grid-cols-[160px_90px_90px_140px_1fr_28px] gap-1.5 items-end mb-1">
        <label className={LABEL}>Deadline</label>
        <label className={LABEL}>Days before</label>
        <label className={LABEL}>Hours before</label>
        <label className={LABEL}>Date printed</label>
        <label className={LABEL}>What to do</label>
        <span />
      </div>
      <div className="space-y-1.5">
        {value.map((d, i) => (
          <div key={i} className="grid grid-cols-[160px_90px_90px_140px_1fr_28px] gap-1.5 items-center">
            <select value={d.deadline_type} onChange={(e) => setAt(i, { deadline_type: e.target.value })} className={SMALL_INPUT}>
              {types.map((t) => <option key={t} value={t}>{DEADLINE_TYPE_LABEL[t]}</option>)}
            </select>
            <input type="number" min="0" value={d.offset_days} placeholder="30"
              onChange={(e) => setAt(i, { offset_days: e.target.value })} className={SMALL_INPUT} />
            <input type="number" min="0" value={d.offset_hours} placeholder="24"
              onChange={(e) => setAt(i, { offset_hours: e.target.value })} className={SMALL_INPUT} />
            <input type="date" value={d.stated_date}
              onChange={(e) => setAt(i, { stated_date: e.target.value })} className={SMALL_INPUT} />
            <input value={d.action_required} placeholder="Send the complete name list"
              onChange={(e) => setAt(i, { action_required: e.target.value })} className={SMALL_INPUT} />
            <Remove onClick={() => onChange(value.filter((_, x) => x !== i))} title="Remove deadline" />
          </div>
        ))}
      </div>
      <Add label="Add deadline" disabled={value.length >= 20} onClick={() => onChange([...value, blankDeadline()])} />
      <p className="text-[10px] text-gray-400 mt-1">
        A rule in days or hours repeats on every departure. When the contract also prints the
        date, keep both — the printed date is enforced, and a disagreement is flagged.
        Payment dates come from the payment step; cancellation-charge steps from the terms.
      </p>
    </div>
  );
}

// ── Passengers ───────────────────────────────────────────────────────────────

export type PassengerDraft = {
  title: string;
  first_name: string;
  last_name: string;
  pax_type: string;
  gender: string;
  date_of_birth: string;
  nationality: string;
  passport_number: string;
  passport_expiry: string;
};

export const blankPassenger = (): PassengerDraft => ({
  title: "", first_name: "", last_name: "", pax_type: "ADT", gender: "", date_of_birth: "",
  nationality: "", passport_number: "", passport_expiry: "",
});

export function PassengerListEditor({
  value, onChange,
}: {
  value: PassengerDraft[];
  onChange: (v: PassengerDraft[]) => void;
}) {
  const setAt = (i: number, patch: Partial<PassengerDraft>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const cols = "grid-cols-[28px_60px_1fr_1fr_100px_70px_120px_110px_120px_28px]";

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[900px]">
        <div className={`grid ${cols} gap-1.5 items-end mb-1`}>
          <span className={LABEL}>#</span>
          <label className={LABEL}>Title</label>
          <label className={LABEL}>First name</label>
          <label className={LABEL}>Last name</label>
          <label className={LABEL}>Type</label>
          <label className={LABEL}>Gender</label>
          <label className={LABEL}>Date of birth</label>
          <label className={LABEL}>Passport</label>
          <label className={LABEL}>Expiry</label>
          <span />
        </div>
        <div className="space-y-1">
          {value.map((p, i) => (
            <div key={i} className={`grid ${cols} gap-1.5 items-center`}>
              <span className="text-[10px] text-gray-400 tabular-nums">{i + 1}</span>
              <input value={p.title} onChange={(e) => setAt(i, { title: e.target.value })} placeholder="MR" className={SMALL_INPUT} />
              <input value={p.first_name} onChange={(e) => setAt(i, { first_name: e.target.value.toUpperCase() })} className={`${SMALL_INPUT} uppercase`} />
              <input value={p.last_name} onChange={(e) => setAt(i, { last_name: e.target.value.toUpperCase() })} className={`${SMALL_INPUT} uppercase`} />
              <select value={p.pax_type} onChange={(e) => setAt(i, { pax_type: e.target.value })} className={SMALL_INPUT}>
                {PAX_TYPES.map((t) => <option key={t} value={t}>{PAX_TYPE_LABEL[t]}</option>)}
              </select>
              <select value={p.gender} onChange={(e) => setAt(i, { gender: e.target.value })} className={SMALL_INPUT}>
                <option value="">—</option><option value="M">M</option><option value="F">F</option><option value="X">X</option>
              </select>
              <input type="date" value={p.date_of_birth} onChange={(e) => setAt(i, { date_of_birth: e.target.value })} className={SMALL_INPUT} />
              <input value={p.passport_number} onChange={(e) => setAt(i, { passport_number: e.target.value.toUpperCase() })} className={`${SMALL_INPUT} font-mono uppercase`} />
              <input type="date" value={p.passport_expiry} onChange={(e) => setAt(i, { passport_expiry: e.target.value })} className={SMALL_INPUT} />
              <Remove onClick={() => onChange(value.filter((_, x) => x !== i))} title="Remove passenger" />
            </div>
          ))}
        </div>
        <Add label="Add passenger" disabled={value.length >= 500} onClick={() => onChange([...value, blankPassenger()])} />
      </div>
    </div>
  );
}
