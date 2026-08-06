"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import toast from "react-hot-toast";
import {
  AlertCircle, ChevronLeft, RefreshCw, RotateCcw, Save,
} from "lucide-react";
import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import TicketFilingCard, {
  NEW_STATEMENT, type StatementOption,
} from "@/components/tickets/TicketFilingCard";
import TicketFieldGroupCard from "@/components/tickets/TicketFieldGroupCard";
import TicketFieldInput from "@/components/tickets/TicketFieldInput";
import TaxBreakupEditor from "@/components/tickets/TaxBreakupEditor";
import ItineraryLegsEditor from "@/components/tickets/ItineraryLegsEditor";
import LegPreview from "@/components/tickets/LegPreview";
import AirlinePicker from "@/components/tickets/AirlinePicker";
import {
  BLANK_LEG, LEG_SECTOR_RE, MANUAL_ENTRY_FILE_NAME, REQUIRED_KEYS,
  coerceFieldValue, composeLegs, fieldByKey, groupedFieldsFor, legFieldKeys,
  predictAdmAcmRa,
  type FieldGroupId, type ItineraryLeg, type StatementType,
  type TicketExtractionPreview, type TicketRow,
} from "@/lib/ticketFields";

type Draft = Record<string, unknown>;

const DEFAULT_OPEN: FieldGroupId[] = ["identity", "passenger", "itinerary", "fare"];
const PREVIEW_DEBOUNCE_MS = 400;

const isBlank = (v: unknown) => v === null || v === undefined || v === "";

// ── Page ─────────────────────────────────────────────────────────────────────

export default function CreateTicketPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Filing
  const [target, setTarget] = useState<string>(NEW_STATEMENT);
  const [statements, setStatements] = useState<StatementOption[]>([]);
  const [ticketType, setTicketType] = useState<StatementType>("B2B");
  const [agency, setAgency] = useState("");
  const [statementName, setStatementName] = useState("");
  const [agencyOptions, setAgencyOptions] = useState<string[]>([]);
  const [validFrom, setValidFrom] = useState("");
  const [validTo, setValidTo] = useState("");

  // Ticket. Itinerary lives outside `draft` because it is repeatable — the two
  // are folded together by composeLegs into the single row the API takes.
  const [draft, setDraft] = useState<Draft>({});
  const [legs, setLegs] = useState<ItineraryLeg[]>([BLANK_LEG]);
  const [touched, setTouched] = useState(false);
  const [openGroups, setOpenGroups] = useState<Set<FieldGroupId>>(new Set(DEFAULT_OPEN));

  // Server-derived view of the current draft
  const [rows, setRows] = useState<TicketRow[]>([]);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [runCalcNow, setRunCalcNow] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then((r) => setAgencyOptions(r.data.map((s) => s.name)))
      .catch(() => {});
    api.get<StatementOption[]>("/tickets/statements")
      .then((r) => setStatements(r.data))
      .catch(() => {});
  }, []);

  // Arriving from a statement's "Add ticket" button pre-selects that statement.
  const presetBatch = searchParams.get("statement");
  useEffect(() => {
    const preset = presetBatch && statements.find((s) => s.batch_id === presetBatch);
    if (!preset) return;
    setTarget(preset.batch_id);
    // The combo shows the statement's name, so seed it too or the box reads empty.
    setStatementName(preset.statement_name || preset.agency);
  }, [presetBatch, statements]);

  const isNew = target === NEW_STATEMENT;
  const selectedStatement = statements.find((s) => s.batch_id === target);

  // Filing into an existing statement means its type wins — the append endpoint
  // takes the statement's own type, so the form must show that field set.
  const effectiveType: StatementType = isNew
    ? ticketType
    : (selectedStatement?.statement_type ?? "B2B");

  const groups = useMemo(() => groupedFieldsFor(effectiveType), [effectiveType]);

  /**
   * The row actually sent to the server: the flat draft with the punched legs
   * folded in. Everything downstream — preview, validation, the group counters
   * and save — reads this, so none of them can disagree about what a leg holds.
   */
  const composed = useMemo<Draft>(
    () => ({ ...draft, ...composeLegs(legs, effectiveType) }),
    [draft, legs, effectiveType],
  );

  const draftIsEmpty = useMemo(
    () => Object.values(composed).every(
      (v) => isBlank(v) || (typeof v === "object" && v !== null && Object.keys(v).length === 0)),
    [composed],
  );

  // ── Preview: the single source of truth for what gets saved ───────────────
  const requestPreview = useCallback(
    async (rows: Draft[], signal?: AbortSignal) => {
      const { data } = await api.post<TicketExtractionPreview>(
        "/tickets/manual/preview",
        { rows, statement_type: effectiveType },
        { signal },
      );
      return data;
    },
    [effectiveType],
  );

  useEffect(() => {
    if (draftIsEmpty) {
      setRows([]); setPreviewWarnings([]); setPreviewError(null);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      setPreviewing(true);
      try {
        const data = await requestPreview([composed], ctrl.signal);
        setRows(data.rows);
        setPreviewWarnings(data.warnings);
        setPreviewError(null);
      } catch {
        if (ctrl.signal.aborted) return;
        // Silent by design — this fires on every keystroke, so a toast per
        // failure would be unusable. The inline note carries the signal.
        setPreviewError("Couldn't refresh the preview — check your connection.");
      } finally {
        if (!ctrl.signal.aborted) setPreviewing(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [composed, draftIsEmpty, requestPreview]);

  const setField = (key: string, value: unknown) =>
    setDraft((prev) => {
      const next = { ...prev };
      if (isBlank(value)) delete next[key]; else next[key] = value;
      return next;
    });

  // ── Validation ────────────────────────────────────────────────────────────
  // Each block holds exactly one leg, so the shape is checked per block rather
  // than against the composed multi-leg string.
  const punchedLegs = legs.filter((l) => (l.sector ?? "").trim() !== "");
  const legMalformed = punchedLegs.some(
    (l) => !LEG_SECTOR_RE.test((l.sector ?? "").trim().toUpperCase()),
  );
  const missingRequired = REQUIRED_KEYS.filter((k) => isBlank(composed[k]));
  const filingReady = isNew
    ? agency !== "" && validFrom !== "" && validTo !== "" && validTo >= validFrom
    : !!selectedStatement;
  const ticketReady = missingRequired.length === 0 && !legMalformed && rows.length > 0;
  const canSave = filingReady && ticketReady && !previewing && !saving;

  // Leg-owned keys are flagged inside the leg editor, not by the flat grid.
  const legKeys = new Set(legFieldKeys(effectiveType));
  const invalidKeys = new Set(
    touched ? missingRequired.filter((k) => !legKeys.has(k)) : [],
  );

  const predicted = predictAdmAcmRa(draft.ticket_number as string);
  const derived = rows[0];

  const reset = () => {
    setDraft({}); setLegs([BLANK_LEG]); setTouched(false);
    setRows([]); setPreviewWarnings([]); setPreviewError(null);
  };

  // ── Save ──────────────────────────────────────────────────────────────────
  const save = async () => {
    setTouched(true);
    if (!filingReady || !ticketReady || saving) return;
    setSaving(true);
    try {
      // Re-derive server-side immediately before saving, in case Save landed
      // while the debounce was still pending.
      const fresh = await requestPreview([composed]);
      const out: TicketRow[] = fresh.rows.map((r, i) => ({ ...r, row_order: i + 1 }));

      const batchId = isNew
        ? (await api.post<{ batch_id: string; created_count: number }>(
            "/tickets/upload/confirm",
            {
              file_name: MANUAL_ENTRY_FILE_NAME,
              rows: out,
              statement_type: ticketType,
              agency,
              statement_name: statementName.trim() || null,
              valid_from: validFrom,
              valid_to: validTo,
            },
          )).data.batch_id
        : (await api.post<{ batch_id: string; created_count: number }>(
            `/tickets/statements/${target}/tickets`, { rows: out },
          )).data.batch_id;

      const rowWord = `${out.length} row${out.length !== 1 ? "s" : ""}`;
      if (runCalcNow) {
        try {
          const { data: calc } = await api.patch<{ matched: number; unmatched: number }>(
            "/tickets/uploads/run-all-calculation", null, { params: { batch_id: batchId } },
          );
          toast.success(`Ticket saved — ${rowWord} · ${calc.matched} matched, ${calc.unmatched} unmatched`);
        } catch {
          toast.error("Saved, but the deal calculation could not be started.");
        }
      } else {
        toast.success(`Ticket saved — ${rowWord}`);
      }

      router.push(`/tickets/${batchId}`);
    } catch (e) {
      toast.error(apiError(e));
      setSaving(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Link href="/tickets" className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Create Ticket</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Punch one ticket by hand — stored exactly like an uploaded one
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={reset}
            disabled={draftIsEmpty}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Clear form
          </button>
          <Link
            href="/tickets/upload"
            className="px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50"
          >
            Have a file? Upload instead
          </Link>
        </div>
      </div>

      {/* filing */}
      <TicketFilingCard
        target={target} setTarget={setTarget}
        statements={statements}
        ticketType={ticketType} setTicketType={setTicketType}
        agency={agency} setAgency={setAgency} agencyOptions={agencyOptions}
        statementName={statementName} setStatementName={setStatementName}
        validFrom={validFrom} setValidFrom={setValidFrom}
        validTo={validTo} setValidTo={setValidTo}
        touched={touched}
      />

      {/* derived strip */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-2.5 flex items-center gap-2 flex-wrap text-[11px]">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mr-1">
          Derived at save
        </span>
        <Chip label="Rows"
          value={rows.length > 1 ? `split × ${rows.length}` : rows.length === 1 ? "1" : "—"}
          tone={rows.length > 1 ? "amber" : "plain"} />
        <Chip label="ADM/ACM/RA" value={predicted ?? "—"} tone={predicted ? "amber" : "plain"} />
        <Chip label="Segment type" value={derived?.segment_type ?? "—"} />
        <Chip label="Invoice type" value={derived?.invoice_type ?? "—"} />
        <Chip label="Departure" value={derived?.departure_datetime ?? "—"} />
        <Chip label="YQ / YR / K3"
          value={[derived?.sell_tax_yq, derived?.sale_yr, derived?.sale_k3].some((v) => v != null)
            ? `${derived?.sell_tax_yq ?? "—"} / ${derived?.sale_yr ?? "—"} / ${derived?.sale_k3 ?? "—"}`
            : "—"} />
        {previewing && <RefreshCw className="w-3 h-3 text-blue-400 animate-spin ml-auto" />}
      </div>

      {/* warnings */}
      {previewWarnings.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-[11px] text-yellow-800 space-y-1">
          {previewWarnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />{w}
            </div>
          ))}
        </div>
      )}

      {/* field groups */}
      {groups.map(({ group, fields }) => {
        const open = openGroups.has(group.id);
        // Counted off `composed`, so a leg-owned field reads as filled the
        // moment any leg carries it — no special case for the repeater.
        const filled = fields.filter((f) => !isBlank(composed[f.key])).length
          + (group.custom === "tax_breakup" && draft.tax_breakup ? 1 : 0);
        const invalidCount = fields.filter((f) => invalidKeys.has(f.key)).length
          + (group.id === "itinerary" && touched && (legMalformed || isBlank(composed.sector)) ? 1 : 0);

        return (
          <TicketFieldGroupCard
            key={group.id}
            group={group}
            open={open}
            onToggle={() => setOpenGroups((prev) => {
              const next = new Set(prev);
              if (next.has(group.id)) next.delete(group.id); else next.add(group.id);
              return next;
            })}
            filledCount={filled}
            totalCount={group.custom ? 1 : fields.length}
            invalidCount={invalidCount}
          >
            {group.custom === "tax_breakup" ? (
              <TaxBreakupEditor
                value={draft.tax_breakup as Record<string, number> | null}
                onChange={(v) => setField("tax_breakup", v)}
              />
            ) : (
              <div className="space-y-3">
                {group.id === "itinerary" && (
                  <ItineraryLegsEditor
                    legs={legs}
                    statementType={effectiveType}
                    onChange={setLegs}
                    showErrors={touched}
                  />
                )}

                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-4 gap-y-3">
                  {fields.map((f) => {
                    // Leg-owned fields are rendered per leg by the repeater above.
                    if (group.id === "itinerary" && legKeys.has(f.key)) return null;
                    // Airline code and name are one decision, so they share one
                    // control backed by the airline master.
                    if (f.key === "airlines_code") {
                      return (
                        <AirlinePicker
                          key={f.key}
                          code={String(draft.airlines_code ?? "")}
                          name={String(draft.airline_name ?? "")}
                          required
                          invalid={invalidKeys.has("airlines_code")}
                          onCodeChange={(v) => setField("airlines_code", v)}
                          onPick={(a) => {
                            setField("airlines_code", a.iata_code);
                            setField("airline_name", a.name);
                          }}
                        />
                      );
                    }
                    if (f.key === "airline_name") return null;

                    return (
                      <TicketFieldInput
                        key={f.key}
                        field={f}
                        value={draft[f.key] as string | number | null}
                        required={!!f.mapRequired}
                        invalid={invalidKeys.has(f.key)}
                        onChange={(raw) => setField(f.key, coerceFieldValue(f, raw))}
                      />
                    );
                  })}
                </div>

                {group.id === "itinerary" && (
                  <LegPreview
                    rows={rows}
                    original={{
                      sell_fare: (draft.sell_fare as number) ?? null,
                      sell_tax: (draft.sell_tax as number) ?? null,
                      sell_tax_yq: (draft.sell_tax_yq as number) ?? null,
                      sale_yr: (draft.sale_yr as number) ?? null,
                    }}
                    loading={previewing}
                    error={previewError}
                  />
                )}
              </div>
            )}
          </TicketFieldGroupCard>
        );
      })}

      {/* save bar */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap sticky bottom-4 shadow-sm">
        <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={runCalcNow}
            onChange={(e) => setRunCalcNow(e.target.checked)}
            className="accent-blue-600 cursor-pointer"
          />
          Run deal calculation after saving
        </label>

        {touched && missingRequired.length > 0 && (
          <span className="text-[11px] text-red-500">
            Required: {missingRequired.map((k) => fieldByKey[k]?.label ?? k).join(", ")}
          </span>
        )}
        {touched && legMalformed && (
          <span className="text-[11px] text-red-500">
            Each sector block must hold one leg, written as DEL/BOM
          </span>
        )}
        {touched && !filingReady && (
          <span className="text-[11px] text-red-500">Complete the filing details above</span>
        )}

        <button
          onClick={save}
          disabled={saving}
          title={!canSave && !saving ? "Fill in the required fields first" : undefined}
          className="ml-auto flex items-center gap-1.5 px-5 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving
            ? <><RefreshCw className="w-4 h-4 animate-spin" /> Saving…</>
            : <><Save className="w-4 h-4" /> Save ticket{rows.length > 1 ? ` (${rows.length} rows)` : ""}</>}
        </button>
      </div>
    </div>
  );
}

function Chip({ label, value, tone = "plain" }: { label: string; value: string; tone?: "plain" | "amber" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border ${
      tone === "amber"
        ? "bg-amber-50 border-amber-200 text-amber-700"
        : "bg-gray-50 border-gray-200 text-gray-600"
    }`}>
      <span className="text-[9px] uppercase tracking-wide opacity-60">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
  );
}
