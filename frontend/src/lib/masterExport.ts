// Master Governance's "Export XLS" — the platform admin pulls a whole master
// into Excel, reviews it, and comes back to correct it here.
//
// Each master serves its own sheet at GET /{resource}/export, built by
// backend/app/services/master_export.py. The sheets reuse the upload template's
// column headers, so a reviewed file can go straight back through the same
// master's bulk-upload.

import api from "@/lib/api";

export type MasterResource =
  | "suppliers"
  | "airlines"
  | "airports"
  | "classes"
  | "iata-commissions";

export async function downloadMasterExport(resource: MasterResource, filename: string) {
  const res = await api.get(`/${resource}/export`, { responseType: "blob" });
  const url = window.URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
