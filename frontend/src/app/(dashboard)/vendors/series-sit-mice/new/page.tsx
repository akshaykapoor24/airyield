"use client";

/**
 * Upload a contract PDF, let the AI read it, review it beside the document, save it.
 *
 * The PDF is stored (GCS) the moment it is uploaded, whether or not the reading works, so
 * nothing a person uploads is lost to an AI failure — they can retry, or fill the form by
 * hand with the document still linked. The reading takes up to a couple of minutes for a
 * photographed contract; the server posts a notification when it is done, and the link in
 * it (`?document=<id>`) reopens this page straight at the review without reading again.
 *
 * `useSearchParams` is inside a Suspense boundary, as this version of Next requires for a
 * prerendered route — see node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import {
  AlertTriangle, ArrowLeft, ExternalLink, FileText, Loader2, PencilLine, RefreshCw, Sparkles,
} from "lucide-react";

import api from "@/lib/api";
import { apiError } from "@/components/userMaster/shared";
import Dropzone from "@/components/statements/Dropzone";
import ContractWizard from "@/components/vendors/series/ContractWizard";
import { API_BASE, type ExtractionDraft, type ExtractionResponse, type SeriesDocument } from "@/lib/series";

type Phase = "upload" | "reading" | "review" | "failed" | "loading";

export default function NewContractPage() {
  return (
    <Suspense fallback={<Centered><Loader2 className="w-4 h-4 animate-spin text-gray-300" /></Centered>}>
      <NewContract />
    </Suspense>
  );
}

function NewContract() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("document");

  const [phase, setPhase] = useState<Phase>(resumeId ? "loading" : "upload");
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<SeriesDocument | null>(null);
  const [draft, setDraft] = useState<ExtractionDraft | null>(null);
  const [duplicate, setDuplicate] = useState<SeriesDocument | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [elapsed, setElapsed] = useState(0);
  const [failure, setFailure] = useState("");
  const [manual, setManual] = useState(false);
  const urlRef = useRef<string | null>(null);
  // The document already on screen. After an upload the URL is rewritten to
  // ?document=<id> so a refresh resumes; this stops that rewrite reloading it.
  const loadedRef = useRef<string | null>(null);

  const showPdf = useCallback((blob: Blob) => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    setPdfUrl(url);
  }, []);

  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current); }, []);

  // The seconds counter while the AI reads — a photographed contract takes a while and a
  // frozen spinner reads as a hang.
  useEffect(() => {
    if (phase !== "reading") return;
    setElapsed(0);
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  const accept = (data: ExtractionResponse) => {
    loadedRef.current = String(data.document.id);
    setDoc(data.document);
    setDuplicate(data.duplicate_of ?? null);
    if (data.draft) {
      setDraft(data.draft);
      setPhase("review");
      const serious = data.draft.warnings.filter((w) => w.level !== "info").length;
      toast.success(serious ? `Contract read — ${serious} item${serious !== 1 ? "s" : ""} to check` : "Contract read");
    } else {
      setFailure(data.document.extraction_error || "The document could not be read.");
      setPhase("failed");
    }
  };

  // Resume from a notification or the Uploaded documents list.
  useEffect(() => {
    if (!resumeId || loadedRef.current === resumeId) return;
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get<ExtractionResponse>(`${API_BASE}/documents/${resumeId}`);
        if (cancelled) return;
        if (data.document.contract_id) {
          toast("This document has already been saved as a contract.");
          router.replace(`/vendors/series-sit-mice/${data.document.contract_id}`);
          return;
        }
        const blob = await api.get<Blob>(`${API_BASE}/documents/${resumeId}/file`, { responseType: "blob" });
        if (cancelled) return;
        showPdf(blob.data);
        if (data.document.extraction_status === "processing") {
          setDoc(data.document);
          setFailure("This document is still being read, or the reading was interrupted. Read it again to continue.");
          setPhase("failed");
          return;
        }
        accept(data);
      } catch (e) {
        if (!cancelled) {
          toast.error(apiError(e));
          setPhase("upload");
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]);

  const upload = async () => {
    if (!file) return;
    showPdf(file);
    setPhase("reading");
    setFailure("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("extract", "true");
      const { data } = await api.post<ExtractionResponse>(`${API_BASE}/documents`, form, { timeout: 300_000 });
      accept(data);
      // Keep the URL resumable: a refresh now reopens this review instead of an empty upload.
      router.replace(`/vendors/series-sit-mice/new?document=${data.document.id}`, { scroll: false });
    } catch (e) {
      setFailure(apiError(e));
      setPhase(doc ? "failed" : "upload");
      toast.error(apiError(e), { duration: 6000 });
    }
  };

  const retry = async () => {
    if (!doc) return;
    setPhase("reading");
    try {
      const { data } = await api.post<ExtractionResponse>(`${API_BASE}/documents/${doc.id}/extract`, null, { timeout: 300_000 });
      accept(data);
    } catch (e) {
      setFailure(apiError(e));
      setPhase("failed");
    }
  };

  const fillByHand = () => { setManual(true); setDraft(null); setPhase("review"); };

  const back = () => router.push("/vendors/series-sit-mice");

  // ── Upload ──────────────────────────────────────────────────────────────────
  if (phase === "loading") {
    return <Centered><Loader2 className="w-4 h-4 animate-spin text-gray-300 mx-auto mb-2" /> Opening the document…</Centered>;
  }

  if (phase === "upload") {
    return (
      <div className="space-y-4 max-w-3xl">
        <PageTitle onBack={back} title="Upload a contract" />
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-4">
          <Dropzone
            file={file}
            onPick={setFile}
            accept="pdf"
            label="Group / series / SIT / MICE contract"
            note="Airline group sales agreement, group quotation, or a B2B supplier's group offer. Scans and phone photos are fine."
          />
          <div className="grid sm:grid-cols-2 gap-3 text-[11px] text-gray-600">
            <div className="rounded-lg bg-gray-50 px-3 py-2.5">
              <p className="font-semibold text-gray-800 mb-1 flex items-center gap-1">
                <Sparkles className="w-3.5 h-3.5 text-violet-600" /> What gets read
              </p>
              Contract type and references · departures and flights · fare per passenger ·
              deposits and payment dates · name-list, ticketing and no-show deadlines ·
              cancellation bands, seat-release, name-change and deviation charges · passenger list.
            </div>
            <div className="rounded-lg bg-gray-50 px-3 py-2.5">
              <p className="font-semibold text-gray-800 mb-1">Nothing is saved until you review it</p>
              The PDF is stored securely against the contract. Every value the AI fills shows the
              page it came from, and anything it was unsure of is listed for you to check.
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={upload}
              disabled={!file}
              className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" /> Upload and read
            </button>
            <button onClick={fillByHand} className="ml-auto text-xs font-semibold text-gray-500 hover:text-gray-700 px-3 py-2">
              Enter by hand instead
            </button>
          </div>
          {failure && <p className="text-xs text-red-500">{failure}</p>}
        </div>
      </div>
    );
  }

  // ── Reading / failed / review: document on the left ───────────────────────
  return (
    <div className="space-y-3">
      <PageTitle
        onBack={back}
        title={phase === "review" ? (manual ? "Enter the contract" : "Review and save") : "Reading the contract"}
        sub={doc?.file_name}
      />

      {duplicate && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          This exact file was uploaded before
          {duplicate.contract_id ? (
            <>
              {" "}and saved as a contract.
              <Link href={`/vendors/series-sit-mice/${duplicate.contract_id}`} className="font-semibold underline ml-1">
                Open that contract
              </Link>
            </>
          ) : " but not saved as a contract yet."}
        </div>
      )}

      <div className={`grid gap-3 lg:h-[calc(100vh-170px)] ${pdfUrl ? "lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" : ""}`}>
        {pdfUrl && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm flex flex-col min-h-[480px] overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
            <FileText className="w-3.5 h-3.5 text-gray-400" />
            <p className="text-[11px] font-semibold text-gray-700 truncate">{doc?.file_name ?? file?.name}</p>
            {doc?.page_count ? (
              <span className="text-[10px] text-gray-400">
                {doc.page_count} page{doc.page_count !== 1 ? "s" : ""}
                {doc.scanned_pages ? ` · ${doc.scanned_pages} scanned` : ""}
              </span>
            ) : null}
            {pdfUrl && (
              <a href={pdfUrl} target="_blank" rel="noreferrer" className="ml-auto p-1 hover:bg-gray-50 rounded" title="Open in a new tab">
                <ExternalLink className="w-3.5 h-3.5 text-gray-400" />
              </a>
            )}
          </div>
          {/* Re-keyed on the page so a click on a "p.3" badge actually moves the viewer. */}
          <iframe key={page} src={`${pdfUrl}#page=${page}&view=FitH`} title="Contract PDF" className="flex-1 w-full" />
        </div>
        )}

        <div className="min-h-0">
          {phase === "reading" && (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm h-full grid place-items-center p-8 text-center">
              <div>
                <Loader2 className="w-6 h-6 animate-spin text-violet-500 mx-auto mb-3" />
                <p className="text-sm font-semibold text-gray-800">Reading the contract… {elapsed}s</p>
                <p className="text-xs text-gray-500 mt-1 max-w-sm">
                  Scanned and photographed pages take one to two minutes. The PDF is already saved.
                </p>
                {elapsed > 20 && (
                  <p className="text-[11px] text-gray-400 mt-3 max-w-sm">
                    You can leave this page — you&apos;ll get a notification in the bell when it&apos;s
                    ready to review.
                  </p>
                )}
              </div>
            </div>
          )}

          {phase === "failed" && (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm h-full grid place-items-center p-8 text-center">
              <div className="max-w-md">
                <AlertTriangle className="w-6 h-6 text-amber-500 mx-auto mb-3" />
                <p className="text-sm font-semibold text-gray-800">The contract could not be read automatically</p>
                <p className="text-xs text-gray-500 mt-1">{failure}</p>
                <div className="flex items-center justify-center gap-2 mt-4">
                  <button onClick={retry} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                    <RefreshCw className="w-3.5 h-3.5" /> Read again
                  </button>
                  <button onClick={fillByHand} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                    <PencilLine className="w-3.5 h-3.5" /> Fill in by hand
                  </button>
                </div>
              </div>
            </div>
          )}

          {phase === "review" && (
            <ContractWizard
              layout="page"
              seed={manual ? null : draft}
              documentId={doc?.id ?? null}
              onJump={setPage}
              onClose={back}
              onSaved={(id) => router.push(`/vendors/series-sit-mice/${id}`)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function PageTitle({ title, sub, onBack }: { title: string; sub?: string | null; onBack: () => void }) {
  return (
    <div>
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-1 hover:text-gray-600"
      >
        <ArrowLeft className="w-3 h-3" /> Series / SIT / MICE / Group
      </button>
      <h1 className="text-xl font-bold text-gray-900">{title}</h1>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="py-24 text-center text-xs text-gray-400">{children}</div>;
}
