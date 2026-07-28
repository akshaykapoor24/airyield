"use client";

// First-login blocking wizard: User Info -> Entities -> Login IDs. Entities and
// Login IDs are skippable (they can be added later from My Profile). On finish
// it marks onboarding complete and refreshes the auth user.

import { useRef, useState } from "react";
import { User, Building2, KeyRound, Check, ArrowLeft, ArrowRight } from "lucide-react";
import api from "@/lib/api";
import { useAppDispatch } from "@/store/hooks";
import { fetchMe } from "@/store/slices/authSlice";
import { apiError } from "@/components/userMaster/shared";
import ProfileInfoSection, { type ProfileInfoHandle } from "@/components/profile/ProfileInfoSection";
import EntitiesSection from "@/components/profile/EntitiesSection";
import LoginIdsSection from "@/components/profile/LoginIdsSection";

const STEPS = [
  { key: "info", label: "Your Info", icon: User, hint: "Review and complete your account details." },
  { key: "entities", label: "Entities", icon: Building2, hint: "Add your billing / legal entities. You can skip and add these later." },
  { key: "logins", label: "Login IDs / IATA", icon: KeyRound, hint: "Add airline login IDs / IATA codes and link them to an entity. Skippable." },
];

export default function OnboardingWizard({ onComplete }: { onComplete: () => void }) {
  const dispatch = useAppDispatch();
  const profileRef = useRef<ProfileInfoHandle>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const isLast = step === STEPS.length - 1;

  const next = async () => {
    setError("");
    if (step === 0) {
      setBusy(true);
      const ok = await profileRef.current?.save();
      setBusy(false);
      if (!ok) return;
    }
    setStep(s => Math.min(s + 1, STEPS.length - 1));
  };

  const finish = async () => {
    setError(""); setBusy(true);
    try {
      await api.post("/users/me/complete-onboarding");
      await dispatch(fetchMe());
      onComplete();
    } catch (e) { setError(apiError(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden">
        {/* header */}
        <div className="px-6 py-5 border-b border-gray-100" style={{ background: "linear-gradient(135deg, #1e3a5f 0%, #1e4d8c 60%, #1a3f7a 100%)" }}>
          <h2 className="text-white text-lg font-bold">Welcome to AirYield 👋</h2>
          <p className="text-white/70 text-xs mt-0.5">Let&apos;s set up your workspace — this only takes a minute.</p>

          {/* stepper */}
          <div className="flex items-center gap-2 mt-4">
            {STEPS.map((s, i) => {
              const done = i < step;
              const active = i === step;
              return (
                <div key={s.key} className="flex items-center gap-2 flex-1">
                  <div className={`flex items-center gap-2 ${i === 0 ? "" : "flex-1"}`}>
                    {i !== 0 && <div className={`h-0.5 flex-1 rounded ${done || active ? "bg-sky-300" : "bg-white/20"}`} />}
                    <div className={`flex items-center gap-1.5 whitespace-nowrap ${active ? "text-white" : done ? "text-sky-200" : "text-white/40"}`}>
                      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold border ${
                        active ? "bg-sky-400 border-sky-400 text-white"
                        : done ? "bg-sky-300/20 border-sky-300 text-sky-200"
                        : "border-white/30 text-white/50"}`}>
                        {done ? <Check className="w-3.5 h-3.5" /> : i + 1}
                      </span>
                      <span className="text-[11px] font-semibold">{s.label}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* body */}
        <div className="px-6 py-5 overflow-y-auto flex-1 bg-gray-50">
          <p className="text-xs text-gray-500 mb-3">{STEPS[step].hint}</p>
          {step === 0 && <ProfileInfoSection ref={profileRef} hideSaveButton />}
          {step === 1 && <EntitiesSection />}
          {step === 2 && <LoginIdsSection />}
          {error && <p className="text-[11px] text-red-500 mt-3">{error}</p>}
        </div>

        {/* footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between bg-white">
          <button
            onClick={() => setStep(s => Math.max(0, s - 1))}
            disabled={step === 0 || busy}
            className="flex items-center gap-1.5 text-sm text-gray-600 px-3 py-2 rounded-lg hover:bg-gray-100 disabled:opacity-40">
            <ArrowLeft className="w-4 h-4" /> Back
          </button>

          <div className="flex items-center gap-2">
            {step > 0 && !isLast && (
              <button onClick={() => setStep(s => s + 1)} disabled={busy}
                className="text-sm text-gray-500 px-3 py-2 rounded-lg hover:bg-gray-100 disabled:opacity-40">
                Skip for now
              </button>
            )}
            {isLast ? (
              <button onClick={finish} disabled={busy}
                className="flex items-center gap-1.5 text-white px-5 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                style={{ background: "#1e3a5f" }}>
                {busy ? "Finishing…" : "Finish setup"} <Check className="w-4 h-4" />
              </button>
            ) : (
              <button onClick={next} disabled={busy}
                className="flex items-center gap-1.5 text-white px-5 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                style={{ background: "#1e3a5f" }}>
                {busy ? "Saving…" : "Next"} <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
