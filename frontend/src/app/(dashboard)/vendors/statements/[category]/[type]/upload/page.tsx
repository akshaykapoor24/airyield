"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { getType } from "@/lib/statements";
import StatementUploadWizard from "@/components/statements/StatementUploadWizard";

// Upload XLS as a page of its own, for the types that open it so (lib/statements.ts
// `uploadPage`) rather than as a popup over the uploads list. It sits under the Statements
// layout, so the category and type tabs stay, and the list is the back link — or the
// browser's Back — away. Back, Cancel and Done all return to it; the list reloads on arrival.
export default function StatementUploadPage() {
  const params = useParams();
  const router = useRouter();
  const categorySlug = params?.category as string;
  const typeSlug = params?.type as string;
  const type = getType(categorySlug, typeSlug);
  const listHref = `/vendors/statements/${categorySlug}/${typeSlug}`;
  const usable = !!(type?.uploadPage && type.supportsMapping && type.apiBase);

  // A type without the page uploads through its list's popup.
  useEffect(() => {
    if (!usable) router.replace(listHref);
  }, [usable, listHref, router]);

  if (!usable || !type?.apiBase) return null;
  return (
    <StatementUploadWizard
      layout="page"
      backLabel={`${type.label} uploads`}
      apiBase={type.apiBase}
      title={type.label}
      requireSupplier={type.requiresSupplier}
      doneHint={type.doneHint}
      onClose={() => router.push(listHref)}
      onDone={() => router.push(listHref)}
    />
  );
}
