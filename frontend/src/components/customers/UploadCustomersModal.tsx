"use client";

import { useState } from "react";
import { Download, Upload, X } from "lucide-react";
import api from "@/lib/api";

type BulkResult = { total: number; success: number; failed: number; errors: string[] };

export default function UploadCustomersModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BulkResult | null>(null);

  const handleTemplateDownload = async () => {
    setError("");
    try {
      const res = await api.get("/customers/template", { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "customer_template.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      setError("Template download failed.");
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError("Please select a file.");
      return;
    }
    setUploading(true);
    setError("");
    setResult(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const { data } = await api.post<BulkResult>("/customers/bulk-upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(data);
      if (data.success > 0) onSaved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Upload className="w-4 h-4 text-[#1e3a5f]" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">Import Customers</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-[#1e3a5f]">Download Excel Template</p>
              <p className="text-[10px] text-blue-500 mt-0.5">
                Columns: FIRST_NAME, LAST_NAME, COMPANY, TITLE, PHONE, EMAIL, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency)
              </p>
            </div>
            <button
              type="button"
              onClick={handleTemplateDownload}
              className="flex items-center gap-1 text-[#1e3a5f] hover:opacity-80 text-xs font-medium whitespace-nowrap ml-3"
            >
              <Download className="w-3.5 h-3.5" /> Template
            </button>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Select XLS / XLSX File</label>
            <input
              type="file"
              accept=".xls,.xlsx"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setResult(null);
                setError("");
              }}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-blue-50 file:text-[#1e3a5f] file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none"
            />
          </div>

          {result && (
            <div
              className={`rounded-lg border px-3 py-2.5 text-xs space-y-1 ${
                result.failed > 0 ? "bg-yellow-50 border-yellow-200" : "bg-green-50 border-green-200"
              }`}
            >
              <p className="font-semibold">
                Upload complete — {result.success} of {result.total} rows added
              </p>
              {result.errors.slice(0, 5).map((e, i) => (
                <p key={i} className="text-[10px] text-red-500">{e}</p>
              ))}
              {result.errors.length > 5 && (
                <p className="text-[10px] text-gray-400">…and {result.errors.length - 5} more errors</p>
              )}
            </div>
          )}

          {error && <p className="text-[11px] text-red-500">{error}</p>}
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={handleUpload}
              disabled={uploading || !file}
              className="flex-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            >
              {uploading ? "Uploading…" : "Upload & Import"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
