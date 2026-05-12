"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, Building2, CheckCircle2 } from "lucide-react";
import { setToken, setUser } from "@/lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const [fullName,     setFullName]     = useState("");
  const [email,        setEmail]        = useState("");
  const [companyName,  setCompanyName]  = useState("");
  const [password,     setPassword]     = useState("");
  const [confirm,      setConfirm]      = useState("");
  const [showPw,       setShowPw]       = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState("");
  const [domainNote,   setDomainNote]   = useState("");

  // live domain detection
  const handleEmailChange = (v: string) => {
    setEmail(v);
    setError("");
    const parts = v.split("@");
    if (parts.length === 2 && parts[1].includes(".")) {
      setDomainNote(`Domain: ${parts[1]} — you will be the admin for this domain.`);
    } else {
      setDomainNote("");
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!fullName || !email || !password || !confirm) {
      setError("Please fill in all required fields."); return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters."); return;
    }
    if (password !== confirm) {
      setError("Passwords do not match."); return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name:    fullName,
          email,
          password,
          company_name: companyName || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Signup failed. Please try again.");
        return;
      }
      setToken(data.access_token);
      setUser(data.user);
      router.push("/");
    } catch {
      setError("Cannot reach server. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md">
      {/* mobile logo */}
      <div className="lg:hidden flex items-center gap-2 mb-8">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "#1e3a5f" }}>
          <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
            <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
          </svg>
        </div>
        <span className="font-bold text-gray-900">AirYield</span>
      </div>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Create your account</h1>
        <p className="text-sm text-gray-500 mt-1">You'll be the admin for your company domain</p>
      </div>

      {/* admin info banner */}
      <div className="flex items-start gap-2.5 bg-blue-50 border border-blue-200 rounded-xl px-3.5 py-2.5 mb-5">
        <Building2 className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5"/>
        <p className="text-[11px] text-blue-700 leading-snug">
          <span className="font-semibold">One admin per domain.</span>{" "}
          The first person to sign up with a company email becomes the admin.
          Other team members must be added by the admin from User Management.
        </p>
      </div>

      <form onSubmit={handleSignup} className="space-y-3.5">
        {/* full name */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Full Name *</label>
          <input
            type="text"
            value={fullName}
            onChange={e => setFullName(e.target.value)}
            placeholder="e.g. Rajesh Kumar"
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
          />
        </div>

        {/* email */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Work Email *</label>
          <input
            type="email"
            value={email}
            onChange={e => handleEmailChange(e.target.value)}
            placeholder="you@yourcompany.com"
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
          />
          {domainNote && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-green-500"/>
              <p className="text-[11px] text-green-600 font-medium">{domainNote}</p>
            </div>
          )}
        </div>

        {/* company name */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">
            Company Name <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={companyName}
            onChange={e => setCompanyName(e.target.value)}
            placeholder="e.g. Yatra Online Pvt Ltd"
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
          />
        </div>

        {/* password */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Password *</label>
          <div className="relative">
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Min 8 characters"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
            />
            <button type="button" onClick={() => setShowPw(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              {showPw ? <EyeOff className="w-4 h-4"/> : <Eye className="w-4 h-4"/>}
            </button>
          </div>
        </div>

        {/* confirm */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Confirm Password *</label>
          <input
            type="password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            placeholder="Re-enter your password"
            className={`w-full border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 transition-colors ${
              confirm && confirm !== password
                ? "border-red-300 focus:ring-red-200"
                : "border-gray-200 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f]"
            }`}
          />
          {confirm && confirm !== password && (
            <p className="text-[11px] text-red-500 mt-1">Passwords do not match</p>
          )}
        </div>

        {/* error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 text-xs text-red-600 leading-snug">
            {error}
          </div>
        )}

        {/* submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full text-white py-3 rounded-xl font-semibold text-sm hover:opacity-90 disabled:opacity-60 transition-all"
          style={{ background: "#1e3a5f" }}>
          {loading ? "Creating account..." : "Create Account"}
        </button>
      </form>

      <p className="text-center text-sm text-gray-600 mt-5">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-[#1e3a5f] hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
