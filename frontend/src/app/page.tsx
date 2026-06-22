"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  FileText, Calculator, CheckSquare, BarChart2,
  ArrowRight, ShieldCheck, Plane,
} from "lucide-react";
import { isAuthenticated } from "@/lib/auth";

const NAVY = "#1e3a5f";
const NAVY_GRADIENT = "linear-gradient(135deg, #1e3a5f 0%, #0f2240 60%, #0a1628 100%)";

const FEATURES = [
  {
    icon: FileText,
    title: "Deal Management",
    desc: "Track airline contracts, incentives, and validity periods across B2B, B2C, and B2E in one repository.",
  },
  {
    icon: Calculator,
    title: "Income Calculation",
    desc: "Automatically calculate incentive income from tickets against your active deals — no spreadsheets.",
  },
  {
    icon: CheckSquare,
    title: "Approval Workflows",
    desc: "Route deals and overrides through configurable, role-based approval matrices with full audit trails.",
  },
  {
    icon: BarChart2,
    title: "Live Dashboards",
    desc: "Monitor income trends, supplier performance, and pending actions with real-time reporting.",
  },
];

const STATS = [
  { value: "200+", label: "Airlines" },
  { value: "50K+", label: "Deals Managed" },
  { value: "99.9%", label: "Uptime" },
];

/** AirYield wordmark + plane logo. */
function Logo({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className="w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: light ? "rgba(255,255,255,0.12)" : NAVY }}
      >
        <Plane className="w-5 h-5 text-white" />
      </div>
      <span className={`font-bold text-lg tracking-wide ${light ? "text-white" : "text-gray-900"}`}>
        AirYield
      </span>
    </div>
  );
}

export default function HomePage() {
  // Auth state is read from localStorage on the client only; gate on mount to
  // avoid a hydration mismatch between server and client markup.
  const [mounted, setMounted] = useState(false);
  const [authed, setAuthed]   = useState(false);

  useEffect(() => {
    setAuthed(isAuthenticated());
    setMounted(true);
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-white text-gray-900">
      {/* ── Top navigation ──────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo />

          <nav className="flex items-center gap-2 sm:gap-3">
            {mounted && authed ? (
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-1.5 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:opacity-90 transition-opacity"
                style={{ background: NAVY }}
              >
                Go to Dashboard <ArrowRight className="w-4 h-4" />
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-sm font-semibold text-gray-700 px-4 py-2 rounded-xl hover:bg-gray-100 transition-colors"
                >
                  Login
                </Link>
                <Link
                  href="/signup"
                  className="text-sm font-semibold text-white px-4 py-2 rounded-xl hover:opacity-90 transition-opacity"
                  style={{ background: NAVY }}
                >
                  Sign Up
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {/* ── Hero ────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 w-full pt-16 pb-20 sm:pt-24 sm:pb-28 text-center">
        <div
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
          style={{ background: "rgba(30,58,95,0.08)", color: NAVY }}
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          Airline incentive income, under control
        </div>

        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight leading-tight text-gray-900">
          The Airline Deal
          <br className="hidden sm:block" />
          <span style={{ color: NAVY }}> Management Platform</span>
        </h1>

        <p className="mt-5 text-base sm:text-lg text-gray-500 max-w-2xl mx-auto leading-relaxed">
          Manage airline contracts, track incentives, calculate income, and streamline
          approvals — all in one place.
        </p>

        {/* primary CTAs */}
        <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            href="/signup"
            className="inline-flex items-center justify-center gap-2 w-full sm:w-auto text-white text-sm font-semibold px-7 py-3.5 rounded-xl hover:opacity-90 transition-opacity"
            style={{ background: NAVY }}
          >
            Get Started <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            href="/login"
            className="inline-flex items-center justify-center w-full sm:w-auto text-sm font-semibold text-gray-700 px-7 py-3.5 rounded-xl border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            Sign in to your account
          </Link>
        </div>

        {/* feature pills */}
        <div className="mt-10 flex flex-wrap justify-center gap-2">
          {["Deal Tracking", "Income Calculation", "Approval Workflows", "B2B · B2C · B2E"].map((f) => (
            <span
              key={f}
              className="px-3 py-1 rounded-full text-xs font-medium"
              style={{ background: "rgba(30,58,95,0.06)", color: NAVY }}
            >
              {f}
            </span>
          ))}
        </div>
      </section>

      {/* ── Features ────────────────────────────────────────────────── */}
      <section className="border-t border-gray-100 bg-gray-50">
        <div className="max-w-6xl mx-auto px-6 py-16 sm:py-20">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
              Everything you need to manage airline income
            </h2>
            <p className="mt-3 text-sm text-gray-500 max-w-xl mx-auto">
              From contract to calculation to approval — AirYield brings your entire
              incentive workflow into a single system.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {FEATURES.map(({ icon: Icon, title, desc }) => (
              <div
                key={title}
                className="bg-white rounded-2xl border border-gray-200 p-6 hover:shadow-sm transition-shadow"
              >
                <div
                  className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                  style={{ background: "rgba(30,58,95,0.08)", color: NAVY }}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="font-semibold text-gray-900">{title}</h3>
                <p className="mt-1.5 text-sm text-gray-500 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA band with stats ─────────────────────────────────────── */}
      <section className="px-6 py-16 sm:py-20">
        <div
          className="max-w-6xl mx-auto rounded-3xl px-8 py-12 sm:px-14 sm:py-16 text-center"
          style={{ background: NAVY_GRADIENT }}
        >
          <h2 className="text-2xl sm:text-3xl font-bold text-white">
            Ready to streamline your airline deals?
          </h2>
          <p className="mt-3 text-blue-200 text-sm max-w-lg mx-auto">
            Create your account in minutes. The first person to sign up with a company
            email becomes the admin for their domain.
          </p>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 w-full sm:w-auto text-sm font-semibold px-7 py-3.5 rounded-xl bg-white text-[#1e3a5f] hover:opacity-90 transition-opacity"
            >
              Create your account <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center w-full sm:w-auto text-sm font-semibold px-7 py-3.5 rounded-xl border border-white/25 text-white hover:bg-white/10 transition-colors"
            >
              Login
            </Link>
          </div>

          <div className="mt-12 grid grid-cols-3 gap-4 max-w-md mx-auto pt-8 border-t border-white/10">
            {STATS.map((s) => (
              <div key={s.label}>
                <p className="text-2xl sm:text-3xl font-bold text-white">{s.value}</p>
                <p className="text-xs text-blue-300 mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer className="mt-auto border-t border-gray-100">
        <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <Logo />
          <p className="text-xs text-gray-400">© 2026 AirYield · All rights reserved</p>
          <div className="flex items-center gap-4 text-sm font-medium">
            <Link href="/login" className="text-gray-600 hover:text-gray-900 transition-colors">Login</Link>
            <Link href="/signup" className="text-gray-600 hover:text-gray-900 transition-colors">Sign Up</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
