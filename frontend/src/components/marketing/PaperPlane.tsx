/**
 * The paper dart and its dotted contrail, behind the hero copy.
 *
 * A paper plane rather than an airliner on purpose: the page is about the work getting
 * lighter, not about aviation hardware. The trail fades to nothing at the far end — a
 * stroke that simply stopped would read as a bar rather than as distance.
 *
 * Decorative, so it is out of the accessibility tree, and the drift is a CSS animation
 * that `prefers-reduced-motion` already parks globally.
 */
export default function PaperPlane({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 720 470"
      className={className}
      fill="none"
      aria-hidden="true"
      role="presentation"
    >
      <defs>
        <linearGradient id="pp-trail" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0%" stopColor="#5a97d4" stopOpacity="0.85" />
          <stop offset="55%" stopColor="#86b3e1" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#86b3e1" stopOpacity="0" />
        </linearGradient>
        {/* Light falls from the upper left, so the near wing sits in shade. */}
        <linearGradient id="pp-top" x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor="#f7fafd" />
          <stop offset="100%" stopColor="#dbe4f0" />
        </linearGradient>
        <linearGradient id="pp-near" x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0%" stopColor="#c9d7e8" />
          <stop offset="100%" stopColor="#a9bdd6" />
        </linearGradient>
      </defs>

      {/* Contrail — round caps on a near-zero dash make dots, not dashes. It runs out to
          the left of the copy rather than across it, so nothing is read through it. */}
      <path
        d="M-30 452 C 130 430, 300 372, 414 258"
        stroke="url(#pp-trail)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray="0.1 14"
      />

      {/* The drift and the placement have to live on separate groups. A CSS `transform`
          animation overrides the `transform` presentation attribute outright, so putting
          both on one <g> drops the translate and parks the dart at the origin. */}
      <g className="animate-float-slow">
        <g transform="translate(471 200) rotate(-31) scale(0.52)">
          {/* Far wing */}
          <path d="M104 -8 L-100 -52 L-16 14 Z" fill="url(#pp-top)" />
          {/* Near wing, folded down and away from the light */}
          <path d="M104 -8 L-16 14 L-56 62 Z" fill="url(#pp-near)" />
          {/* The crease between them */}
          <path d="M104 -8 L-16 14" stroke="#9fb4cd" strokeWidth="1.5" strokeLinecap="round" />
        </g>
      </g>
    </svg>
  );
}
