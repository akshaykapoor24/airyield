"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { getType } from "@/lib/statements";
import ComingSoon from "@/components/ui/ComingSoon";
import AdjustmentStatementsView from "@/components/statements/AdjustmentStatementsView";
import BspStatementsView from "@/components/statements/bsp/BspStatementsView";
import LccDetailedView from "@/components/statements/lcc/LccDetailedView";

export default function StatementTypePage() {
  const params = useParams();
  const categorySlug = params?.category as string;
  const typeSlug = params?.type as string;
  const type = getType(categorySlug, typeSlug);

  // Inner switch for grouped spec types (ADM/ACM/RA).
  const [variantSlug, setVariantSlug] = useState<string | null>(null);

  if (!type) {
    return <ComingSoon title="Statement" description="Unknown statement type." />;
  }

  if (type.kind === "coming-soon") {
    return <ComingSoon title={type.label} description={type.blurb ?? "This statement type is coming soon."} />;
  }

  // BSP: paired Summary + Detailed upload with grand-total reconciliation.
  if (type.kind === "bsp") {
    return <BspStatementsView />;
  }

  // LCC Detailed: mapping wizard + async ingest + progress, dedicated batch/rows schema.
  if (type.kind === "lcc-detailed" && type.apiBase) {
    return <LccDetailedView apiBase={type.apiBase} title={type.label} />;
  }

  // spec-repo with an inner variant switch (ADM/ACM/RA)
  if (type.variants && type.variants.length) {
    const active = type.variants.find((v) => v.slug === variantSlug) ?? type.variants[0];
    return (
      <div>
        <div className="flex items-center gap-1.5 mb-4">
          {type.variants.map((v) => {
            const isActive = v.slug === active.slug;
            return (
              <button
                key={v.slug}
                type="button"
                onClick={() => setVariantSlug(v.slug)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors",
                  isActive
                    ? "bg-blue-50 border-blue-300 text-blue-700"
                    : "bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                )}
              >
                {v.label}
              </button>
            );
          })}
        </div>
        <AdjustmentStatementsView
          key={active.slug}
          slug={active.slug}
          apiBase={active.apiBase}
          title={active.label}
          blurb={type.blurb ?? ""}
        />
      </div>
    );
  }

  // plain spec-repo → statement-type (batch) view
  if (!type.apiBase) {
    return <ComingSoon title={type.label} description={type.blurb ?? "Not configured yet."} />;
  }
  return (
    <AdjustmentStatementsView
      key={type.slug}
      slug={type.slug}
      apiBase={type.apiBase}
      title={type.label}
      blurb={type.blurb ?? ""}
    />
  );
}
