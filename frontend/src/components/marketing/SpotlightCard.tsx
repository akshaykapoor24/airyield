"use client";

import { useRef } from "react";

const MAX_TILT = 5; // degrees — enough to feel like a surface, not a novelty

/**
 * A card that lights up under the pointer and tips very slightly towards it.
 *
 * The pointer position is pushed straight onto the element as `--mx`/`--my` custom
 * properties (`.spotlight` in globals.css paints the glow from them) and the tilt is
 * written to `style.transform` in the same handler. Nothing here goes through state: a
 * pointermove that re-rendered React would fire dozens of renders per second per card.
 *
 * Touch devices never get a pointermove, so they simply see the resting card — and the
 * transform is dropped under `prefers-reduced-motion` by the global rule in globals.css.
 */
export default function SpotlightCard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--mx", `${px * 100}%`);
    el.style.setProperty("--my", `${py * 100}%`);
    el.style.transform = `perspective(900px) rotateX(${(0.5 - py) * MAX_TILT}deg) rotateY(${
      (px - 0.5) * MAX_TILT
    }deg) translateY(-4px)`;
  };

  const onLeave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.transform = "";
  };

  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className={`spotlight relative transition-transform duration-300 ease-out ${className}`}
    >
      {children}
    </div>
  );
}
