export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* ── Left panel — branding ─────────────────────────────────────── */}
      <div className="hidden lg:flex lg:w-[52%] flex-col justify-between p-12"
        style={{ background: "linear-gradient(135deg, #1e3a5f 0%, #0f2240 60%, #0a1628 100%)" }}>

        {/* logo */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor">
              <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
            </svg>
          </div>
          <span className="text-white font-bold text-lg tracking-wide">AirYield</span>
        </div>

        {/* center content */}
        <div className="space-y-6">
          <div>
            <h2 className="text-4xl font-bold text-white leading-tight">
              Airline Deal<br/>Management Platform
            </h2>
            <p className="text-blue-200 mt-3 text-sm leading-relaxed max-w-sm">
              Manage airline contracts, track incentives, calculate income, and
              streamline approvals — all in one place.
            </p>
          </div>

          {/* feature pills */}
          <div className="flex flex-wrap gap-2">
            {["Deal Tracking", "Income Calculation", "Approval Workflows", "B2B · B2C · B2E"].map(f => (
              <span key={f} className="px-3 py-1 bg-white/10 text-blue-100 rounded-full text-xs font-medium">
                {f}
              </span>
            ))}
          </div>

          {/* stats */}
          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-white/10">
            {[
              { value: "200+", label: "Airlines" },
              { value: "50K+", label: "Deals Managed" },
              { value: "99.9%", label: "Uptime" },
            ].map(s => (
              <div key={s.label}>
                <p className="text-2xl font-bold text-white">{s.value}</p>
                <p className="text-xs text-blue-300 mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="text-blue-400 text-xs">© 2026 AirYield · All rights reserved</p>
      </div>

      {/* ── Right panel — form ────────────────────────────────────────── */}
      <div className="flex-1 flex items-center justify-center p-6">
        {children}
      </div>
    </div>
  );
}
