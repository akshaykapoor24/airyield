import { Construction } from "lucide-react";

/**
 * Lightweight placeholder for navigation destinations that don't have a real
 * page built yet. Used by the new sidebar sections until the feature ships.
 */
export default function ComingSoon({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-1 items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md px-6">
        <div
          className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center mb-5"
          style={{ background: "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)" }}
        >
          <Construction className="w-8 h-8 text-blue-600" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-slate-500">
          {description ?? "We're building this out — check back shortly."}
        </p>
        <span className="inline-flex items-center mt-5 px-3 py-1 rounded-full text-xs font-semibold bg-orange-100 text-orange-600">
          Coming soon
        </span>
      </div>
    </div>
  );
}
