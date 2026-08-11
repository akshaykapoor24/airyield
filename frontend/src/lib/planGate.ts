/**
 * "This workspace has no active plan" — a one-bit store outside React.
 *
 * The axios interceptor learns about it (402) but cannot reach the Redux store:
 * authSlice already imports `api`, so importing the store from `api.ts` would be
 * a cycle. This module imports nothing, so both sides can depend on it.
 *
 * Read it with useSyncExternalStore — the same pattern SiteNav uses to read auth
 * state without a hydration mismatch. getPlanBlockedServer must stay `false` so
 * the server render and the first client render agree.
 */

let blocked = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

/** Called by the 402 branch of the axios response interceptor. */
export function markPlanBlocked() {
  if (blocked) return;
  blocked = true;
  emit();
}

/** Called on logout and when the frozen screen re-checks and finds a live plan. */
export function clearPlanBlocked() {
  if (!blocked) return;
  blocked = false;
  emit();
}

export function subscribePlanGate(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export function getPlanBlocked() {
  return blocked;
}

export function getPlanBlockedServer() {
  return false;
}
