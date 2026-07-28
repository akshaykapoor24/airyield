"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  UploadCloud, FileText, ArrowLeft, X, CheckCircle2,
  Plane, CalendarRange, Info, Loader2,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

type AirlineOpt = { id: number; name: string; iata_code?: string };

const BRAND = "#1e3a5f";

export default function BspUploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [airlineName, setAirlineName] = useState("All");   // a BSP statement covers all airlines by default
  const [validFrom, setValidFrom] = useState("");
  const [validTo, setValidTo] = useState("");

  useEffect(() => {
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } })
      .then(r => setAirlines(r.data))
      .catch(() => setAirlines([]));
  }, []);

  const sizeLabel = useMemo(() => {
    if (!file) return "";
    const mb = file.size / (1024 * 1024);
    return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  }, [file]);

  const pickFile = (f: File | null) => {
    if (f && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Please choose a PDF file.");
      return;
    }
    setFile(f);
  };

  const submit = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("airline_name", airlineName || "All");
      if (validFrom) fd.append("period_from", validFrom);
      if (validTo) fd.append("period_to", validTo);
      const { data } = await api.post<{ batch_id: string; status: string }>("/bsp/upload", fd);
      toast.success("BSP statement uploaded — parsing started.");
      router.push(`/tickets/bsp/${data.batch_id}`);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : "Failed to upload the statement.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="w-full pb-20">
      {/* Header */}
      <div className="mb-5">
        <button onClick={() => router.push("/tickets/bsp")} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mb-3">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Repository
        </button>
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center text-white shadow-sm" style={{ backgroundColor: BRAND }}>
            <UploadCloud className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 leading-tight">Upload BSP Statement</h1>
            <p className="text-xs text-gray-500 mt-0.5">Upload an IATA BSP settlement PDF — it&apos;s parsed in the background into the BSP Repository.</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 max-w-5xl items-stretch">
        {/* Left — BSP Details */}
        <section className="lg:col-span-2 bg-white border border-gray-200 rounded-2xl shadow-sm p-6 h-full flex flex-col">
          <CardHeader icon={<Info className="w-4 h-4" />} title="BSP Details" subtitle="Tag this statement" />

          <div className="space-y-5 mt-5">
            <Field label="Airline Name">
              <div className="relative">
                <Plane className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <select
                  value={airlineName}
                  onChange={e => setAirlineName(e.target.value)}
                  className="w-full appearance-none border border-gray-200 rounded-lg pl-9 pr-8 py-2.5 text-sm bg-white text-gray-800 outline-none transition focus:border-[#1e3a5f] focus:ring-2 focus:ring-[#1e3a5f]/10"
                >
                  <option value="All">All airlines</option>
                  {airlines.map(a => (
                    <option key={a.id} value={a.name}>{a.name}{a.iata_code ? ` (${a.iata_code})` : ""}</option>
                  ))}
                </select>
                <svg className="w-4 h-4 text-gray-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" /></svg>
              </div>
              <Hint>A BSP statement usually covers every airline — leave as <b>All</b> unless it&apos;s a single-carrier file.</Hint>
            </Field>

            <div>
              <label className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 mb-1.5 uppercase tracking-wide">
                <CalendarRange className="w-3.5 h-3.5" /> Billing Validity
              </label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <input type="date" value={validFrom} onChange={e => setValidFrom(e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-[#1e3a5f] focus:ring-2 focus:ring-[#1e3a5f]/10" />
                  <p className="text-[10px] text-gray-400 mt-1 ml-0.5">Valid from</p>
                </div>
                <div>
                  <input type="date" value={validTo} onChange={e => setValidTo(e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-[#1e3a5f] focus:ring-2 focus:ring-[#1e3a5f]/10" />
                  <p className="text-[10px] text-gray-400 mt-1 ml-0.5">Valid to</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Right — Attach a BSP PDF */}
        <section className="lg:col-span-3 bg-white border border-gray-200 rounded-2xl shadow-sm p-6 h-full flex flex-col">
          <CardHeader icon={<FileText className="w-4 h-4" />} title="Attach a BSP PDF" subtitle="Drag &amp; drop or browse" />

          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files?.[0]; if (f) pickFile(f); }}
            className={`mt-5 flex-1 flex flex-col items-center justify-center rounded-xl border-2 border-dashed transition-colors p-8 text-center
              ${dragging ? "border-[#1e3a5f] bg-[#1e3a5f]/5" : file ? "border-emerald-200 bg-emerald-50/30" : "border-gray-200 bg-gray-50/50 hover:border-gray-300 hover:bg-gray-50"}`}
          >
            {file ? (
              <div className="w-full max-w-md">
                <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-white p-3 shadow-sm">
                  <div className="w-10 h-10 rounded-lg bg-red-50 border border-red-100 flex items-center justify-center shrink-0">
                    <FileText className="w-5 h-5 text-red-500" />
                  </div>
                  <div className="min-w-0 flex-1 text-left">
                    <p className="text-xs font-semibold text-gray-800 truncate" title={file.name}>{file.name}</p>
                    <p className="text-[11px] text-gray-500">{sizeLabel} · PDF</p>
                  </div>
                  <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                  <button onClick={() => setFile(null)} className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-gray-50 shrink-0" title="Remove">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <label className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-medium cursor-pointer hover:underline" style={{ color: BRAND }}>
                  <UploadCloud className="w-3.5 h-3.5" /> Choose a different file
                  <input type="file" accept=".pdf,application/pdf" className="hidden" onChange={e => pickFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>
            ) : (
              <>
                <div className="w-14 h-14 rounded-full flex items-center justify-center mb-3" style={{ backgroundColor: `${BRAND}14` }}>
                  <UploadCloud className="w-7 h-7" style={{ color: BRAND }} />
                </div>
                <p className="text-sm font-medium text-gray-700">Drop your BSP PDF here</p>
                <p className="text-xs text-gray-400 mt-0.5 mb-4">or select a file from your computer</p>
                <label className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white rounded-lg cursor-pointer shadow-sm transition hover:opacity-90" style={{ backgroundColor: BRAND }}>
                  <FileText className="w-3.5 h-3.5" /> Browse files
                  <input type="file" accept=".pdf,application/pdf" className="hidden" onChange={e => pickFile(e.target.files?.[0] ?? null)} />
                </label>
                <p className="text-[11px] text-gray-400 mt-5 max-w-xs leading-relaxed">
                  PDF only · up to 200 MB. Large statements (1,000–2,000 pages) are parsed in the background — you can keep working while they process.
                </p>
              </>
            )}
          </div>
        </section>
      </div>

      {/* Action bar */}
      <div className="mt-5 flex flex-wrap items-center gap-3 max-w-5xl">
        <button onClick={submit} disabled={!file || uploading}
          className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white rounded-lg shadow-sm transition hover:opacity-90 disabled:bg-gray-200 disabled:text-gray-400 disabled:shadow-none"
          style={!file || uploading ? undefined : { backgroundColor: BRAND }}>
          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
          {uploading ? "Uploading…" : "Upload & Parse"}
        </button>
        {!file && <span className="text-[11px] text-gray-400">Attach a PDF to continue.</span>}
        {file && !uploading && <span className="text-[11px] text-gray-400 flex items-center gap-1.5"><Info className="w-3.5 h-3.5" /> You&apos;ll see live parsing progress on the next screen.</span>}
      </div>
    </div>
  );
}

function CardHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="flex items-center gap-3 pb-4 border-b border-gray-100">
      <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: `${BRAND}14`, color: BRAND }}>
        {icon}
      </div>
      <div>
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
        <p className="text-[11px] text-gray-400">{subtitle}</p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] font-semibold text-gray-500 mb-1.5 uppercase tracking-wide">{label}</label>
      {children}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-gray-400 mt-1.5 leading-relaxed">{children}</p>;
}
