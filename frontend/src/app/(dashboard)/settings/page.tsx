"use client";

import { useState } from "react";
import { Plane, Building2, MapPin, Route, Plus, Search, Edit2, Trash2 } from "lucide-react";

const AIRLINES = [
  { id: 1, name: "Emirates", iata: "EK", icao: "UAE", active: true },
  { id: 2, name: "IndiGo", iata: "6E", icao: "IGO", active: true },
  { id: 3, name: "Air India", iata: "AI", icao: "AIC", active: true },
  { id: 4, name: "SpiceJet", iata: "SG", icao: "SEJ", active: true },
  { id: 5, name: "Vistara", iata: "UK", icao: "VTI", active: false },
];

const SUPPLIERS = [
  { id: 1, name: "Gulf Travel Co.", code: "GTC", email: "deals@gulftravelco.com", phone: "+971-4-234-5678", active: true },
  { id: 2, name: "Sky Agents Ltd.", code: "SAL", email: "ops@skyagents.in", phone: "+91-22-4567-8901", active: true },
  { id: 3, name: "PremiumAir", code: "PAR", email: "b2b@premiumair.com", phone: "+91-11-9876-5432", active: true },
  { id: 4, name: "Budget Wings", code: "BWG", email: "deals@budgetwings.in", phone: "+91-80-1234-5678", active: false },
];

const AIRPORTS = [
  { id: 1, iata: "BOM", name: "Chhatrapati Shivaji Maharaj International", city: "Mumbai", country: "India" },
  { id: 2, iata: "DEL", name: "Indira Gandhi International", city: "New Delhi", country: "India" },
  { id: 3, iata: "DXB", name: "Dubai International", city: "Dubai", country: "UAE" },
  { id: 4, iata: "LHR", name: "Heathrow", city: "London", country: "UK" },
  { id: 5, iata: "CCU", name: "Netaji Subhas Chandra Bose International", city: "Kolkata", country: "India" },
];

type Tab = "airlines" | "suppliers" | "airports";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("airlines");
  const [search, setSearch] = useState("");

  const TABS: { key: Tab; label: string; icon: any }[] = [
    { key: "airlines", label: "Airlines", icon: Plane },
    { key: "suppliers", label: "Suppliers", icon: Building2 },
    { key: "airports", label: "Airports", icon: MapPin },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">Manage master data for airlines, suppliers, and airports</p>
      </div>

      {/* Tab Bar */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === key ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {/* Toolbar */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={`Search ${tab}...`}
              className="pl-9 pr-4 py-1.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-60"
            />
          </div>
          <button className="flex items-center gap-2 bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Add {tab.slice(0, -1).charAt(0).toUpperCase() + tab.slice(1, -1)}
          </button>
        </div>

        {/* Airlines Table */}
        {tab === "airlines" && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-5 py-3 text-left">Name</th>
                <th className="px-5 py-3 text-left">IATA</th>
                <th className="px-5 py-3 text-left">ICAO</th>
                <th className="px-5 py-3 text-left">Status</th>
                <th className="px-5 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {AIRLINES.filter((a) => a.name.toLowerCase().includes(search.toLowerCase()) || a.iata.toLowerCase().includes(search.toLowerCase())).map((a) => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium">{a.name}</td>
                  <td className="px-5 py-3 font-mono font-bold text-blue-600">{a.iata}</td>
                  <td className="px-5 py-3 font-mono text-gray-500">{a.icao}</td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${a.active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {a.active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-center">
                    <div className="flex justify-center gap-2">
                      <button className="p-1 hover:bg-blue-50 rounded"><Edit2 className="w-3.5 h-3.5 text-blue-500" /></button>
                      <button className="p-1 hover:bg-red-50 rounded"><Trash2 className="w-3.5 h-3.5 text-red-400" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Suppliers Table */}
        {tab === "suppliers" && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-5 py-3 text-left">Name</th>
                <th className="px-5 py-3 text-left">Code</th>
                <th className="px-5 py-3 text-left">Email</th>
                <th className="px-5 py-3 text-left">Phone</th>
                <th className="px-5 py-3 text-left">Status</th>
                <th className="px-5 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {SUPPLIERS.filter((s) => s.name.toLowerCase().includes(search.toLowerCase()) || s.code.toLowerCase().includes(search.toLowerCase())).map((s) => (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium">{s.name}</td>
                  <td className="px-5 py-3 font-mono font-bold text-purple-600">{s.code}</td>
                  <td className="px-5 py-3 text-gray-500">{s.email}</td>
                  <td className="px-5 py-3 text-gray-500">{s.phone}</td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${s.active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {s.active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-center">
                    <div className="flex justify-center gap-2">
                      <button className="p-1 hover:bg-blue-50 rounded"><Edit2 className="w-3.5 h-3.5 text-blue-500" /></button>
                      <button className="p-1 hover:bg-red-50 rounded"><Trash2 className="w-3.5 h-3.5 text-red-400" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Airports Table */}
        {tab === "airports" && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-5 py-3 text-left">IATA</th>
                <th className="px-5 py-3 text-left">Airport Name</th>
                <th className="px-5 py-3 text-left">City</th>
                <th className="px-5 py-3 text-left">Country</th>
                <th className="px-5 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {AIRPORTS.filter((a) => a.iata.toLowerCase().includes(search.toLowerCase()) || a.city.toLowerCase().includes(search.toLowerCase()) || a.name.toLowerCase().includes(search.toLowerCase())).map((a) => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-mono font-bold text-teal-600">{a.iata}</td>
                  <td className="px-5 py-3 font-medium">{a.name}</td>
                  <td className="px-5 py-3 text-gray-600">{a.city}</td>
                  <td className="px-5 py-3 text-gray-500">{a.country}</td>
                  <td className="px-5 py-3 text-center">
                    <div className="flex justify-center gap-2">
                      <button className="p-1 hover:bg-blue-50 rounded"><Edit2 className="w-3.5 h-3.5 text-blue-500" /></button>
                      <button className="p-1 hover:bg-red-50 rounded"><Trash2 className="w-3.5 h-3.5 text-red-400" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
