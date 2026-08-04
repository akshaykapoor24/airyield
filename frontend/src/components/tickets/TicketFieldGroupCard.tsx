"use client";

import type { ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { FieldGroup } from "@/lib/ticketFields";

/**
 * Collapsible card for one field group.
 *
 * The filled-field count in the header is what makes collapsing safe: a user can
 * close a group and still see at a glance that it holds data.
 */
export default function TicketFieldGroupCard({
  group, open, onToggle, filledCount, totalCount, invalidCount, children,
}: {
  group: FieldGroup;
  open: boolean;
  onToggle: () => void;
  filledCount: number;
  totalCount: number;
  invalidCount?: number;
  children: ReactNode;
}) {
  return (
    // No overflow-hidden: the airline picker inside opens as an absolute panel
    // and would be clipped by it. The header rounds its own corners instead.
    <div className="bg-white border border-gray-200 rounded-xl">
      <button
        type="button"
        onClick={onToggle}
        className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left ${
          open ? "rounded-t-xl" : "rounded-xl"
        }`}
      >
        <span className="w-1.5 h-6 rounded-full shrink-0" style={{ background: group.color }} />
        {open
          ? <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
          : <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />}

        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">{group.label}</p>
          {group.description && (
            <p className="text-[10px] text-gray-400 mt-0.5 leading-snug">{group.description}</p>
          )}
        </div>

        {invalidCount ? (
          <span className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-600 border border-red-200">
            {invalidCount} to fix
          </span>
        ) : null}

        <span
          className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
            filledCount > 0
              ? "bg-blue-50 text-blue-700 border border-blue-200"
              : "bg-gray-50 text-gray-400 border border-gray-200"
          }`}
        >
          {filledCount} / {totalCount}
        </span>
      </button>

      {open && <div className="px-4 pb-4 pt-1 border-t border-gray-100">{children}</div>}
    </div>
  );
}
