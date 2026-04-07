import { useState, useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BookOpen, Sparkles, Loader2, RotateCcw, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { verifyOtp, sendOtp } from "@/api/auth";

// ─── constants ────────────────────────────────────────────────────────────────

const RESEND_COOLDOWN_SEC = 30;

// ─── component ────────────────────────────────────────────────────────────────

export default function OtpPage() {
  const location = useLocation();
  const navigate  = useNavigate();

  // Recover mobile from navigation state; if missing, send back to login
  const mobile = location.state?.mobile ?? null;

  const [otp, setOtp]         = useState("");
  const [loading, setLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const timerRef = useRef(null);

  // Guard: if no mobile state, redirect to login
  useEffect(() => {
    if (!mobile) {
      toast.error("Session expired. Please start again.");
      navigate("/", { replace: true });
    }
  }, [mobile, navigate]);

  // Cooldown countdown
  useEffect(() => {
    if (cooldown <= 0) return;
    timerRef.current = setInterval(() => {
      setCooldown((c) => {
        if (c <= 1) {
          clearInterval(timerRef.current);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [cooldown]);

  // ── verify ─────────────────────────────────────────────────────────────────

  const handleVerify = async (e) => {
    e.preventDefault();

    const trimmed = otp.trim();
    if (trimmed.length !== 6) {
      toast.error("Please enter the 6-digit OTP");
      return;
    }

    setLoading(true);
    const result = await verifyOtp(mobile, trimmed);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Invalid OTP. Please try again.");
      return;
    }

    if (result.data?.status === "NEW_USER") {
      toast.success("Welcome! Let's set up your account.");
      navigate("/register", { state: { mobile } });
    } else {
      toast.success("Welcome back!");
      navigate("/home");
    }
  };

  // ── resend ─────────────────────────────────────────────────────────────────

  const handleResend = async () => {
    if (cooldown > 0) return;

    const result = await sendOtp(mobile);

    if (result.error) {
      toast.error(result.message || "Failed to resend OTP");
      return;
    }

    // Surface OTP in dev/simulated mode
    if (result.data?.otp) {
      toast.info(`[Dev] New OTP: ${result.data.otp}`, { duration: 30_000 });
    } else {
      toast.success("A new OTP has been sent");
    }

    setCooldown(RESEND_COOLDOWN_SEC);
    setOtp("");
  };

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 flex items-center justify-center py-8 px-4">
      <div className="w-full max-w-md">

        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-3">
            <BookOpen className="w-9 h-9 text-emerald-600" />
            <h1 className="text-4xl font-bold text-gray-900 tracking-tight">StoryMe</h1>
            <Sparkles className="w-7 h-7 text-amber-500" />
          </div>
        </div>

        {/* OTP card */}
        <Card className="shadow-lg border-emerald-100">
          <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
            <CardTitle className="text-xl text-gray-800">Enter OTP</CardTitle>
            <CardDescription>
              We sent a 6-digit code to{" "}
              <span className="font-semibold text-gray-700">+91 {mobile}</span>
            </CardDescription>
          </CardHeader>

          <CardContent className="pt-6">
            <form onSubmit={handleVerify} className="space-y-5">
              {/* OTP input */}
              <div className="space-y-1.5">
                <Label htmlFor="otp" className="text-gray-700 font-medium">
                  One-Time Password
                </Label>
                <Input
                  id="otp"
                  data-testid="otp-input"
                  type="text"
                  inputMode="numeric"
                  placeholder="123456"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  maxLength={6}
                  className="border-gray-300 text-center text-2xl tracking-[0.4em] font-mono"
                  autoFocus
                />
                <p className="text-xs text-gray-400">
                  💡 In simulated mode, check the server console or look for the toast notification above.
                </p>
              </div>

              {/* Verify */}
              <Button
                type="submit"
                data-testid="verify-otp-btn"
                disabled={loading || otp.length !== 6}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold"
              >
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {loading ? "Verifying…" : "Verify OTP"}
              </Button>
            </form>

            {/* Resend + back */}
            <div className="mt-5 flex items-center justify-between text-sm">
              <button
                type="button"
                onClick={() => navigate("/", { replace: true })}
                className="flex items-center gap-1 text-gray-400 hover:text-gray-600"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back
              </button>

              <button
                type="button"
                data-testid="resend-otp-btn"
                onClick={handleResend}
                disabled={cooldown > 0}
                className={[
                  "flex items-center gap-1 font-medium",
                  cooldown > 0
                    ? "text-gray-400 cursor-not-allowed"
                    : "text-emerald-600 hover:text-emerald-700",
                ].join(" ")}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend OTP"}
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
