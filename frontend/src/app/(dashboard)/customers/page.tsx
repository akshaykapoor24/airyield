"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Search, Edit2, Trash2, RefreshCw, Upload, Contact, ChevronRight, AlertTriangle, X } from "lucide-react";
import api from "@/lib/api";
import Pagination from "@/components/ui/Pagination";
import CustomerModal, { type Customer } from "@/components/customers/CustomerModal";
import UploadCustomersModal from "@/components/customers/UploadCustomersModal";

const PAGE_SIZE = 25;

function markupTypeLabel(c: Customer): string {
  if (!c.markup_type) return "—";
  return c.markup_type === "percentage" ? "Percentage" : "Fixed";
}

function markupValueLabel(c: Customer): string {
  if (c.markup_value == null || !c.markup_type) return "—";
  return c.markup_type === "percentage" ? `${c.markup_value}%` : `₹${c.markup_value}`;
}

function billingLabel(c: Customer): string {
  if (!c.billing_type) return "—";
  return c.billing_type.charAt(0).toUpperCase() + c.billing_type.slice(1);
}

export default function CustomersPage() {
  const router = useRouter();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [editTarget, setEditTarget] = useState<Customer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchCustomers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Customer[]>("/customers/", { params: { limit: 500 } });
      setCustomers(data);
    } catch {
      setError("Failed to load customers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCustomers();
  }, [fetchCustomers]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter((c) =>
      [c.first_name, c.last_name, c.company, c.email, c.phone]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [customers, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  useEffect(() => {
    if (page > totalPages) setPage(1);
  }, [page, totalPages]);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/customers/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchCustomers();
    } catch {
      alert("Failed to delete customer.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Customers</p>
          <h1 className="text-xl font-bold text-gray-900">My Customers</h1>
          <p className="text-xs text-gray-500 mt-0.5">{customers.length} customers</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchCustomers}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={() => setShowUpload(true)}
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            <Upload className="w-3.5 h-3.5" /> Upload Excel
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Add Customer
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search by name, company, email or phone…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-gray-50"
            />
          </div>
          <span className="text-[11px] text-gray-400 ml-auto">{filtered.length} shown</span>
        </div>

        {error && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border-b border-red-100">{error}</div>}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {["NAME", "COMPANY", "TITLE", "EMAIL", "PHONE", "MARKUP TYPE", "MARKUP VALUE", "BILLING", "ACTIONS"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-xs text-gray-400">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading customers…
                  </td>
                </tr>
              ) : pageItems.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center justify-center text-center">
                      <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                        <Contact className="w-7 h-7 text-gray-300" />
                      </div>
                      <p className="text-sm font-medium text-gray-600">No customers yet</p>
                      <p className="text-xs text-gray-400 mt-1 mb-4">Add a customer manually or import from Excel.</p>
                      <div className="flex gap-2">
                        <button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white text-xs font-semibold px-3.5 py-2 rounded-lg">
                          <Plus className="w-3.5 h-3.5" /> Add Customer
                        </button>
                        <button onClick={() => setShowUpload(true)} className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold px-3.5 py-2 rounded-lg hover:bg-gray-50">
                          <Upload className="w-3.5 h-3.5" /> Upload Excel
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                pageItems.map((c, idx) => (
                  <tr
                    key={c.id}
                    onClick={() => router.push(`/customers/${c.id}`)}
                    className={`border-b border-gray-50 hover:bg-blue-50/40 transition-colors group cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-[12px] text-gray-800">
                          {c.first_name} {c.last_name ?? ""}
                        </span>
                        <ChevronRight className="w-3 h-3 text-gray-300 group-hover:text-[#1e3a5f]" />
                      </div>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{c.company ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{c.title ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{c.email ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-500">{c.phone ?? "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-600">{markupTypeLabel(c)}</td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-gray-700">{markupValueLabel(c)}</td>
                    <td className="px-3 py-2">
                      {c.billing_type ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-100">
                          {billingLabel(c)}
                        </span>
                      ) : (
                        <span className="text-[11px] text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1">
                        <button onClick={() => setEditTarget(c)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Edit">
                          <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                        </button>
                        <button onClick={() => setDeleteTarget(c)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {filtered.length > PAGE_SIZE && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={(p) => setPage(p)} />
        )}
      </div>

      {showAdd && <CustomerModal onClose={() => setShowAdd(false)} onSaved={fetchCustomers} />}
      {showUpload && <UploadCustomersModal onClose={() => setShowUpload(false)} onSaved={fetchCustomers} />}
      {editTarget && <CustomerModal customer={editTarget} onClose={() => setEditTarget(null)} onSaved={fetchCustomers} />}

      {deleteTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-red-500" />
                </div>
                <h2 className="text-sm font-bold text-gray-900">Delete Customer</h2>
              </div>
              <button onClick={() => setDeleteTarget(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-4">
              <p className="text-sm text-gray-600">
                Are you sure you want to delete{" "}
                <span className="font-semibold text-gray-900">
                  {deleteTarget.first_name} {deleteTarget.last_name ?? ""}
                </span>
                ? This action cannot be undone.
              </p>
            </div>
            <div className="px-6 pb-5 flex gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
