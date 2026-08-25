"use client";

import { useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { downloadMasterExport, type MasterResource } from "@/lib/masterExport";

/** Read FastAPI's `detail` out of a failed blob request.
 *
 * responseType "blob" applies to error responses too, so the JSON body arrives
 * as a Blob and the usual `response.data.detail` reads undefined. */
async function exportError(e: unknown): Promise<string> {
  const data = (e as { response?: { data?: unknown } })?.response?.data;
  try {
    const raw = data instanceof Blob ? await data.text() : null;
    const detail = raw ? (JSON.parse(raw) as { detail?: string }).detail : undefined;
    if (detail) return detail;
  } catch {
    /* not JSON — fall through to the generic message */
  }
  return "Export failed. Please try again.";
}

/** "Export XLS" for one Master Governance master — the whole master, not the
 * page or the current search, so the admin reviews the complete list. */
export default function ExportMasterButton({
  resource,
  filename,
  label = "Export XLS",
}: {
  resource: MasterResource;
  filename: string;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      await downloadMasterExport(resource, filename);
    } catch (e) {
      setError(await exportError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={run}
      disabled={busy}
      title={error || "Download the full master as an Excel file"}
      className={`flex items-center gap-1.5 bg-white border px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50 ${
        error ? "border-red-200 text-red-500" : "border-gray-200 text-gray-600"
      }`}
    >
      {busy
        ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
        : <Download className="w-3.5 h-3.5" />}
      {busy ? "Preparing…" : error ? "Export failed" : label}
    </button>
  );
}
