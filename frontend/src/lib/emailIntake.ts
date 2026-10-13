// Email intake — connecting a mailbox. Types mirror backend/app/schemas/mail.py; see
// architecture/03-mailbox-connectors.md for the design.

export type MailProvider = "gmail" | "microsoft" | "imap" | "relay";
export type ConnectionStatus =
  | "pending_auth" | "active" | "needs_reauth" | "paused" | "error" | "disconnected";

export type ProviderAvailability = { available: boolean; reason: string | null };

export type MailConfig = {
  enabled: boolean;
  encryption_ready: boolean;
  can_connect: boolean;
  can_connect_workspace: boolean;
  providers: Record<MailProvider, ProviderAvailability>;
  inbound_domain: string | null;
};

export type DetectResult = {
  email_address: string;
  provider: Exclude<MailProvider, "relay"> | null;
  imap_host: string | null;
  imap_port: number | null;
  label: string;
  note: string | null;
  provider_key: string | null;
};

/** One entry of the provider catalogue (backend services/mail/providers.py). */
export type ProviderInfo = {
  key: string;
  name: string;
  connector: "gmail" | "microsoft" | "imap";
  blurb: string;
  imap_host: string | null;
  imap_port: number;
  password_label: string;
  steps: string[];
  help_url: string | null;
  popular: boolean;
  regions: { code: string; label: string; host: string; free_host: string }[];
  available: boolean;
  reason: string | null;
  /** Google / Microsoft: is their sign-in app configured on this server? */
  oauth_available: boolean;
  /** Google: the app-password IMAP route used when sign-in is not configured. */
  imap_alternative: { host: string; port: number; password_label: string; steps: string[]; help_url: string | null } | null;
};

/** Brand badge per provider key — what a mailbox looks like at a glance. */
export const BRAND: Record<string, { short: string; tile: string }> = {
  google:    { short: "G",  tile: "bg-red-50 text-red-600 ring-red-100" },
  microsoft: { short: "M",  tile: "bg-sky-50 text-sky-700 ring-sky-100" },
  godaddy:   { short: "GD", tile: "bg-teal-50 text-teal-700 ring-teal-100" },
  zoho:      { short: "Z",  tile: "bg-amber-50 text-amber-700 ring-amber-100" },
  titan:     { short: "T",  tile: "bg-indigo-50 text-indigo-700 ring-indigo-100" },
  yahoo:     { short: "Y!", tile: "bg-purple-50 text-purple-700 ring-purple-100" },
  icloud:    { short: "iC", tile: "bg-slate-100 text-slate-700 ring-slate-200" },
  rediff:    { short: "R",  tile: "bg-rose-50 text-rose-700 ring-rose-100" },
  hostinger: { short: "H",  tile: "bg-violet-50 text-violet-700 ring-violet-100" },
  namecheap: { short: "NC", tile: "bg-orange-50 text-orange-700 ring-orange-100" },
  aol:       { short: "A",  tile: "bg-blue-50 text-blue-700 ring-blue-100" },
  yandex:    { short: "Ya", tile: "bg-red-50 text-red-700 ring-red-100" },
  fastmail:  { short: "F",  tile: "bg-blue-50 text-blue-800 ring-blue-100" },
  other:     { short: "IM", tile: "bg-slate-100 text-slate-700 ring-slate-200" },
  relay:     { short: "FW", tile: "bg-violet-50 text-violet-700 ring-violet-100" },
};

export function brandOf(provider: MailProvider, providerKey?: string | null) {
  const key = providerKey ?? (provider === "gmail" ? "google" : provider === "imap" ? "other" : provider);
  return BRAND[key] ?? BRAND.other;
}

export type MailConnection = {
  id: number;
  provider: MailProvider;
  email_address: string;
  visibility: "personal" | "workspace";
  status: ConnectionStatus;
  status_reason: string | null;
  screening_mode: "strict" | "extended";
  settings: { folders?: string[]; include_spam?: boolean; backfill_days?: number; provider_key?: string };
  owner: { id: number; name: string };
  is_mine: boolean;
  imap_host: string | null;
  imap_port: number | null;
  imap_username: string | null;
  forwarding_address: string | null;
  granted_scopes: string | null;
  last_tested_at: string | null;
  last_synced_at: string | null;
  created_at: string;
};

export type FolderInfo = { name: string; display: string; special_use: string | null };
export type TestResult = { ok: boolean; message: string; status: ConnectionStatus; folders: FolderInfo[] | null };
export type ConnectResult = { connection: MailConnection; test: TestResult };

export const PROVIDER_LABEL: Record<MailProvider, string> = {
  gmail: "Gmail / Google Workspace",
  microsoft: "Microsoft 365 / Outlook",
  imap: "IMAP (Zoho, GoDaddy, Rediff…)",
  relay: "Forwarding address",
};

export const STATUS_META: Record<ConnectionStatus, { label: string; badge: string }> = {
  pending_auth: { label: "Waiting for sign-in", badge: "bg-gray-50 text-gray-600 border-gray-200" },
  active:       { label: "Connected",           badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  needs_reauth: { label: "Reconnect needed",    badge: "bg-amber-50 text-amber-700 border-amber-200" },
  paused:       { label: "Paused",              badge: "bg-slate-100 text-slate-600 border-slate-200" },
  error:        { label: "Error",               badge: "bg-red-50 text-red-700 border-red-200" },
  disconnected: { label: "Disconnected",        badge: "bg-gray-50 text-gray-400 border-gray-200" },
};

export const BACKFILL_OPTIONS = [7, 30, 90, 180] as const;

/** Port → the only two secure ways to speak IMAP. Plaintext is not offered. */
export const IMAP_PORTS = [
  { port: 993, label: "993 — SSL/TLS (recommended)" },
  { port: 143, label: "143 — STARTTLS" },
] as const;

export function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  // The API sends naive UTC; say so, or the browser reads it as local time.
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ── received mail (backend/app/api/v1/mail_inbox.py) ────────────────────────

export type Segment = "B2B" | "B2E" | "B2C";

export type MailParty = {
  party_type: "agency" | "corporate" | "customer";
  party_id: number;
  label: string;
  segment: Segment;
  /** "domain" = not the address in the master but someone else at its company domain. */
  via?: "address" | "domain" | null;
};

export type MailAttachment = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  is_inline: boolean;
  previewable: boolean;
  doc_kind: "statement" | "other" | null;
  doc_type: string | null;
  doc_family: string | null;
  doc_label: string | null;
  doc_confidence: number | null;
  doc_reason: string | null;
  doc_rows: number | null;
};

/** A statement found in an email's attachments (backend services/mail/classify.py). */
export type DocTag = { doc_type: string; family: string; label: string };

export type MailboxCount = {
  id: number;
  email_address: string;
  provider: MailProvider;
  provider_key: string | null;
  status: ConnectionStatus;
  total: number;
  unread: number;
  statements: number;
};

/** Statement families, in the order the inbox offers them as filters. */
export const STATEMENT_FAMILIES: { key: string; label: string; badge: string }[] = [
  { key: "bsp",         label: "BSP",          badge: "bg-blue-50 text-blue-700 border-blue-200" },
  { key: "lcc",         label: "LCC",          badge: "bg-orange-50 text-orange-700 border-orange-200" },
  { key: "third_party", label: "Third party",  badge: "bg-teal-50 text-teal-700 border-teal-200" },
  { key: "ndc",         label: "NDC",          badge: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  { key: "tgq",         label: "TGQ HMPR",     badge: "bg-cyan-50 text-cyan-700 border-cyan-200" },
  { key: "mo",          label: "MO",           badge: "bg-slate-100 text-slate-700 border-slate-200" },
  { key: "bank",        label: "Bank",         badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  { key: "unknown",     label: "Unrecognised", badge: "bg-amber-50 text-amber-700 border-amber-200" },
];

export function familyBadge(family: string): string {
  return STATEMENT_FAMILIES.find(f => f.key === family)?.badge ?? "bg-gray-50 text-gray-600 border-gray-200";
}

export type MailListItem = {
  id: number;
  subject: string | null;
  from_name: string | null;
  from_address: string;
  party: MailParty | null;
  snippet: string | null;
  received_at: string;
  attachment_count: number;
  is_read: boolean;
  mailbox: string;
  connection_id: number;
  statements: DocTag[];
};

export type MailList = {
  items: MailListItem[];
  total: number;
  unread: number;
  statements: number;
  mailboxes: MailboxCount[];
};

export type MailDetail = MailListItem & {
  to_addresses: string[];
  cc_addresses: string[];
  sent_at: string | null;
  parties: MailParty[];
  body_text: string | null;
  has_html: boolean;
  note: string | null;
  attachments: MailAttachment[];
};

export type SyncResult = { status: string; message: string; new_messages: number; senders: number; more_waiting: boolean };

export const SEGMENT_BADGE: Record<Segment, string> = {
  B2B: "bg-sky-50 text-sky-700 border-sky-200",
  B2E: "bg-violet-50 text-violet-700 border-violet-200",
  B2C: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

export const SEGMENT_MASTER: Record<Segment, string> = {
  B2B: "Agency Master", B2E: "Corporate Master", B2C: "Employee Master",
};

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** "10:42 am" today, "07 Oct" this year, "07 Oct 2025" otherwise. */
export function fmtListDate(iso: string): string {
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("en-IN", d.getFullYear() === now.getFullYear()
    ? { day: "2-digit", month: "short" } : { day: "2-digit", month: "short", year: "numeric" });
}
