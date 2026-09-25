"use client";

/**
 * The paper behind the contract: the PDF it was read from, and any amendment or name list
 * filed against it later. Files are streamed through the API rather than linked from the
 * bucket, so neither a GCS object nor a local fallback copy is ever publicly addressable.
 */

import { useRef, useState } from "react";
import toast from "react-hot-toast";
import { FileText, Loader2, Trash2, Upload } from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import { API_BASE, DOCUMENT_KIND_LABEL, type ContractDetail, type SeriesDocument } from "@/lib/series";

const size = (bytes?: number | null) =>
  bytes == null ? "" : bytes > 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;

export default function DocumentsCard({
  contract, onChanged,
}: {
  contract: ContractDetail;
  onChanged: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState("AMENDMENT");
  const [busy, setBusy] = useState<number | "upload" | null>(null);

  const open = async (doc: SeriesDocument) => {
    setBusy(doc.id);
    try {
      const { data } = await api.get<Blob>(`${API_BASE}/documents/${doc.id}/file`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(null);
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy("upload");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("doc_kind", kind);
      form.append("extract", "false");
      form.append("contract_id", String(contract.id));
      await api.post(`${API_BASE}/documents`, form, { timeout: 120_000 });
      toast.success("Document saved");
      onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async (doc: SeriesDocument) => {
    if (!confirm(`Delete ${doc.file_name}? The stored file is removed as well.`)) return;
    setBusy(doc.id);
    try {
      await api.delete(`${API_BASE}/documents/${doc.id}`);
      onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
        <p className="text-xs font-bold text-gray-800 uppercase tracking-wide">Documents</p>
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          className="ml-auto border border-gray-200 rounded-lg px-2 py-1 text-[11px] bg-gray-50">
          {Object.entries(DOCUMENT_KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <button onClick={() => inputRef.current?.click()} disabled={busy === "upload"}
          className="flex items-center gap-1 text-[11px] font-semibold text-[#1e3a5f] hover:bg-gray-50 px-2 py-1 rounded-lg disabled:opacity-50">
          {busy === "upload" ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />} Add PDF
        </button>
        <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden"
          onChange={(e) => upload(e.target.files?.[0])} />
      </div>
      {contract.documents.length === 0 ? (
        <p className="text-xs text-gray-400 px-4 py-5">
          No documents yet. Keep the signed agreement, amendments and name lists here.
        </p>
      ) : (
        <ul className="divide-y divide-gray-50">
          {contract.documents.map((d) => (
            <li key={d.id} className="flex items-center gap-2.5 px-4 py-2">
              <FileText className="w-4 h-4 text-red-400 shrink-0" />
              <button onClick={() => open(d)} className="min-w-0 flex-1 text-left">
                <span className="block text-[12px] font-semibold text-gray-800 truncate hover:underline">{d.file_name}</span>
                <span className="block text-[10px] text-gray-400">
                  {[DOCUMENT_KIND_LABEL[d.doc_kind] ?? d.doc_kind, size(d.file_size),
                    d.page_count ? `${d.page_count} pages` : null,
                    d.extraction_status === "done" ? "read by AI" : null,
                    d.created_at ? d.created_at.slice(0, 10) : null,
                    d.stored_remotely ? null : "stored on server disk"].filter(Boolean).join(" · ")}
                </span>
              </button>
              {busy === d.id && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-300" />}
              <button onClick={() => remove(d)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete document">
                <Trash2 className="w-3.5 h-3.5 text-red-400" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
