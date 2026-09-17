"use client";

import { useEffect, useRef } from "react";

/** What a flap leaf can show while it is still shuffling. */
const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789·→";

const SPIN_MS = 45; // how fast leaves turn over while shuffling
const BASE_MS = 360; // how long the first cell shuffles for
const STAGGER_MS = 62; // each cell to its right settles this much later

/**
 * A Solari split-flap display — the departure board in every airport.
 *
 * The settled text is what renders on the server, so the board is readable with no JS and
 * to a crawler, and `aria-label` carries it to a screen reader while the cells themselves
 * are hidden from the accessibility tree (otherwise it announces a stream of nonsense as
 * the leaves turn). On intersection the cells blank, shuffle, and settle left to right.
 *
 * All of the per-frame work writes `textContent` straight to the DOM from one shared rAF
 * loop — going through state would re-render the whole board ~22 times a second.
 */
export default function FlipText({
  text,
  delay = 0,
  className = "",
  cellClassName = "h-7 w-[1.1rem] text-[13px]",
  glyphClassName = "text-white",
}: {
  text: string;
  /** Stagger this board behind others in the same section, in ms. */
  delay?: number;
  className?: string;
  /** Size of one flap cell. */
  cellClassName?: string;
  /** Tint of the settled characters — status rows read in green or amber. */
  glyphClassName?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const cells = Array.from(root.querySelectorAll<HTMLElement>("[data-final]"));
    if (!cells.length) return;

    const reduce =
      typeof matchMedia !== "undefined" &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || typeof IntersectionObserver === "undefined") return;

    const finals = cells.map((c) => c.dataset.final ?? "");
    const settleAt = finals.map((_, i) => delay + BASE_MS + i * STAGGER_MS);
    let raf = 0;

    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        io.disconnect();

        cells.forEach((c) => {
          c.textContent = "";
          c.classList.add("animate-flap");
        });

        const start = performance.now();
        let lastTick = -1;

        const step = (now: number) => {
          const t = now - start;
          const tick = Math.floor(t / SPIN_MS);
          const turned = tick !== lastTick;
          lastTick = tick;

          let running = false;
          for (let i = 0; i < cells.length; i++) {
            const cell = cells[i];
            if (t >= settleAt[i]) {
              if (cell.textContent !== finals[i]) {
                cell.textContent = finals[i];
                cell.classList.remove("animate-flap");
              }
            } else {
              running = true;
              if (turned) cell.textContent = GLYPHS[(Math.random() * GLYPHS.length) | 0];
            }
          }
          if (running) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
      },
      { threshold: 0.35 },
    );
    io.observe(root);

    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [delay]);

  return (
    <span ref={ref} className={`inline-flex items-center gap-[2px] ${className}`} aria-label={text}>
      {[...text].map((ch, i) =>
        ch === " " ? (
          // a gap between words, not a flap — a real board leaves the housing out
          <span key={i} className="w-[0.34rem]" aria-hidden="true" />
        ) : (
          <span key={i} className={`flap-cell ${cellClassName}`} aria-hidden="true">
            <span
              data-final={ch}
              className={`flap-glyph font-mono font-bold leading-none ${glyphClassName}`}
            >
              {ch}
            </span>
          </span>
        ),
      )}
    </span>
  );
}
