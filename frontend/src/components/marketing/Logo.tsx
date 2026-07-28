import { Send } from "lucide-react";

/**
 * FareQube wordmark + paper-plane mark.
 * `light` inverts it for use on the deep-blue brand panels.
 */
export default function Logo({
  light = false,
  tagline,
  className = "",
}: {
  light?: boolean;
  tagline?: string;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div
        className={`relative grid h-9 w-9 place-items-center rounded-xl shadow-md ${
          light ? "bg-white/15 ring-1 ring-white/25" : "shadow-blue-500/25"
        }`}
        style={light ? undefined : { background: "var(--brand-grad)" }}
      >
        <Send className="h-[18px] w-[18px] -translate-x-px translate-y-px text-white" />
      </div>
      <div className="leading-none">
        <span className="text-lg font-bold tracking-tight">
          <span className={light ? "text-white" : "text-slate-900"}>Fare</span>
          <span className={light ? "text-orange-400" : "text-orange-500"}>Qube</span>
        </span>
        {tagline && (
          <p className={`mt-1 text-[11px] ${light ? "text-blue-200" : "text-slate-400"}`}>
            {tagline}
          </p>
        )}
      </div>
    </div>
  );
}
