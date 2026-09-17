import type { CSSProperties } from "react";

/**
 * The backdrop for the auth brand panel.
 *
 * Two layers, both edgeless. Underneath, three wide colour fields drifting slowly past one
 * another. Over them, motes of light rising the height of the panel — the tagline the panel
 * is carrying, read literally.
 *
 * Nothing here draws a line. Two earlier attempts did: full-height flight legs, then a
 * single arc. At panel scale a stroke over body copy reads as a scratch across the text no
 * matter how faint it is, so the motion behind the copy is now entirely soft-edged.
 *
 * No client JS, and every animation is CSS, so `prefers-reduced-motion` stops all of it
 * through the global rule in globals.css.
 */

type Mote = {
  /** Horizontal start, as a percentage across the panel. */
  left: string;
  /** Diameter in px. */
  size: number;
  /** Seconds for a full ascent. */
  dur: number;
  /** Negative, so the panel already has motes in flight on first paint. */
  delay: number;
  /** Sideways drift over the ascent. */
  dx: string;
  opacity: number;
};

const MOTES: Mote[] = [
  { left: "6%", size: 5, dur: 26, delay: -3, dx: "5%", opacity: 0.5 },
  { left: "17%", size: 9, dur: 38, delay: -19, dx: "-4%", opacity: 0.3 },
  { left: "27%", size: 4, dur: 22, delay: -11, dx: "7%", opacity: 0.55 },
  { left: "36%", size: 14, dur: 46, delay: -31, dx: "6%", opacity: 0.16 },
  { left: "45%", size: 6, dur: 30, delay: -7, dx: "-6%", opacity: 0.42 },
  { left: "55%", size: 4, dur: 24, delay: -17, dx: "4%", opacity: 0.5 },
  { left: "63%", size: 11, dur: 42, delay: -26, dx: "-5%", opacity: 0.22 },
  { left: "72%", size: 5, dur: 28, delay: -2, dx: "6%", opacity: 0.45 },
  { left: "81%", size: 8, dur: 35, delay: -22, dx: "-3%", opacity: 0.3 },
  { left: "90%", size: 4, dur: 21, delay: -13, dx: "5%", opacity: 0.5 },
  { left: "12%", size: 7, dur: 33, delay: -28, dx: "-5%", opacity: 0.34 },
  { left: "50%", size: 18, dur: 52, delay: -40, dx: "8%", opacity: 0.12 },
  { left: "86%", size: 12, dur: 44, delay: -9, dx: "-7%", opacity: 0.18 },
  { left: "33%", size: 5, dur: 27, delay: -24, dx: "-4%", opacity: 0.44 },
];

export default function PanelBackdrop() {
  return (
    <>
      {/* drifting colour fields */}
      <div className="animate-drift-a absolute -left-[30%] -top-[15%] h-[70%] w-[95%] rounded-full bg-brand-400/40 blur-[90px]" />
      <div className="animate-drift-b absolute -right-[25%] top-[12%] h-[62%] w-[85%] rounded-full bg-brand-300/28 blur-[100px]" />
      <div className="animate-drift-c absolute -bottom-[18%] left-[5%] h-[58%] w-[80%] rounded-full bg-accent-500/18 blur-[110px]" />

      {/* rising motes */}
      {MOTES.map((m) => (
        <span
          key={`${m.left}-${m.size}-${m.dur}`}
          className="animate-ascend absolute -bottom-8 rounded-full bg-white"
          style={
            {
              left: m.left,
              width: m.size,
              height: m.size,
              opacity: m.opacity,
              filter: `blur(${m.size > 10 ? 4 : 1.2}px)`,
              animationDuration: `${m.dur}s`,
              animationDelay: `${m.delay}s`,
              "--dx": m.dx,
            } as CSSProperties
          }
        />
      ))}
    </>
  );
}
