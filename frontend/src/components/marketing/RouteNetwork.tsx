/**
 * A stylised route network: hubs ping, dashes march down each leg, and aircraft fly the
 * legs end to end. Decorative — the geometry is a sketch of a long-haul map, not real
 * geography, so the whole thing is hidden from the accessibility tree.
 *
 * No client JS: the dashes are a CSS animation and the aircraft ride SMIL `animateMotion`,
 * which is the same pattern the hero and the auth panel already use. SMIL ignores CSS
 * animation properties, so the `.smil-motion` wrapper is what lets `prefers-reduced-motion`
 * take the aircraft out while the routes themselves stay drawn.
 */

const HUBS = [
  { id: "JFK", x: 72, y: 124 },
  { id: "LHR", x: 258, y: 58 },
  { id: "DXB", x: 498, y: 116 },
  { id: "DEL", x: 648, y: 62 },
  { id: "SIN", x: 806, y: 150 },
  { id: "SYD", x: 960, y: 96 },
];

/** Each leg carries one aircraft; `dur` is staggered so they never fly in lockstep. */
const LEGS = [
  { d: "M648 62 Q574 58 498 116", dur: "7s", begin: "0s" },
  { d: "M498 116 Q378 34 258 58", dur: "9s", begin: "1.4s" },
  { d: "M258 58 Q166 56 72 124", dur: "8s", begin: "3.1s" },
  { d: "M648 62 Q742 82 806 150", dur: "6.5s", begin: "0.7s" },
  { d: "M806 150 Q892 158 960 96", dur: "5.5s", begin: "2.2s" },
  // two long-haul legs crossing the chain, so it reads as a network and not a relay
  { d: "M648 62 Q450 12 258 58", dur: "11s", begin: "2.8s" },
  { d: "M498 116 Q650 172 806 150", dur: "8.5s", begin: "4.3s" },
];

export default function RouteNetwork() {
  return (
    <svg
      viewBox="0 0 1030 190"
      className="h-full w-full"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      role="presentation"
    >
      <defs>
        <linearGradient id="leg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#3a80c6" stopOpacity="0.15" />
          <stop offset="50%" stopColor="#3a80c6" stopOpacity="0.75" />
          <stop offset="100%" stopColor="#3a80c6" stopOpacity="0.15" />
        </linearGradient>
        <radialGradient id="hubGlow">
          <stop offset="0%" stopColor="#3a80c6" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#3a80c6" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* legs — a solid ghost under a marching dashed line */}
      {LEGS.map((l, i) => (
        <g key={l.d}>
          <path d={l.d} fill="none" stroke="url(#leg)" strokeWidth="1.8" strokeLinecap="round" />
          <path
            d={l.d}
            fill="none"
            stroke="#3a80c6"
            strokeOpacity="0.6"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeDasharray="2 12"
            className="animate-route-flow"
            style={{ animationDelay: `${i * 0.3}s` }}
          />
        </g>
      ))}

      {/* hubs */}
      {HUBS.map((h, i) => (
        <g key={h.id}>
          <circle cx={h.x} cy={h.y} r="26" fill="url(#hubGlow)" />
          <circle
            cx={h.x}
            cy={h.y}
            r="5"
            fill="none"
            stroke="#3a80c6"
            strokeWidth="1.2"
            className="animate-hub"
            style={{
              transformBox: "view-box",
              transformOrigin: `${h.x}px ${h.y}px`,
              animationDelay: `${i * 0.5}s`,
            }}
          />
          <circle cx={h.x} cy={h.y} r="3.4" fill="#2466a8" />
          <circle cx={h.x} cy={h.y} r="1.4" fill="#ffffff" fillOpacity="0.9" />
          <text
            x={h.x}
            y={h.y - 14}
            textAnchor="middle"
            className="fill-brand-800 font-mono text-[11px] font-bold"
            style={{ letterSpacing: "0.08em" }}
          >
            {h.id}
          </text>
        </g>
      ))}

      {/* aircraft */}
      {LEGS.map((l) => (
        <g key={`p-${l.d}`} className="smil-motion">
          <path d="M0 -4 L3.6 3 L0 1.4 L-3.6 3 Z" fill="#f29a33" transform="rotate(90)" />
          <animateMotion
            dur={l.dur}
            begin={l.begin}
            repeatCount="indefinite"
            rotate="auto"
            path={l.d}
            keyPoints="0;1"
            keyTimes="0;1"
            calcMode="spline"
            keySplines="0.4 0 0.6 1"
          />
        </g>
      ))}
    </svg>
  );
}
