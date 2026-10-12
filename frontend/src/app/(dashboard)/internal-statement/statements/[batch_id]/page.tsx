"use client";

// Internal Statement → Statements → one uploaded statement and the tickets it loaded.
//
// Deliberately not the Customer data detail screen (tickets/[batch_id]): that one is
// built around deal calculation, income summaries and match diagnosis, none of which
// Internal Statement runs (see backend api/v1/internal_tickets.py). This is the file
// as it was loaded — its tickets, its Invoice Amounts.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertCircle, Calendar, ChevronLeft, FileSpreadsheet, Ticket, Trash2 } from "lucide-react";
import api from "@/lib/api";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import InternalTicketsView from "@/components/tickets/InternalTicketsView";

type Statement = {
  batch_id: string;
  statement_name: string | null;
  agency: string;
  valid_from: string;
  valid_to: string;
  file_name: string;
  ticket_count: number;
  created_by_name: string | null;
  created_at: string;
};

const fmt = (d?: string | null) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";

export default function InternalStatementDetailPage() {
  const { batch_id } = useParams<{ batch_id: string }>();
  const [statement, setStatement] = useState<Statement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const router = useRouter();

  const load = useCallback(() => {
    api.get<Statement>(`/internal-tickets/statements/${batch_id}`)
      .then((r) => setStatement(r.data))
      .catch(() => setError("Could not load this statement."));
  }, [batch_id]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href="/internal-statement/statements"
          className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500" title="Back to statements">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-gray-900 leading-tight truncate">
            {statement ? (statement.statement_name || statement.agency) : "Statement"}
          </h1>
          <p className="text-xs text-gray-500">Internal Statement · uploaded statement</p>
        </div>
        {statement && (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="ml-auto flex items-center gap-1.5 px-3 py-2 border border-red-200 text-red-600 rounded-lg text-xs font-semibold hover:bg-red-50"
          >
            <Trash2 className="w-3.5 h-3.5" /> Delete statement
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {statement && (
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center gap-x-8 gap-y-2 flex-wrap text-xs">
          <span className="text-gray-500">Customer <b className="text-gray-800 ml-1">{statement.agency}</b></span>
          <span className="flex items-center gap-1.5 text-gray-500">
            <Calendar className="w-3.5 h-3.5" />
            <b className="text-gray-800">{fmt(statement.valid_from)} → {fmt(statement.valid_to)}</b>
          </span>
          <span className="flex items-center gap-1.5 text-gray-500 min-w-0">
            <FileSpreadsheet className="w-3.5 h-3.5 shrink-0" />
            <b className="text-gray-800 truncate max-w-[260px]" title={statement.file_name}>{statement.file_name}</b>
          </span>
          <span className="flex items-center gap-1.5 text-gray-500">
            <Ticket className="w-3.5 h-3.5" />
            <b className="text-gray-800">{statement.ticket_count}</b> tickets
          </span>
          <span className="text-gray-400 ml-auto">
            Uploaded {fmt(statement.created_at)}{statement.created_by_name ? ` by ${statement.created_by_name}` : ""}
          </span>
        </div>
      )}

      <InternalTicketsView batchId={batch_id} onDeleted={load} />

      {confirmDelete && statement && (
        <ConfirmDialog
          title="Delete statement?"
          confirmLabel={`Delete statement and ${statement.ticket_count} ticket${statement.ticket_count !== 1 ? "s" : ""}`}
          onClose={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await api.delete(`/internal-tickets/statements/${batch_id}`);
            router.push("/internal-statement/statements");
          }}
        >
          <p>
            <b>{statement.statement_name || statement.agency}</b> ({statement.file_name}) and all{" "}
            <b>{statement.ticket_count}</b> ticket{statement.ticket_count !== 1 ? "s" : ""} loaded with it will be
            permanently deleted. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
