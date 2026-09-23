"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Check, Mail, X } from "lucide-react";
import { CONTACT_EMAIL } from "@/lib/contact";

// The form composes a `mailto:` in the visitor's own mail client rather than posting
// anywhere — there is no contact endpoint on the API, and this way nothing is stored,
// nothing needs a spam guard, and the sender keeps a copy in their own Sent folder.
// The address itself lives in lib/contact so the server page can read it too.

/** Dial codes for the markets the product sells into, India first. */
const DIAL_CODES = ["+91", "+971", "+44", "+1", "+65", "+61", "+966", "+254", "+27"];

/** Broadcast channel between the triggers and the single mounted dialog. */
const OPEN_EVENT = "fareqube:contact";

/**
 * Opens the contact dialog from anywhere on the page, including from inside other
 * client components such as the header.
 */
export function openContact() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

/**
 * A trigger for the contact dialog that is usable from a server component — which is why
 * the open state travels as a DOM event rather than through context or props. The page
 * mounts exactly one <ContactModal />; every button on it simply shouts.
 */
export function ContactButton({
  children,
  className = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  /** For the brand gradient, which is a CSS variable rather than a utility. */
  style?: React.CSSProperties;
}) {
  return (
    <button type="button" onClick={openContact} className={className} style={style}>
      {children}
    </button>
  );
}

// Width is deliberately NOT baked in here. Between `w-full` and `w-[92px]` on the same
// element it is stylesheet order, not class order, that wins — so the dial-code select
// would inherit a full-width rule it cannot override, and shove the number field out of
// the card. Each field states its own width instead.
const FIELD_BASE =
  "rounded-lg border border-line bg-paper px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-brand-500 focus:bg-white";
const FIELD = `w-full ${FIELD_BASE}`;
const LABEL = "mb-1.5 block text-[13px] font-medium text-slate-600";

export default function ContactModal() {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  // Whatever had focus when the dialog opened, so it can be handed back on close.
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const uid = useId();

  const close = useCallback(() => {
    setOpen(false);
    // Reset to the form, so a later visit never opens on the previous confirmation.
    setSent(false);
  }, []);

  useEffect(() => {
    const onOpen = () => {
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      setOpen(true);
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  // Esc closes, the page behind stops scrolling, and focus starts in the first field.
  useEffect(() => {
    if (!open) {
      returnFocusRef.current?.focus();
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstFieldRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, close]);

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const get = (k: string) => String(data.get(k) ?? "").trim();

    const company = get("company");
    const phone = [get("dial"), get("phone")].filter(Boolean).join(" ");

    const subject = company ? `fareqube enquiry — ${company}` : "fareqube enquiry";
    const body = [
      `Name: ${get("name")}`,
      company && `Company: ${company}`,
      `Email: ${get("email")}`,
      get("phone") && `Phone: ${phone}`,
      "",
      get("message"),
    ]
      .filter(Boolean)
      .join("\n");

    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(
      subject,
    )}&body=${encodeURIComponent(body)}`;
    setSent(true);
  };

  if (!open) return null;

  return (
    <div
      className="animate-fade-in fixed inset-0 z-[100] flex items-center justify-center p-5"
      style={{ background: "rgba(13, 46, 91, 0.55)" }}
      // A press that starts on the backdrop closes the dialog; one that merely ends there,
      // after dragging a selection out of a text field, does not.
      onMouseDown={(e) => {
        if (!cardRef.current?.contains(e.target as Node)) close();
      }}
    >
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
        className="animate-scale-in relative max-h-[90vh] w-full max-w-[480px] overflow-y-auto rounded-2xl bg-white p-7 shadow-2xl shadow-brand-900/40 sm:p-8"
      >
        <button
          type="button"
          onClick={close}
          aria-label="Close"
          className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>

        {sent ? (
          <div className="py-8 text-center">
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200">
              <Check className="h-7 w-7" strokeWidth={2.5} />
            </span>
            <h3 id={`${uid}-title`} className="display mt-5 text-xl font-semibold text-brand-900">
              Your mail app is open
            </h3>
            <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-slate-500">
              We&rsquo;ve filled in the details — send the draft and we&rsquo;ll reply within
              one working day. If nothing opened, write to{" "}
              <a
                href={`mailto:${CONTACT_EMAIL}`}
                className="font-semibold text-brand-700 hover:text-brand-800"
              >
                {CONTACT_EMAIL}
              </a>
              .
            </p>
            <button
              type="button"
              onClick={close}
              className="mt-6 rounded-lg border border-line px-5 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
            >
              Done
            </button>
          </div>
        ) : (
          <>
            <span className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-brand-700">
              <Mail className="h-3.5 w-3.5" />
              Contact
            </span>
            <h3
              id={`${uid}-title`}
              className="display mt-3.5 text-[22px] font-semibold text-brand-900"
            >
              Let&rsquo;s look at your statements
            </h3>
            <p className="mt-1.5 text-sm text-slate-500">
              Tell us what you settle on and we&rsquo;ll show you the reconciliation on your
              own file.
            </p>

            <form onSubmit={onSubmit} className="mt-6">
              <div className="flex flex-col gap-3.5 sm:flex-row">
                <div className="flex-1">
                  <label className={LABEL} htmlFor={`${uid}-name`}>
                    Name
                  </label>
                  <input
                    ref={firstFieldRef}
                    id={`${uid}-name`}
                    name="name"
                    required
                    autoComplete="name"
                    className={FIELD}
                    placeholder="Your name"
                  />
                </div>
                <div className="flex-1">
                  <label className={LABEL} htmlFor={`${uid}-company`}>
                    Company
                  </label>
                  <input
                    id={`${uid}-company`}
                    name="company"
                    autoComplete="organization"
                    className={FIELD}
                    placeholder="Agency name"
                  />
                </div>
              </div>

              <div className="mt-3.5">
                <label className={LABEL} htmlFor={`${uid}-email`}>
                  Work email
                </label>
                <input
                  id={`${uid}-email`}
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  className={FIELD}
                  placeholder="you@agency.com"
                />
              </div>

              <div className="mt-3.5">
                <label className={LABEL} htmlFor={`${uid}-phone`}>
                  Phone <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <div className="flex gap-2">
                  <select
                    name="dial"
                    aria-label="Country dialling code"
                    defaultValue="+91"
                    className={`${FIELD_BASE} w-[92px] shrink-0`}
                  >
                    {DIAL_CODES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <input
                    id={`${uid}-phone`}
                    name="phone"
                    type="tel"
                    autoComplete="tel-national"
                    className={`${FIELD_BASE} min-w-0 flex-1`}
                    placeholder="98765 43210"
                  />
                </div>
              </div>

              <div className="mt-3.5">
                <label className={LABEL} htmlFor={`${uid}-message`}>
                  What can we help with?
                </label>
                <textarea
                  id={`${uid}-message`}
                  name="message"
                  rows={3}
                  className={`${FIELD} min-h-[84px] resize-y`}
                  placeholder="Your BSP volume, the carriers you hold deals with, what breaks today…"
                />
              </div>

              <button
                type="submit"
                className="btn-sheen mt-5 w-full rounded-xl px-6 py-3 text-[15px] font-semibold text-white shadow-lg shadow-brand-700/25 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brand-700/30"
                style={{ background: "var(--brand-grad)" }}
              >
                Send enquiry
              </button>
              <p className="mt-3 text-center text-[12px] text-slate-400">
                Opens in your mail app — nothing is stored here.
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
