import { type RefObject, useLayoutEffect } from "react";

/**
 * Pins a dropdown panel to its trigger. For panels portalled to <body> with
 * `position: fixed`, so a scrolling ancestor — a modal body, a table wrapper —
 * can't clip them.
 *
 * The panel matches the trigger's width (a `min-w-*` class still wins), opens
 * below the trigger, or above it when there's more room there, and is kept
 * inside the viewport. Written to the DOM before paint, so a panel first
 * rendered with `visibility: hidden` never flashes at the wrong spot.
 * Re-placed on scroll, on resize, and when either element changes size
 * (filtering the list, chips wrapping in the trigger).
 */
export function useAnchoredPanel(
  open: boolean,
  triggerRef: RefObject<HTMLElement | null>,
  panelRef: RefObject<HTMLElement | null>,
) {
  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!open || !trigger || !panel) return;

    const place = () => {
      const r = trigger.getBoundingClientRect();
      const gap = 8;
      panel.style.width = `${r.width}px`;
      const left = Math.max(gap, Math.min(r.left, window.innerWidth - panel.offsetWidth - gap));
      const roomBelow = window.innerHeight - r.bottom - gap;
      const roomAbove = r.top - gap;
      const up = panel.offsetHeight > roomBelow && roomAbove > roomBelow;
      panel.style.left = `${left}px`;
      panel.style.top = up ? `${Math.max(gap, r.top - panel.offsetHeight - 4)}px` : `${r.bottom + 4}px`;
      panel.style.visibility = "visible";
    };

    place();
    const ro = new ResizeObserver(place);
    ro.observe(trigger);
    ro.observe(panel);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, triggerRef, panelRef]);
}
