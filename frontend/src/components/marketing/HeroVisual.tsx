import { Check, Plane, ShieldCheck, TrendingUp } from "lucide-react";

const ROWS = [
  { code: "071", iata: "ET", name: "Ethiopian",  amount: "44,20,412" },
  { code: "157", iata: "QR", name: "Qatar",      amount: "22,13,601" },
  { code: "176", iata: "EK", name: "Emirates",   amount: "46,54,961" },
  { code: "098", iata: "AI", name: "Air India",  amount: "1,24,93,977" },
];

/**
 * Decorative hero artwork: a BSP statement reconciling to zero variance,
 * styled as a boarding pass. Pure CSS animation, no client JS — the numbers
 * are illustrative, not live data.
 */
export default function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-[440px]" aria-hidden="true">
      {/* glow behind the card */}
      <div className="animate-aurora absolute -inset-8 rounded-[3rem] bg-gradient-to-tr from-blue-400/25 via-sky-300/20 to-orange-300/20 blur-3xl" />

      <div className="animate-float-slow relative">
        <div className="animate-scale-in overflow-hidden rounded-[26px] border border-white/60 bg-white shadow-2xl shadow-blue-900/20 ring-1 ring-slate-900/5">
          {/* ── Boarding-pass header ─────────────────────────────────── */}
          <div
            className="relative overflow-hidden px-5 pt-5 pb-14"
            style={{ background: "var(--brand-deep)" }}
          >
            <div className="relative z-10 flex items-start justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-200">
                  BSP Statement
                </p>
                <p className="mt-1 text-[15px] font-bold text-white">14-3 0950 3</p>
                <p className="mt-0.5 text-[11px] text-blue-200/80">
                  01 Jul → 07 Jul 2026
                </p>
              </div>

              <span className="relative inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-2.5 py-1 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-400/30">
                <span className="relative grid h-1.5 w-1.5 place-items-center">
                  <span className="animate-pulse-ring absolute inset-0 rounded-full bg-emerald-400" />
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                </span>
                Reconciled
              </span>
            </div>

            {/* route + flight path */}
            <div className="relative z-10 mt-5 flex items-end justify-between">
              <div>
                <p className="text-2xl font-bold leading-none text-white">DEL</p>
                <p className="mt-1 text-[10px] text-blue-200/70">Delhi</p>
              </div>
              <div className="mx-3 flex-1">
                <svg viewBox="0 0 200 46" className="h-11 w-full overflow-visible">
                  {/* dashes march along the route */}
                  <path
                    d="M4 38 Q 100 -12 196 30"
                    fill="none"
                    stroke="rgba(191,219,254,0.5)"
                    strokeWidth="1.5"
                    strokeDasharray="5 5"
                    strokeLinecap="round"
                    className="animate-draw"
                  />
                  {/* plane follows the same curve — `path` inline avoids <mpath href> quirks */}
                  <g className="smil-motion">
                    <path
                      d="M0 -4.5 L4.2 3.4 L0 1.6 L-4.2 3.4 Z"
                      fill="#fdba74"
                      transform="rotate(90)"
                    />
                    <animateMotion
                      dur="3.6s"
                      repeatCount="indefinite"
                      rotate="auto"
                      path="M4 38 Q 100 -12 196 30"
                      calcMode="spline"
                      keyPoints="0;1"
                      keyTimes="0;1"
                      keySplines="0.45 0 0.55 1"
                    />
                  </g>
                </svg>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold leading-none text-white">DXB</p>
                <p className="mt-1 text-[10px] text-blue-200/70">Dubai</p>
              </div>
            </div>

            {/* soft light sweep */}
            <div className="animate-shimmer pointer-events-none absolute inset-0 bg-[linear-gradient(105deg,transparent_35%,rgba(255,255,255,0.13)_50%,transparent_65%)] bg-[length:220%_100%]" />
          </div>

          {/* perforated tear line */}
          <div className="relative -mt-6 flex items-center">
            <div className="h-6 w-6 -translate-x-3 rounded-full bg-slate-50 shadow-inner" />
            <div className="flex-1 border-t-2 border-dashed border-slate-200" />
            <div className="h-6 w-6 translate-x-3 rounded-full bg-slate-50 shadow-inner" />
          </div>

          {/* ── Matched rows ─────────────────────────────────────────── */}
          <div className="relative overflow-hidden px-5 pt-2 pb-5">
            {/* scanning line */}
            <div className="animate-scan pointer-events-none absolute inset-x-5 top-0 h-14 bg-[linear-gradient(180deg,transparent,rgba(37,99,235,0.10),transparent)]" />

            <div className="mb-2 flex items-center justify-between text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              <span>Airline</span>
              <span>Uploaded = Calculated</span>
            </div>

            <ul className="space-y-1.5">
              {ROWS.map((r, i) => (
                <li
                  key={r.code}
                  className="animate-fade-up flex items-center gap-2.5 rounded-xl border border-slate-100 bg-slate-50/70 px-2.5 py-2"
                  style={{ animationDelay: `${380 + i * 130}ms` }}
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white text-[10px] font-bold text-blue-700 ring-1 ring-slate-200">
                    {r.iata}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11px] font-semibold text-slate-700">
                      {r.name}
                    </p>
                    <p className="text-[9px] text-slate-400">{r.code}</p>
                  </div>
                  <p className="font-mono text-[11px] font-semibold tabular-nums text-slate-700">
                    {r.amount}
                  </p>
                  <span
                    className="animate-scale-in grid h-5 w-5 shrink-0 place-items-center rounded-full bg-emerald-500"
                    style={{ animationDelay: `${900 + i * 130}ms` }}
                  >
                    <Check className="h-3 w-3 text-white" strokeWidth={3.5} />
                  </span>
                </li>
              ))}
            </ul>

            {/* variance footer */}
            <div
              className="animate-fade-up mt-3 flex items-center justify-between rounded-xl bg-emerald-50 px-3 py-2.5 ring-1 ring-emerald-200"
              style={{ animationDelay: "1500ms" }}
            >
              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
                <ShieldCheck className="h-3.5 w-3.5" />
                Variance
              </span>
              <span className="font-mono text-sm font-bold tabular-nums text-emerald-700">
                ₹0.00
              </span>
            </div>
          </div>
        </div>

        {/* ── Floating chips ───────────────────────────────────────── */}
        {/* Hung off the corners so they never cover a data row. */}
        <div
          className="animate-float absolute -bottom-8 -left-7 hidden rounded-2xl border border-slate-200/80 bg-white/95 px-3.5 py-2.5 shadow-xl shadow-slate-900/10 backdrop-blur sm:block"
          style={{ animationDelay: "1.2s" }}
        >
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-emerald-50 text-emerald-600">
              <TrendingUp className="h-4 w-4" />
            </span>
            <div>
              <p className="text-[9px] font-medium uppercase tracking-wider text-slate-400">
                Incentive
              </p>
              <p className="font-mono text-xs font-bold text-slate-800">+ ₹8,42,900</p>
            </div>
          </div>
        </div>

        <div
          className="animate-float absolute -right-7 -top-9 hidden rounded-2xl border border-slate-200/80 bg-white/95 px-3.5 py-2.5 shadow-xl shadow-slate-900/10 backdrop-blur sm:block"
          style={{ animationDelay: "0.4s" }}
        >
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-blue-50 text-blue-600">
              <Plane className="h-4 w-4 -rotate-45" />
            </span>
            <div>
              <p className="text-[9px] font-medium uppercase tracking-wider text-slate-400">
                Tickets matched
              </p>
              <p className="font-mono text-xs font-bold text-slate-800">15,204</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
