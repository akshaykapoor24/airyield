import Logo from "./Logo";

/**
 * The hero artwork: the five things the platform joins up, wired back to one core.
 *
 * Lines are drawn in one SVG and the labels are real HTML on top, rather than SVG <text>.
 * That keeps the labels selectable, lets them use the type scale the rest of the page
 * uses, and means they reflow at small sizes instead of scaling down into illegibility.
 * Both layers are laid out against the same VIEW box, so a node at x/W in the SVG and a
 * label at the same percentage land on exactly the same point — which only holds because
 * the card's aspect ratio matches the viewBox.
 */
const W = 640;
const H = 400;

const HUB = { x: 320, y: 232 };

const NODES = [
  { label: "Booking", x: 132, y: 141 },
  { label: "Reconciliation", x: 320, y: 112, accent: true },
  { label: "Revenue", x: 508, y: 141 },
  { label: "Payments", x: 132, y: 320 },
  { label: "Compliance", x: 508, y: 320 },
];

const pct = (v: number, total: number) => `${(v / total) * 100}%`;

export default function PlatformMap() {
  return (
    <div className="relative mx-auto aspect-[16/10] w-full max-w-[640px] overflow-hidden rounded-2xl bg-ink shadow-2xl shadow-brand-900/25">
      <p className="absolute left-5 top-4 z-10 text-[13px] font-semibold text-brand-100 sm:left-7 sm:top-6 sm:text-[15px]">
        Operational + Finance + Reporting
      </p>

      {/* Spokes. The dashes march inward, so the card reads as data arriving at the core
          rather than as a static org chart. */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="absolute inset-0 h-full w-full"
        fill="none"
        aria-hidden="true"
      >
        {NODES.map((n) => (
          <line
            key={n.label}
            x1={n.x}
            y1={n.y}
            x2={HUB.x}
            y2={HUB.y}
            stroke={n.accent ? "#d97e1c" : "#2f73b7"}
            strokeWidth="1.5"
            strokeDasharray="5 6"
            className="animate-route-flow"
          />
        ))}
      </svg>

      {/* Hub */}
      <div
        className="absolute z-10 -translate-x-1/2 -translate-y-1/2"
        style={{ left: pct(HUB.x, W), top: pct(HUB.y, H) }}
      >
        <span className="grid h-12 w-12 place-items-center rounded-full bg-white shadow-lg shadow-black/40 sm:h-[68px] sm:w-[68px]">
          <Logo variant="mark" className="h-7 w-auto sm:h-10" />
        </span>
      </div>

      {/* Labels */}
      {NODES.map((n) => (
        <span
          key={n.label}
          className={`absolute z-10 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-lg border px-2 py-1.5 text-[10px] font-medium sm:px-3.5 sm:py-2 sm:text-[12px] ${
            n.accent
              ? "border-accent-500 bg-accent-500/10 text-accent-200"
              : "border-brand-700 bg-brand-950 text-brand-100"
          }`}
          style={{ left: pct(n.x, W), top: pct(n.y, H) }}
        >
          {n.label}
        </span>
      ))}
    </div>
  );
}
