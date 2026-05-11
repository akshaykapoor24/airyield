"use client";

import { useState } from "react";
import { Check, Globe, Bell, Database, Shield } from "lucide-react";

const TABS = ["General", "Notifications", "Calculation", "Security"] as const;
type Tab = typeof TABS[number];

export default function ConfigurationPage() {
  const [tab, setTab] = useState<Tab>("General");
  const [saved, setSaved] = useState(false);
  const [config, setConfig] = useState({
    orgName: "AirYield Operations Pvt. Ltd.",
    baseCurrency: "USD",
    timezone: "Asia/Kolkata (IST)",
    fiscalYearStart: "April",
    dateFormat: "DD MMM YYYY",
    emailNotifications: true,
    inAppNotifications: true,
    dealSubmitNotify: true,
    overrideRequestNotify: true,
    calculationCompleteNotify: true,
    slaBreachNotify: true,
    defaultCommission: "4.0",
    roundingRule: "2 decimal places",
    allowNegativeIncome: false,
    autoMatchDeals: true,
    sessionTimeout: "60",
    passwordExpiry: "90",
    mfaRequired: false,
    auditLogRetention: "365",
  });

  const set = (key: string, value: any) => setConfig(p => ({ ...p, [key]: value }));
  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">System Configuration</h1>
          <p className="text-sm text-gray-500 mt-0.5">Global settings for the AirYield platform</p>
        </div>
        <button onClick={save} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          {saved ? <><Check className="w-4 h-4" /> Saved!</> : "Save Changes"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-800"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "General" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2 border-b border-gray-100 pb-3">
            <Globe className="w-4 h-4 text-blue-500" /> General Settings
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-gray-700 mb-1">Organization Name</label>
              <input value={config.orgName} onChange={e => set("orgName", e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            {[
              { label: "Base Currency", key: "baseCurrency", options: ["USD", "INR", "AED", "EUR", "GBP"] },
              { label: "Timezone", key: "timezone", options: ["Asia/Kolkata (IST)", "UTC", "Asia/Dubai (GST)", "America/New_York (EST)"] },
              { label: "Fiscal Year Start", key: "fiscalYearStart", options: ["January", "April", "July", "October"] },
              { label: "Date Format", key: "dateFormat", options: ["DD MMM YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] },
            ].map(({ label, key, options }) => (
              <div key={key}>
                <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
                <select value={(config as any)[key]} onChange={e => set(key, e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {options.map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "Notifications" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2 border-b border-gray-100 pb-3">
            <Bell className="w-4 h-4 text-orange-500" /> Notification Preferences
          </h2>
          <div className="space-y-3">
            {[
              { label: "Email Notifications", sub: "Send email alerts for important events", key: "emailNotifications" },
              { label: "In-App Notifications", sub: "Show notification badges in the sidebar", key: "inAppNotifications" },
              { label: "Deal Submitted / Approved", sub: "Notify when a deal changes approval status", key: "dealSubmitNotify" },
              { label: "Override Requests", sub: "Notify when a manual override is created or actioned", key: "overrideRequestNotify" },
              { label: "Calculation Complete", sub: "Notify when a batch calculation finishes", key: "calculationCompleteNotify" },
              { label: "SLA Breach Alerts", sub: "Alert when an approval exceeds SLA time", key: "slaBreachNotify" },
            ].map(({ label, sub, key }) => (
              <label key={key} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg cursor-pointer">
                <div>
                  <p className="text-sm font-medium text-gray-900">{label}</p>
                  <p className="text-xs text-gray-500">{sub}</p>
                </div>
                <div className={`relative w-10 h-5 rounded-full transition-colors ${(config as any)[key] ? "bg-blue-600" : "bg-gray-300"}`}
                  onClick={() => set(key, !(config as any)[key])}>
                  <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${(config as any)[key] ? "translate-x-5" : "translate-x-0.5"}`} />
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {tab === "Calculation" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2 border-b border-gray-100 pb-3">
            <Database className="w-4 h-4 text-green-500" /> Calculation Settings
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Default Commission %</label>
              <input value={config.defaultCommission} onChange={e => set("defaultCommission", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Rounding Rule</label>
              <select value={config.roundingRule} onChange={e => set("roundingRule", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {["2 decimal places", "No rounding", "Round up", "Round down"].map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
          </div>
          <div className="space-y-3 pt-2">
            {[
              { label: "Allow Negative Income", sub: "If income calculation results in a negative value, record it as-is", key: "allowNegativeIncome" },
              { label: "Auto-match Deals", sub: "Automatically match tickets to deals during upload validation", key: "autoMatchDeals" },
            ].map(({ label, sub, key }) => (
              <label key={key} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg cursor-pointer">
                <div>
                  <p className="text-sm font-medium text-gray-900">{label}</p>
                  <p className="text-xs text-gray-500">{sub}</p>
                </div>
                <div className={`relative w-10 h-5 rounded-full transition-colors ${(config as any)[key] ? "bg-blue-600" : "bg-gray-300"}`}
                  onClick={() => set(key, !(config as any)[key])}>
                  <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${(config as any)[key] ? "translate-x-5" : "translate-x-0.5"}`} />
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {tab === "Security" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2 border-b border-gray-100 pb-3">
            <Shield className="w-4 h-4 text-red-500" /> Security Settings
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Session Timeout (minutes)</label>
              <input type="number" value={config.sessionTimeout} onChange={e => set("sessionTimeout", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Password Expiry (days)</label>
              <input type="number" value={config.passwordExpiry} onChange={e => set("passwordExpiry", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Audit Log Retention (days)</label>
              <input type="number" value={config.auditLogRetention} onChange={e => set("auditLogRetention", e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <label className="flex items-center justify-between p-3 bg-gray-50 rounded-lg cursor-pointer mt-2">
            <div>
              <p className="text-sm font-medium text-gray-900">Require MFA for all users</p>
              <p className="text-xs text-gray-500">All users must verify with an authenticator app at login</p>
            </div>
            <div className={`relative w-10 h-5 rounded-full transition-colors ${config.mfaRequired ? "bg-blue-600" : "bg-gray-300"}`}
              onClick={() => set("mfaRequired", !config.mfaRequired)}>
              <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${config.mfaRequired ? "translate-x-5" : "translate-x-0.5"}`} />
            </div>
          </label>
        </div>
      )}
    </div>
  );
}
