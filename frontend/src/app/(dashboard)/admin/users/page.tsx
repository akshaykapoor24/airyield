"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Plus, Search, Edit2, MoreVertical,
  Shield, User, ChevronDown, X, Check, RefreshCw, Users, KeyRound, Building2, SlidersHorizontal,
} from "lucide-react";
import api from "@/lib/api";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Entities come from the admin's own My Profile → Entities list — the ones they
// captured during onboarding. Assigning them here says which the member works on.
type AssignableEntity = { id: number; name: string; code: string };
type AssignedEntity = AssignableEntity & { login_ids: string[] };

// ── Role definitions ───────────────────────────────────────────────────────
const ROLES = [
  {
    value: "super_admin",
    label: "Super Admin",
    description: "Full access across all modules. Controls masters, users, rules, reports.",
    color: "bg-red-100 text-red-700 border-red-200",
    dot: "bg-red-500",
  },
  {
    value: "company_admin",
    label: "Company Admin",
    description: "Manages company data, users, suppliers, deal settings, approvals.",
    color: "bg-orange-100 text-orange-700 border-orange-200",
    dot: "bg-orange-500",
  },
  {
    value: "operations_user",
    label: "Operations User",
    description: "Uploads deals & booking data. Reviews extracted data. Raises manual modifications.",
    color: "bg-blue-100 text-blue-700 border-blue-200",
    dot: "bg-blue-500",
  },
  {
    value: "finance_user",
    label: "Finance User",
    description: "Reviews income calculations, runs reports, validates monthly/quarterly income.",
    color: "bg-green-100 text-green-700 border-green-200",
    dot: "bg-green-500",
  },
  {
    value: "approver",
    label: "Approver / Reviewer",
    description: "Approves deal data, manual overrides, and final calculation changes.",
    color: "bg-purple-100 text-purple-700 border-purple-200",
    dot: "bg-purple-500",
  },
  {
    value: "viewer",
    label: "View-only User",
    description: "Views dashboards and reports only. No edit access.",
    color: "bg-gray-100 text-gray-600 border-gray-200",
    dot: "bg-gray-400",
  },
] as const;

type RoleValue = (typeof ROLES)[number]["value"];
const ASSIGNABLE_ROLE_VALUES: RoleValue[] = [
  "company_admin",
  "operations_user",
  "finance_user",
  "approver",
  "viewer",
];

function roleInfo(v: RoleValue) {
  return ROLES.find(r => r.value === v) ?? ROLES[ROLES.length - 1];
}

const DEPARTMENTS = ["Operations", "Revenue", "Finance", "Technology", "Management", "Sales"];

type UserRow = {
  id: number;
  full_name: string;
  email: string;
  role: RoleValue;
  department: string | null;
  is_active: boolean;
  created_at: string;
  entity_ids?: number[];
  entity_names?: string[];
  /** The assignments with what tells them apart: the code, and the login IDs / IATA
   *  numbers under each entity — the same ones this member sees in their My Profile. */
  entities?: AssignedEntity[];
};

// ── role badge ─────────────────────────────────────────────────────────────
function RoleBadge({ role }: { role: RoleValue }) {
  const r = roleInfo(role);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${r.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${r.dot}`}/>
      {r.label}
    </span>
  );
}

// ── add/edit modal ─────────────────────────────────────────────────────────
function UserModal({
  user, onClose, onSave, adminDomain, entities, entitiesLoading,
}: {
  user: Partial<UserRow> | null;
  onClose: () => void;
  onSave: (u: Partial<UserRow> & { password?: string; entity_ids?: number[] }) => void;
  adminDomain: string;
  entities: AssignableEntity[];
  entitiesLoading: boolean;
}) {
  const isEdit = !!user?.id;
  const [form, setForm] = useState({
    full_name:  user?.full_name  ?? "",
    email:      user?.email      ?? "",
    password:   "",
    role:       (user?.role      ?? "viewer") as RoleValue,
    department: user?.department ?? "",
  });
  const [entityIds, setEntityIds] = useState<number[]>(user?.entity_ids ?? []);
  const [roleOpen, setRoleOpen] = useState(false);
  const [domainError, setDomainError] = useState("");

  const set = (k: string, v: string) => setForm(p => ({ ...p, [k]: v }));

  const handleEmailChange = (v: string) => {
    set("email", v);
    if (v.includes("@")) {
      const enteredDomain = v.split("@")[1]?.toLowerCase();
      if (enteredDomain && adminDomain && enteredDomain !== adminDomain) {
        setDomainError(`Only @${adminDomain} emails are allowed in your organisation.`);
      } else {
        setDomainError("");
      }
    } else {
      setDomainError("");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        {/* header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[#1e3a5f]/10 flex items-center justify-center">
              <User className="w-4 h-4 text-[#1e3a5f]"/>
            </div>
            <h2 className="text-sm font-bold text-gray-900">{isEdit ? "Edit User" : "Add New User"}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500"/></button>
        </div>

        <div className="px-6 py-4 space-y-3">
          {/* name */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Full Name *</label>
            <input value={form.full_name} onChange={e => set("full_name", e.target.value)}
              placeholder="e.g. Priya Nair"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"/>
          </div>

          {/* email */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Email Address * <span className="text-gray-400 font-normal">(@{adminDomain} only)</span>
            </label>
            <input type="email" value={form.email} onChange={e => handleEmailChange(e.target.value)}
              placeholder={`user@${adminDomain}`} disabled={isEdit}
              className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 disabled:bg-gray-50 disabled:text-gray-400 ${
                domainError ? "border-red-300 focus:ring-red-200" : "border-gray-200 focus:ring-[#1e3a5f]/30"
              }`}/>
            {domainError && (
              <p className="text-[11px] text-red-500 mt-1 flex items-center gap-1">
                <span>⚠</span> {domainError}
              </p>
            )}
          </div>

          {/* password */}
          {!isEdit && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Password *</label>
              <input type="password" value={form.password} onChange={e => set("password", e.target.value)}
                placeholder="Min 8 characters"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"/>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {/* role */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Role *</label>
              <div className="relative">
                <button type="button" onClick={() => setRoleOpen(o => !o)}
                  className="w-full flex items-center justify-between border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white text-left focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30">
                  <span>{roleInfo(form.role).label}</span>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-400"/>
                </button>
                {roleOpen && (
                  <div className="absolute z-50 w-72 mt-0.5 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
                    {ROLES.filter(r => ASSIGNABLE_ROLE_VALUES.includes(r.value)).map(r => (
                      <button key={r.value} type="button"
                        onClick={() => { set("role", r.value); setRoleOpen(false); }}
                        className={`w-full text-left px-3 py-2.5 hover:bg-gray-50 flex items-start gap-2.5 ${form.role === r.value ? "bg-blue-50" : ""}`}>
                        <span className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${r.dot}`}/>
                        <div>
                          <p className="text-xs font-semibold text-gray-800">{r.label}</p>
                          <p className="text-[11px] text-gray-400 leading-snug mt-0.5">{r.description}</p>
                        </div>
                        {form.role === r.value && <Check className="w-3.5 h-3.5 text-blue-500 ml-auto mt-0.5 flex-shrink-0"/>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* department */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Department</label>
              <select value={form.department} onChange={e => set("department", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30">
                <option value="">Select...</option>
                {DEPARTMENTS.map(d => <option key={d}>{d}</option>)}
              </select>
            </div>
          </div>

          {/* entities — options are the admin's own entities from My Profile */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Entities</label>
            {entitiesLoading ? (
              <p className="text-[11px] text-gray-400 py-2">Loading your entities…</p>
            ) : entities.length === 0 ? (
              <p className="text-[11px] text-gray-400 border border-dashed border-gray-200 rounded-lg px-3 py-2 leading-snug">
                You haven&apos;t added any entities yet. Add them under{" "}
                <span className="font-semibold">My Profile → Entities</span>, then assign them here.
              </p>
            ) : (
              <>
                <MultiSelectDropdown
                  options={entities.map(e => ({ value: e.id, label: e.name, sublabel: e.code }))}
                  selected={entityIds}
                  onChange={setEntityIds}
                  placeholder="Select entities…"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  Which of your entities this user works on. Leave empty to assign later.
                </p>
              </>
            )}
          </div>

          {/* role description */}
          <div className={`px-3 py-2.5 rounded-lg border text-[11px] leading-snug ${roleInfo(form.role).color}`}>
            <span className="font-semibold">{roleInfo(form.role).label}: </span>
            {roleInfo(form.role).description}
          </div>
        </div>

        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={() => onSave({ ...user, ...form, entity_ids: entityIds })}
            disabled={!form.full_name || !form.email || (!isEdit && !form.password) || !!domainError}
            className="flex-1 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed">
            {isEdit ? "Save Changes" : "Create User"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** "16 Sep 2026" — a readable date instead of the raw timestamp the API sends.
 *  Safe against a bad value: an unparseable date is shown as it arrived. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Which entities this member works on — by NAME and CODE.
 *
 *  The code is not decoration: a group's entities routinely share a name (three called
 *  "yatra"), so the name alone cannot say which ones were assigned. */
function EntitiesCell({ user }: { user: UserRow }) {
  // An older response carried names only; still show something rather than a dash.
  const list: AssignedEntity[] = user.entities?.length
    ? user.entities
    : (user.entity_names ?? []).map((name, i) => ({ id: -i - 1, name, code: "", login_ids: [] }));

  if (!list.length) return <span className="text-xs text-gray-300">—</span>;
  return (
    <div className="flex flex-col items-start gap-1">
      {list.map(e => (
        <span key={e.id}
          className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-800 whitespace-nowrap">
          <Building2 className="w-2.5 h-2.5 text-blue-400" />
          {e.name}
          {e.code && <span className="font-mono text-blue-500">· {e.code}</span>}
        </span>
      ))}
    </div>
  );
}

/** The login IDs / IATA numbers that come with those entities.
 *
 *  A column of its own, because it answers a different question from Entities — "what can
 *  this person actually book on" — and because one entity can hold many. They are not
 *  assigned separately: they follow the entity, so this column is always a consequence of
 *  the one before it. Each chip carries its entity's code when the member has more than
 *  one entity, so a number is never ambiguous. */
function LoginIdsCell({ user }: { user: UserRow }) {
  const entities = user.entities ?? [];
  if (!entities.length) return <span className="text-xs text-gray-300">—</span>;

  const all = entities.flatMap(e => e.login_ids.map(login => ({ login, code: e.code })));
  if (!all.length) {
    return <span className="text-[10px] text-gray-400">No login IDs yet</span>;
  }

  const SHOWN = 4;
  const extra = all.length - SHOWN;
  const showCode = entities.length > 1;
  return (
    <div className="flex flex-wrap gap-1 max-w-64"
      title={all.map(a => `${a.code}: ${a.login}`).join("\n")}>
      {all.slice(0, SHOWN).map(a => (
        <span key={`${a.code}-${a.login}`}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 whitespace-nowrap">
          {showCode && <span className="font-sans text-[9px] font-semibold text-slate-400">{a.code}</span>}
          {a.login}
        </span>
      ))}
      {extra > 0 && (
        <span className="inline-flex items-center rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
          +{extra} more
        </span>
      )}
    </div>
  );
}

/** One role tile above the table — also the filter for that role. */
function RoleStat({ label, count, dot, active, onClick }: {
  label: string; count: number; dot: string; active: boolean; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      className={`rounded-xl border px-3 py-2.5 text-left transition-all ${
        active
          ? "border-[#1e3a5f] bg-[#1e3a5f]/[0.04] ring-1 ring-[#1e3a5f]"
          : "border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm"
      }`}>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide truncate">{label}</p>
      </div>
      <p className="text-xl font-bold text-gray-900 mt-1 leading-none">{count}</p>
    </button>
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function UserManagementPage() {
  const [users, setUsers]           = useState<UserRow[]>([]);
  const [loading, setLoading]       = useState(true);
  const [apiError, setApiError]     = useState("");
  const [search, setSearch]         = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleValue | "all">("all");
  const [statusFilter, setStatus]   = useState<"all" | "active" | "inactive">("all");
  const [modal, setModal]           = useState<Partial<UserRow> | null | false>(false);
  const [menuOpen, setMenuOpen]     = useState<number | null>(null);
  // The member awaiting delete confirmation — the app's popup, not the browser's.
  const [pendingDelete, setPendingDelete] = useState<UserRow | null>(null);
  const [entities, setEntities]     = useState<AssignableEntity[]>([]);
  const [entitiesLoading, setEntitiesLoading] = useState(true);

  // derive admin context from the logged-in user stored in localStorage
  const storedUser = typeof window !== "undefined" ? (() => { try { return JSON.parse(localStorage.getItem("ay_user") ?? "{}"); } catch { return {}; } })() : {};
  const adminEmail  = storedUser?.email ?? "";
  const adminDomain = adminEmail.includes("@") ? adminEmail.split("@")[1].toLowerCase() : "";
  // individual tenants are private single-person workspaces — no team management
  const isIndividual = storedUser?.tenant_type === "individual";

  // ── fetch users from API ──────────────────────────────────────────────
  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setApiError("");
    try {
      const { data } = await api.get<UserRow[]>("/users/");
      setUsers(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setApiError(msg ?? "Failed to load users.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  // The Entities dropdown options — the admin's own entities from My Profile.
  useEffect(() => {
    if (isIndividual) { setEntitiesLoading(false); return; }
    let alive = true;
    api.get<AssignableEntity[]>("/users/assignable-entities")
      .then(({ data }) => { if (alive) setEntities(data); })
      .catch(() => { if (alive) setEntities([]); })
      .finally(() => { if (alive) setEntitiesLoading(false); });
    return () => { alive = false; };
  }, [isIndividual]);

  // ── filtered list ─────────────────────────────────────────────────────
  const filtered = users.filter(u => {
    if (roleFilter !== "all" && u.role !== roleFilter) return false;
    if (statusFilter === "active"   && !u.is_active) return false;
    if (statusFilter === "inactive" &&  u.is_active) return false;
    const q = search.toLowerCase();
    return !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
  });

  // ── toggle active ─────────────────────────────────────────────────────
  const toggleActive = async (id: number) => {
    try {
      const { data } = await api.patch<UserRow>(`/users/${id}/toggle-active`);
      setUsers(p => p.map(u => u.id === id ? data : u));
    } catch {
      alert("Failed to update status.");
    }
  };

  // ── delete user ───────────────────────────────────────────────────────
  /** Runs inside the popup: it stays open and shows the error if the delete fails. */
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    await api.delete(`/users/${id}`);
    setUsers(p => p.filter(u => u.id !== id));
  };

  // ── create / update user ──────────────────────────────────────────────
  const handleSave = async (data: Partial<UserRow> & { password?: string; entity_ids?: number[] }) => {
    try {
      if (data.id) {
        // update role if changed
        const original = users.find(u => u.id === data.id);
        if (original?.role !== data.role) {
          await api.patch(`/users/${data.id}/role`, { role: data.role });
        }
        // entity assignments are replaced wholesale by the API
        const next = data.entity_ids ?? [];
        const before = original?.entity_ids ?? [];
        const changed =
          next.length !== before.length || next.some(id => !before.includes(id));
        let updated: UserRow | null = null;
        if (changed) {
          const res = await api.patch<UserRow>(`/users/${data.id}/entities`, { entity_ids: next });
          updated = res.data;
        }
        // update name/department via register-style patch (reuse /users/me for self, or just refetch)
        setUsers(p => p.map(u => u.id === data.id ? { ...u, ...data, ...(updated ?? {}) } as UserRow : u));
      } else {
        const { data: created } = await api.post<UserRow>("/users/", {
          full_name:  data.full_name,
          email:      data.email,
          password:   data.password,
          role:       data.role ?? "viewer",
          department: data.department ?? null,
          entity_ids: data.entity_ids ?? [],
        });
        setUsers(p => [...p, created]);
      }
      setModal(false);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to save user.");
    }
  };

  // ── stats ─────────────────────────────────────────────────────────────
  const stats = ROLES.map(r => ({
    ...r,
    count: users.filter(u => u.role === r.value).length,
  }));

  const filtersOn = roleFilter !== "all" || statusFilter !== "all" || search.trim() !== "";
  const COLUMNS = ["User", "Role", "Department", "Entities", "Login IDs / IATA", "Status", "Created", "Actions"];

  return (
    <div className="space-y-5">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Admin</p>
          <h1 className="text-xl font-bold text-gray-900">User Management</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Add people to this workspace, give them a role, and choose which entities they work on.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchUsers} disabled={loading} title="Refresh"
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}/>
          </button>
          {isIndividual ? (
            <span className="text-[11px] text-gray-400 self-center max-w-45 leading-snug">
              Private workspace — adding team members isn&apos;t available.
            </span>
          ) : (
            <button onClick={() => setModal(null)}
              className="flex items-center gap-1.5 text-white px-4 py-2 rounded-lg text-xs font-semibold shadow-sm"
              style={{ background: "linear-gradient(135deg, #1e4d8c, #16304f)" }}>
              <Plus className="w-3.5 h-3.5"/> Add User
            </button>
          )}
        </div>
      </div>

      {/* ── Role tiles — also the role filter ──────────────────────────── */}
      <div className="grid gap-2 grid-cols-2 sm:grid-cols-4 xl:grid-cols-7">
        <RoleStat label="All users" count={users.length} dot="bg-slate-400"
          active={roleFilter === "all"} onClick={() => setRoleFilter("all")} />
        {stats.map(r => (
          <RoleStat key={r.value} label={r.label} count={r.count} dot={r.dot}
            active={roleFilter === r.value}
            onClick={() => setRoleFilter(roleFilter === r.value ? "all" : r.value)} />
        ))}
      </div>

      {/* ── Toolbar + table ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">

        <div className="px-4 py-3 border-b border-gray-100 flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-56">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400"/>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or email…"
              className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-sky-400"/>
          </div>

          <SlidersHorizontal className="w-3.5 h-3.5 text-gray-400" />
          <select value={roleFilter} onChange={e => setRoleFilter(e.target.value as RoleValue | "all")}
            className="border border-gray-200 rounded-lg px-2.5 py-2 text-xs text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-sky-400">
            <option value="all">All roles</option>
            {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>

          <select value={statusFilter} onChange={e => setStatus(e.target.value as typeof statusFilter)}
            className="border border-gray-200 rounded-lg px-2.5 py-2 text-xs text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-sky-400">
            <option value="all">All status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>

          <div className="ml-auto flex items-center gap-2">
            {filtersOn && (
              <button onClick={() => { setSearch(""); setRoleFilter("all"); setStatus("all"); }}
                className="flex items-center gap-1 text-[11px] font-semibold text-gray-500 hover:text-gray-700">
                <X className="w-3 h-3" /> Clear filters
              </button>
            )}
            <span className="text-[11px] text-gray-400 whitespace-nowrap">
              {filtered.length} of {users.length} user{users.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px]">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {COLUMNS.map(h => (
                  <th key={h} className="px-4 py-3 text-left text-[10px] font-semibold text-white/90 uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-4 py-14 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300"/>
                    Loading users…
                  </td>
                </tr>
              ) : apiError ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-4 py-14 text-center text-xs text-red-500">{apiError}</td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-4 py-14 text-center">
                    <Users className="w-7 h-7 mx-auto mb-2 text-gray-200" />
                    <p className="text-xs text-gray-500 font-medium">
                      {filtersOn ? "No users match these filters." : "No users yet."}
                    </p>
                    {filtersOn
                      ? <button onClick={() => { setSearch(""); setRoleFilter("all"); setStatus("all"); }}
                          className="mt-1 text-[11px] font-semibold text-sky-600 hover:text-sky-800">Clear filters</button>
                      : !isIndividual && (
                          <p className="text-[11px] text-gray-400 mt-1">Use <span className="font-semibold">Add User</span> to invite your team.</p>
                        )}
                  </td>
                </tr>
              ) : filtered.map(u => (
                <tr key={u.id} className="hover:bg-sky-50/40 transition-colors">

                  {/* user */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 border ${roleInfo(u.role).color}`}>
                        {u.full_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <p className="text-[12px] font-semibold text-gray-900 truncate">{u.full_name}</p>
                        <p className="text-[10px] text-gray-400 truncate">{u.email}</p>
                      </div>
                    </div>
                  </td>

                  <td className="px-4 py-3"><RoleBadge role={u.role}/></td>

                  <td className="px-4 py-3 text-xs text-gray-600 whitespace-nowrap">{u.department || "—"}</td>

                  {/* which entities they work on … */}
                  <td className="px-4 py-3"><EntitiesCell user={u} /></td>

                  {/* … and the credentials those entities carry */}
                  <td className="px-4 py-3"><LoginIdsCell user={u} /></td>

                  {/* status */}
                  <td className="px-4 py-3">
                    <button onClick={() => toggleActive(u.id)}
                      title={u.is_active ? "Deactivate this user" : "Activate this user"}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border cursor-pointer transition-colors ${
                        u.is_active
                          ? "bg-green-50 text-green-600 border-green-200 hover:bg-green-100"
                          : "bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"
                      }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-green-500" : "bg-gray-400"}`}/>
                      {u.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>

                  <td className="px-4 py-3 text-[11px] text-gray-500 whitespace-nowrap">{formatDate(u.created_at)}</td>

                  {/* actions */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal(u)}
                        className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600 transition-colors"
                        title="Edit user">
                        <Edit2 className="w-3.5 h-3.5"/>
                      </button>
                      <div className="relative">
                        <button onClick={() => setMenuOpen(menuOpen === u.id ? null : u.id)}
                          className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 transition-colors" title="More">
                          <MoreVertical className="w-3.5 h-3.5"/>
                        </button>
                        {menuOpen === u.id && (
                          <div className="absolute right-0 mt-0.5 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-20 overflow-hidden">
                            <button onClick={() => { toggleActive(u.id); setMenuOpen(null); }}
                              className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50">
                              {u.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button onClick={() => { setPendingDelete(u); setMenuOpen(null); }}
                              className="w-full text-left px-3 py-2 text-xs text-red-500 hover:bg-red-50">
                              Delete user
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Entities and login IDs are assigned, not typed — say where they come from. */}
        <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50/60 flex items-center gap-1.5">
          <KeyRound className="w-3 h-3 text-gray-400 shrink-0" />
          <p className="text-[10px] text-gray-500">
            Login IDs / IATA numbers follow the entity — assign an entity and its credentials come with it.
            Both are managed in <span className="font-semibold">My Profile</span> and are read-only for everyone else.
          </p>
        </div>
      </div>

      {/* ── Role reference — folded away until asked for ─────────────────── */}
      <details className="group bg-white rounded-2xl border border-gray-200 shadow-sm">
        <summary className="flex items-center justify-between gap-2 px-4 py-3 cursor-pointer list-none">
          <span className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-[#1e3a5f]"/>
            <span className="text-xs font-bold text-gray-800 uppercase tracking-wide">Role permissions reference</span>
          </span>
          <ChevronDown className="w-4 h-4 text-gray-400 transition-transform group-open:rotate-180"/>
        </summary>
        <div className="px-4 pb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {ROLES.map(r => (
            <div key={r.value} className="rounded-xl border border-gray-200 bg-gray-50/60 px-3 py-2.5">
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`w-2 h-2 rounded-full ${r.dot}`}/>
                <span className="text-[11px] font-bold text-gray-800">{r.label}</span>
              </div>
              <p className="text-[10px] leading-snug text-gray-500">{r.description}</p>
            </div>
          ))}
        </div>
      </details>

      {/* ── Modal ───────────────────────────────────────────────────────── */}
      {modal !== false && (
        <UserModal
          user={modal}
          onClose={() => setModal(false)}
          onSave={handleSave}
          adminDomain={adminDomain}
          entities={entities}
          entitiesLoading={entitiesLoading}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Delete user"
          confirmLabel="Delete user"
          onConfirm={confirmDelete}
          onClose={() => setPendingDelete(null)}
        >
          <p>
            Delete <span className="font-semibold text-gray-900">{pendingDelete.full_name}</span>{" "}
            <span className="text-gray-400">({pendingDelete.email})</span>? They lose access immediately.
            This cannot be undone.
          </p>
          <p className="text-gray-400">
            Their entity assignments go with them. The entities and login IDs themselves are not affected.
          </p>
        </ConfirmDialog>
      )}

      {/* close menus on outside click */}
      {menuOpen !== null && (
        <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(null)}/>
      )}
    </div>
  );
}
