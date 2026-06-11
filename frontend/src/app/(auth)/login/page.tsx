"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { useAppDispatch } from "@/store/hooks";
import { login } from "@/store/slices/authSlice";

export default function LoginPage() {
  const router   = useRouter();
  const dispatch = useAppDispatch();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email || !password) { setError("Please enter email and password."); return; }
    setLoading(true);
    const result = await dispatch(login({ username: email, password }));
    setLoading(false);
    if (login.rejected.match(result)) {
      setError((result.payload as string) ?? "Login failed. Please try again.");
      return;
    }
    router.push("/");
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

      <div className="mb-7">
        <h1 className="text-2xl font-bold text-gray-900">Welcome back</h1>
        <p className="text-sm text-gray-500 mt-1">Sign in to your AirYield account</p>
      </div>

      <form onSubmit={handleLogin} className="space-y-4">
        {/* email */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1.5">Email address</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@company.com"
            className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
          />
        </div>

        {/* password */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-semibold text-gray-700">Password</label>
            <a href="#" className="text-xs text-[#1e3a5f] hover:underline">Forgot password?</a>
          </div>
          <div className="relative">
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 focus:border-[#1e3a5f] transition-colors"
            />
            <button type="button" onClick={() => setShowPw(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              {showPw ? <EyeOff className="w-4 h-4"/> : <Eye className="w-4 h-4"/>}
            </button>
          </div>
        </div>

        {/* error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 text-xs text-red-600">
            {error}
          </div>
        )}

        {/* submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full text-white py-3 rounded-xl font-semibold text-sm hover:opacity-90 disabled:opacity-60 transition-all mt-1"
          style={{ background: "#1e3a5f" }}>
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>

      {/* divider */}
      <div className="flex items-center gap-3 my-5">
        <div className="flex-1 h-px bg-gray-200"/>
        <span className="text-xs text-gray-400">or</span>
        <div className="flex-1 h-px bg-gray-200"/>
      </div>

      {/* signup link */}
      <p className="text-center text-sm text-gray-600">
        New to AirYield?{" "}
        <Link href="/signup" className="font-semibold text-[#1e3a5f] hover:underline">
          Create an account
        </Link>
      </p>

      <p className="text-center text-[11px] text-gray-400 mt-6">
        By signing in you agree to our Terms of Service and Privacy Policy.
      </p>
    </div>
  );
}
