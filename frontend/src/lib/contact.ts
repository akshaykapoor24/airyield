/**
 * Where enquiries land.
 *
 * This lives in its own plain module rather than inside ContactModal because the modal is
 * a Client Component. A non-component export crossing the `"use client"` boundary into a
 * Server Component arrives as a client-reference proxy, not as the string — interpolating
 * it into a `mailto:` href server-side silently produces the text of an internal error
 * function instead of the address. A shared module has no boundary to cross, so both
 * sides get the same value.
 *
 * Swap this for the real inbox before launch.
 */
export const CONTACT_EMAIL = "hello@fareqube.com";
