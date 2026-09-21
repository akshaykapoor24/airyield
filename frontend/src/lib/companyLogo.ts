"use client";

/**
 * The workspace's logo, fetched once and shared by everything that shows it.
 *
 * WHY A STORE RATHER THAN A FETCH PER COMPONENT. The logo is workspace-private, so the
 * endpoint needs the bearer token and an <img> cannot point at it: the bytes come through
 * axios and are shown from an object URL. That URL has to be created once and revoked
 * exactly once, and the sidebar, the My Profile header (and anything later) must show the
 * same one — and must all change the moment it is replaced or removed.
 *
 * Read it with useCompanyLogo(). Call refreshCompanyLogo() after an upload or a delete,
 * and clearCompanyLogo() on logout so the next person to sign in on this browser never
 * sees the previous workspace's letterhead.
 *
 * Deliberately outside Redux, like lib/planGate: this imports `api`, and authSlice already
 * imports `api`, so living in the store would be a cycle.
 */

import { useSyncExternalStore } from "react";
import api from "@/lib/api";

let url: string | null = null;
let started = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function set(next: string | null) {
  if (url === next) return;
  // Revoked before it is dropped — an object URL that nobody releases keeps its blob alive
  // for the life of the tab.
  if (url) URL.revokeObjectURL(url);
  url = next;
  emit();
}

async function load(): Promise<void> {
  try {
    const res = await api.get("/users/me/profile/logo", { responseType: "blob" });
    set(URL.createObjectURL(res.data as Blob));
  } catch {
    // 404 = none uploaded; 400 = an account with no workspace (a platform admin). Either
    // way there is nothing to show, and the caller falls back to initials.
    set(null);
  }
}

/** Re-read it from the server — after an upload or a delete. */
export function refreshCompanyLogo(): Promise<void> {
  started = true;
  return load();
}

/** Forget it — on logout. */
export function clearCompanyLogo(): void {
  started = false;
  set(null);
}

export function subscribeCompanyLogo(onChange: () => void): () => void {
  listeners.add(onChange);
  // The first reader triggers the one fetch; later ones join the value it produced.
  if (!started) {
    started = true;
    void load();
  }
  return () => {
    listeners.delete(onChange);
  };
}

export const getCompanyLogo = () => url;
/** Must stay null so the server render and the first client render agree. */
export const getCompanyLogoServer = () => null;

/** The workspace's logo as an object URL, or null when there is none. */
export function useCompanyLogo(): string | null {
  return useSyncExternalStore(subscribeCompanyLogo, getCompanyLogo, getCompanyLogoServer);
}
