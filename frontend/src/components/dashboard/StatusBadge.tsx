"use client";

import {
  AlertOctagon, AlertTriangle, CheckCircle2, Clock, Split, XCircle,
} from "lucide-react";
import { STATUS, type StatusCode } from "@/lib/accrual";

/**
 * A status always ships as icon + text, never colour alone — the colour is a
 * reinforcement for people who can see it, not the message.
 */
const ICON: Record<StatusCode, typeof AlertTriangle> = {
  EXPIRED_WITH_FLOWN: AlertOctagon,
  NO_DEAL: XCircle,
  NO_RATE: AlertTriangle,
  NEEDS_SPLIT: Split,
  EXPIRING: Clock,
  UNCONFIRMED: Clock,
  OK: CheckCircle2,
};

export default function StatusBadge({
  code,
  full = false,
}: {
  code: StatusCode;
  full?: boolean;
}) {
  const meta = STATUS[code];
  const Icon = ICON[code];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${meta.chip}`}
      title={meta.blurb || meta.label}
    >
      <Icon className="w-3 h-3 shrink-0" aria-hidden />
      {full ? meta.label : meta.short}
    </span>
  );
}
