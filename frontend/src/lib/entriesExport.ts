// "Download entries" — the rows an upload left in the system, as an .xlsx built by the
// server from the stored rows (never from the uploaded file). Shared by the LCC Detailed
// view and the spec-driven statements view (NDC), whose endpoints both answer
// `GET <apiBase>/batches/<id>/export` and honour the drill-in's `f.<field>` filters.
import api from "@/lib/api";

/** Mirrors statement_export.file_name on the server — its Content-Disposition isn't
 *  exposed over CORS, so the browser can't read the name the server chose. */
export function entriesFileName(source: string | null): string {
  const stem = (source ?? "").trim().replace(/\.(xlsx|xls|csv|tsv|txt)$/i, "")
    .replace(/[\\/:*?"<>|]+/g, "_").replace(/^[ .]+|[ .]+$/g, "") || "upload";
  return `${stem} - entries in system.xlsx`;
}

/** Fetches and saves the workbook. Throws an Error carrying the server's own reason. */
export async function downloadEntries(
  apiBase: string, batchId: string, sourceFile: string | null, filters: Record<string, string> = {},
): Promise<void> {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(filters)) if (v) params[`f.${k}`] = v;
  try {
    const { data } = await api.get(`${apiBase}/batches/${batchId}/export`, { params, responseType: "blob" });
    const url = URL.createObjectURL(data as Blob);
    const a = document.createElement("a"); a.href = url; a.download = entriesFileName(sourceFile); a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    // responseType "blob" makes the error body a Blob too, so the server's reason has to
    // be read back out of it.
    let msg = "Could not export the entries.";
    const body = (e as { response?: { data?: unknown } })?.response?.data;
    if (body instanceof Blob) {
      try { const d = JSON.parse(await body.text())?.detail; if (typeof d === "string") msg = d; } catch { /* not JSON */ }
    }
    throw new Error(msg);
  }
}
