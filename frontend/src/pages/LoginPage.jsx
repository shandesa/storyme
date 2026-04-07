import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Sparkles, Phone, Lock, ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { sendOtp, loginWithPassword } from "@/api/auth";

// ─── constants ────────────────────────────────────────────────────────────────

const MODE = { OTP: "otp", PASSWORD: "password" };

// ─── component ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate();

  const [mobile, setMobile]   = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode]       = useState(MODE.OTP);
  const [loading, setLoading] = useState(false);

  // ── helpers ────────────────────────────────────────────────────────────────

  const handleMobileChange = (e) => {
    // Strip non-digits, max 10
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

  // ── OTP mode ───────────────────────────────────────────────────────────────

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

  // ── Password mode ──────────────────────────────────────────────────────────

  const handleLoginPassword = async (e) => {
    e.preventDefault();
    if (!validateMobile()) return;
    if (!password.trim()) {
      toast.error("Please enter your password");
      return;
    }

    setLoading(true);
    const result = await loginWithPassword(mobile, password);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Login failed");
      return;
    }

    toast.success("Welcome back!");
    navigate("/home");
  };

  // ── render ─────────────────────────────────────────────────────────────────

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
                  {/* Country code badge */}
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

              {/* Password field — only shown in password mode */}
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
                ) : (
                  mode === MODE.OTP ? (
                    <Phone className="mr-2 h-4 w-4" />
                  ) : (
                    <ArrowRight className="mr-2 h-4 w-4" />
                  )
                )}
                {loading
                  ? "Please wait…"
                  : mode === MODE.OTP
                  ? "Send OTP"
                  : "Login"}
              </Button>
            </form>

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
