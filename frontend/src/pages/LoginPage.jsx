import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Sparkles, Phone, Lock, ArrowRight, Loader2, Wifi, WifiOff } from "lucide-react";
import { toast } from "sonner";

import { Button }   from "@/components/ui/button";
import { Input }    from "@/components/ui/input";
import { Label }    from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { sendOtp, loginWithPassword } from "@/api/auth";
import { startWarmup, WarmupStatus }  from "@/api/warmup";

// ─── constants ────────────────────────────────────────────────────────────────

const MODE = { OTP: "otp", PASSWORD: "password" };

// ─── component ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate();

  const [mobile,   setMobile]   = useState("");
  const [password, setPassword] = useState("");
  const [mode,     setMode]     = useState(MODE.OTP);
  const [loading,  setLoading]  = useState(false);

  // ── Server warm-up state ────────────────────────────────────────────────────
  // Azure App Service cold starts take 3–5 min (apt-get runs on every restart).
  // We poll /health on mount so the user's first button press hits a live server.
  const [warmup,        setWarmup]        = useState(WarmupStatus.IDLE);
  const [warmupElapsed, setWarmupElapsed] = useState(0);
  const warmupRef = useRef(null);

  useEffect(() => {
    const handle = startWarmup((status, elapsed) => {
      setWarmup(status);
      setWarmupElapsed(elapsed);

      if (status === WarmupStatus.READY) {
        // Only show the toast the first time (not on every poll)
        toast.success("Server is ready!", { duration: 3_000 });
      }
    });

    warmupRef.current = handle;
    return () => handle.stop();
  }, []);

  // ── helpers ─────────────────────────────────────────────────────────────────

  const handleMobileChange = (e) => {
    const digits = e.target.value.replace(/\D/g, "").slice(0, 10);
    setMobile(digits);
  };

  const validateMobile = () => {
    if (mobile.length !== 10) {
      toast.error("Please enter a valid 10-digit mobile number");
      return false;
    }
    return true;
  };

  // ── OTP mode ────────────────────────────────────────────────────────────────

  const handleSendOtp = async (e) => {
    e.preventDefault();
    if (!validateMobile()) return;

    setLoading(true);
    const result = await sendOtp(mobile);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Failed to send OTP");
      return;
    }

    // Simulated OTP: backend may return the OTP for dev/testing convenience
    if (result.data?.otp) {
      toast.info(`[Dev] Your OTP is: ${result.data.otp}`, { duration: 30_000 });
    } else {
      toast.success("OTP sent to your mobile number");
    }

    navigate("/otp", { state: { mobile } });
  };

  // ── Password mode ────────────────────────────────────────────────────────────

  const handleLoginPassword = async (e) => {
    e.preventDefault();
    if (!validateMobile()) return;
    if (!password.trim()) { toast.error("Please enter your password"); return; }

    setLoading(true);
    const result = await loginWithPassword(mobile, password);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Login failed");
      return;
    }

    const user = result.data?.user;
    toast.success("Welcome back!");
    if (!user?.terms_accepted) {
      navigate("/terms", { state: { mobile } });
    } else {
      navigate("/home");
    }
  };

  // ── Warm-up banner ───────────────────────────────────────────────────────────
  // Show a non-intrusive status pill below the form while the server warms up.

  const elapsedSec = Math.floor(warmupElapsed / 1_000);

  const WarmupBanner = () => {
    if (warmup === WarmupStatus.IDLE || warmup === WarmupStatus.READY) return null;

    if (warmup === WarmupStatus.TIMEOUT) {
      return (
        <div className="flex items-center gap-2 mt-4 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-xs">
          <WifiOff className="w-3.5 h-3.5 shrink-0" />
          <span>
            Server is taking longer than expected to start. You can still try —
            your request will wait up to 5 minutes.
          </span>
        </div>
      );
    }

    // POLLING state
    return (
      <div className="flex items-center gap-2 mt-4 px-3 py-2 rounded-lg bg-blue-50 border border-blue-200 text-blue-700 text-xs">
        <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin" />
        <span>
          Server is warming up{elapsedSec > 0 ? ` (${elapsedSec}s)` : ""}…
          You can still tap Send OTP — your request will wait.
        </span>
      </div>
    );
  };

  // ── render ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 flex items-center justify-center py-8 px-4">
      <div className="w-full max-w-md">

        {/* Brand header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-3">
            <BookOpen className="w-9 h-9 text-emerald-600" />
            <h1 className="text-4xl font-bold text-gray-900 tracking-tight">StoryMe</h1>
            <Sparkles className="w-7 h-7 text-amber-500" />
          </div>
          <p className="text-base text-gray-500">AI-powered personalised storybooks for your child</p>
        </div>

        {/* Login card */}
        <Card className="shadow-lg border-emerald-100">
          <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
            <CardTitle className="text-xl text-gray-800">
              {mode === MODE.OTP ? "Login with OTP" : "Login with Password"}
            </CardTitle>
            <CardDescription>
              {mode === MODE.OTP
                ? "Enter your mobile number and we'll send you a one-time password"
                : "Enter your mobile number and password"}
            </CardDescription>
          </CardHeader>

          <CardContent className="pt-6">
            <form
              onSubmit={mode === MODE.OTP ? handleSendOtp : handleLoginPassword}
              className="space-y-5"
            >
              {/* Mobile field */}
              <div className="space-y-1.5">
                <Label htmlFor="mobile" className="text-gray-700 font-medium">
                  Mobile Number
                </Label>
                <div className="flex gap-2">
                  <span className="inline-flex items-center px-3 rounded-md border border-gray-300 bg-gray-50 text-gray-500 text-sm select-none">
                    🇮🇳 +91
                  </span>
                  <Input
                    id="mobile"
                    data-testid="mobile-input"
                    type="tel"
                    inputMode="numeric"
                    placeholder="9876543210"
                    value={mobile}
                    onChange={handleMobileChange}
                    maxLength={10}
                    className="border-gray-300 flex-1"
                    autoFocus
                  />
                </div>
              </div>

              {/* Password field — only in password mode */}
              {mode === MODE.PASSWORD && (
                <div className="space-y-1.5">
                  <Label htmlFor="password" className="text-gray-700 font-medium">
                    Password
                  </Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <Input
                      id="password"
                      data-testid="password-input"
                      type="password"
                      placeholder="Enter your password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="border-gray-300 pl-10"
                    />
                  </div>
                </div>
              )}

              {/* Submit */}
              <Button
                type="submit"
                data-testid="login-submit-btn"
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold"
              >
                {loading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : mode === MODE.OTP ? (
                  <Phone className="mr-2 h-4 w-4" />
                ) : (
                  <ArrowRight className="mr-2 h-4 w-4" />
                )}
                {loading
                  ? "Please wait…"
                  : mode === MODE.OTP
                  ? "Send OTP"
                  : "Login"}
              </Button>
            </form>

            {/* Warm-up status banner */}
            <WarmupBanner />

            {/* Mode toggle */}
            <div className="mt-5 text-center text-sm text-gray-500">
              <button
                type="button"
                data-testid="toggle-mode-btn"
                onClick={() => setMode(mode === MODE.OTP ? MODE.PASSWORD : MODE.OTP)}
                className="text-emerald-600 hover:text-emerald-700 font-medium underline-offset-2 hover:underline"
              >
                {mode === MODE.OTP
                  ? "Login with password instead"
                  : "Login with OTP instead"}
              </button>
            </div>
          </CardContent>
        </Card>

        {/* Footer note */}
        <p className="text-center text-xs text-gray-400 mt-6">
          New here? You'll be prompted to create an account after OTP verification.
        </p>
      </div>
    </div>
  );
}
