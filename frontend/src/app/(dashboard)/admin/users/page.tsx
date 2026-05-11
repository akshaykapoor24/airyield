"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Plus, Search, Edit2, MoreVertical,
  Shield, User, ChevronDown, X, Check, RefreshCw,
} from "lucide-react";
import api from "@/lib/api";

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
  user, onClose, onSave, adminDomain,
}: {
  user: Partial<UserRow> | null;
  onClose: () => void;
  onSave: (u: Partial<UserRow> & { password?: string }) => void;
  adminDomain: string;
}) {
  const isEdit = !!user?.id;
  const [form, setForm] = useState({
    full_name:  user?.full_name  ?? "",
    email:      user?.email      ?? "",
    password:   "",
    role:       (user?.role      ?? "viewer") as RoleValue,
    department: user?.department ?? "",
  });
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
            onClick={() => onSave({ ...user, ...form })}
            disabled={!form.full_name || !form.email || (!isEdit && !form.password) || !!domainError}
            className="flex-1 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed">
            {isEdit ? "Save Changes" : "Create User"}
          </button>
        </div>
      </div>
    </div>
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

  // derive admin's domain from the logged-in user stored in localStorage
  const adminEmail  = typeof window !== "undefined" ? (() => { try { return JSON.parse(localStorage.getItem("ay_user") ?? "{}").email ?? ""; } catch { return ""; } })() : "";
  const adminDomain = adminEmail.includes("@") ? adminEmail.split("@")[1].toLowerCase() : "";

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
  const deleteUser = async (id: number) => {
    if (!confirm("Delete this user? This cannot be undone.")) return;
    setMenuOpen(null);
    try {
      await api.delete(`/users/${id}`);
      setUsers(p => p.filter(u => u.id !== id));
    } catch {
      alert("Failed to delete user.");
    }
  };

  // ── create / update user ──────────────────────────────────────────────
  const handleSave = async (data: Partial<UserRow> & { password?: string }) => {
    try {
      if (data.id) {
        // update role if changed
        const original = users.find(u => u.id === data.id);
        if (original?.role !== data.role) {
          await api.patch(`/users/${data.id}/role`, { role: data.role });
        }
        // update name/department via register-style patch (reuse /users/me for self, or just refetch)
        setUsers(p => p.map(u => u.id === data.id ? { ...u, ...data } as UserRow : u));
      } else {
        const { data: created } = await api.post<UserRow>("/users/", {
          full_name:  data.full_name,
          email:      data.email,
          password:   data.password,
          role:       data.role ?? "viewer",
          department: data.department ?? null,
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

  return (
    <div className="space-y-4">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Admin</p>
          <h1 className="text-xl font-bold text-gray-900">User Management</h1>
          <p className="text-xs text-gray-500 mt-0.5">Manage system users, assign roles and control access</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchUsers} disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}/>
          </button>
          <button onClick={() => setModal(null)}
            className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3.5 py-2 rounded-lg text-xs font-medium hover:bg-[#16304f]">
            <Plus className="w-3.5 h-3.5"/> Add User
          </button>
        </div>
      </div>

      {/* ── Role stats ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-6 gap-2">
        {stats.map(r => (
          <button key={r.value} onClick={() => setRoleFilter(roleFilter === r.value ? "all" : r.value)}
            className={`rounded-xl border px-3 py-2.5 text-center transition-all ${
              roleFilter === r.value ? "ring-2 ring-[#1e3a5f] ring-offset-1" : "hover:shadow-sm"
            } ${r.color}`}>
            <p className="text-xl font-bold">{r.count}</p>
            <p className="text-[10px] font-medium mt-0.5 leading-snug">{r.label}</p>
          </button>
        ))}
      </div>

      {/* ── Filters + table ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">

        {/* toolbar */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400"/>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or email..."
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
          </div>

          <select value={roleFilter} onChange={e => setRoleFilter(e.target.value as RoleValue | "all")}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
            <option value="all">All Roles</option>
            {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>

          <select value={statusFilter} onChange={e => setStatus(e.target.value as typeof statusFilter)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>

          <span className="text-[11px] text-gray-400 ml-auto">{filtered.length} user{filtered.length !== 1 ? "s" : ""}</span>
        </div>

        {/* table */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {["User", "Role", "Department", "Status", "Created", "Actions"].map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300"/>
                    Loading users...
                  </td>
                </tr>
              ) : apiError ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-xs text-red-400">{apiError}</td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-xs text-gray-400">No users found.</td>
                </tr>
              ) : filtered.map((u, idx) => (
                <tr key={u.id}
                  className={`border-b border-gray-100 hover:bg-gray-50/60 transition-colors ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>

                  {/* user */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${roleInfo(u.role).color}`}>
                        {u.full_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-[12px] font-semibold text-gray-800">{u.full_name}</p>
                        <p className="text-[10px] text-gray-400">{u.email}</p>
                      </div>
                    </div>
                  </td>

                  {/* role */}
                  <td className="px-4 py-3">
                    <RoleBadge role={u.role}/>
                  </td>

                  {/* department */}
                  <td className="px-4 py-3 text-xs text-gray-600">{u.department || "—"}</td>

                  {/* status */}
                  <td className="px-4 py-3">
                    <button onClick={() => toggleActive(u.id)}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border cursor-pointer transition-colors ${
                        u.is_active
                          ? "bg-green-50 text-green-600 border-green-200 hover:bg-green-100"
                          : "bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"
                      }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-green-500" : "bg-gray-400"}`}/>
                      {u.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>

                  {/* created */}
                  <td className="px-4 py-3 text-[11px] text-gray-500">{u.created_at}</td>

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
                          className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 transition-colors">
                          <MoreVertical className="w-3.5 h-3.5"/>
                        </button>
                        {menuOpen === u.id && (
                          <div className="absolute right-0 mt-0.5 w-36 bg-white border border-gray-200 rounded-lg shadow-lg z-20 overflow-hidden">
                            <button onClick={() => { toggleActive(u.id); setMenuOpen(null); }}
                              className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50">
                              {u.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button onClick={() => deleteUser(u.id)}
                              className="w-full text-left px-3 py-2 text-xs text-red-500 hover:bg-red-50">
                              Delete User
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
      </div>

      {/* ── Role reference card ──────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
        <div className="flex items-center gap-2 mb-3">
          <Shield className="w-4 h-4 text-[#1e3a5f]"/>
          <h2 className="text-xs font-bold text-gray-800 uppercase tracking-wide">Role Permissions Reference</h2>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {ROLES.map(r => (
            <div key={r.value} className={`rounded-lg border px-3 py-2.5 ${r.color}`}>
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`w-2 h-2 rounded-full ${r.dot}`}/>
                <span className="text-[11px] font-bold">{r.label}</span>
              </div>
              <p className="text-[10px] leading-snug opacity-80">{r.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Modal ───────────────────────────────────────────────────────── */}
      {modal !== false && (
        <UserModal
          user={modal}
          onClose={() => setModal(false)}
          onSave={handleSave}
          adminDomain={adminDomain}
        />
      )}

      {/* close menus on outside click */}
      {menuOpen !== null && (
        <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(null)}/>
      )}
    </div>
  );
}
