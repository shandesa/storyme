import { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BookOpen, Sparkles, Loader2, Lock, Eye, EyeOff, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { register } from "@/api/auth";

// ─── helpers ──────────────────────────────────────────────────────────────────

function PasswordStrength({ password }) {
  const strength = (() => {
    if (!password) return 0;
    let score = 0;
    if (password.length >= 8)           score++;
    if (/[A-Z]/.test(password))        score++;
    if (/[0-9]/.test(password))        score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    return score;
  })();

  const labels = ["", "Weak", "Fair", "Good", "Strong"];
  const colours = ["", "bg-red-400", "bg-amber-400", "bg-blue-400", "bg-emerald-500"];

  if (!password) return null;

  return (
    <div className="space-y-1 mt-1">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((n) => (
          <div
            key={n}
            className={[
              "h-1 flex-1 rounded-full transition-colors",
              n <= strength ? colours[strength] : "bg-gray-200",
            ].join(" ")}
          />
        ))}
      </div>
      <p className={`text-xs ${strength <= 1 ? "text-red-500" : strength <= 2 ? "text-amber-600" : "text-emerald-600"}`}>
        {labels[strength]}
      </p>
    </div>
  );
}

// ─── component ────────────────────────────────────────────────────────────────

export default function RegisterPage() {
  const location = useLocation();
  const navigate  = useNavigate();

  const mobile = location.state?.mobile ?? null;

  const [password, setPassword]   = useState("");
  const [confirm, setConfirm]     = useState("");
  const [showPw, setShowPw]       = useState(false);
  const [showCf, setShowCf]       = useState(false);
  const [loading, setLoading]     = useState(false);

  // Guard
  useEffect(() => {
    if (!mobile) {
      toast.error("Session expired. Please start again.");
      navigate("/", { replace: true });
    }
  }, [mobile, navigate]);

  const handleRegister = async (e) => {
    e.preventDefault();

    if (password.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }
    if (password !== confirm) {
      toast.error("Passwords do not match");
      return;
    }

    setLoading(true);
    const result = await register(mobile, password);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Registration failed");
      return;
    }

    toast.success("Account created! Welcome to StoryMe 🎉");
    navigate("/home");
  };

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

        {/* Register card */}
        <Card className="shadow-lg border-emerald-100">
          <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
            <CardTitle className="text-xl text-gray-800">Create Your Account</CardTitle>
            <CardDescription>
              You're new here! Set a password for{" "}
              <span className="font-semibold text-gray-700">+91 {mobile}</span>
            </CardDescription>
          </CardHeader>

          <CardContent className="pt-6">
            <form onSubmit={handleRegister} className="space-y-5">

              {/* Password */}
              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-gray-700 font-medium">
                  Create Password
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <Input
                    id="password"
                    data-testid="new-password-input"
                    type={showPw ? "text" : "password"}
                    placeholder="Minimum 6 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="border-gray-300 pl-10 pr-10"
                    autoFocus
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <PasswordStrength password={password} />
              </div>

              {/* Confirm password */}
              <div className="space-y-1.5">
                <Label htmlFor="confirm" className="text-gray-700 font-medium">
                  Confirm Password
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <Input
                    id="confirm"
                    data-testid="confirm-password-input"
                    type={showCf ? "text" : "password"}
                    placeholder="Repeat your password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    className={[
                      "border-gray-300 pl-10 pr-10",
                      confirm && confirm !== password ? "border-red-400" : "",
                    ].join(" ")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowCf((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showCf ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {confirm && confirm !== password && (
                  <p className="text-xs text-red-500">Passwords don't match</p>
                )}
              </div>

              {/* Submit */}
              <Button
                type="submit"
                data-testid="register-btn"
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold"
              >
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {loading ? "Creating account…" : "Create Account"}
              </Button>
            </form>

            <div className="mt-4 text-center">
              <button
                type="button"
                onClick={() => navigate("/", { replace: true })}
                className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-600 mx-auto"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back to login
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
