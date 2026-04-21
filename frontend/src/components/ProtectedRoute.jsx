/**
 * ProtectedRoute.jsx
 * ------------------
 * Wraps any route that requires authentication.
 *
 * On mount:
 *   1. Checks for session token in sessionStorage
 *   2. Calls GET /api/auth/me to validate token is still valid on backend
 *   3. If valid: renders children + starts inactivity timer + token refresh loop
 *   4. If invalid/expired: redirects to / (login)
 *
 * Inactivity:
 *   - 30 seconds before timeout: shows a warning dialog with countdown
 *   - User can click "Stay logged in" to reset timer
 *   - At timeout: clears session + redirects to /
 *
 * Usage:
 *   <Route path="/home" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  isLoggedIn, getToken, getMobile, clearSession,
  startInactivityTimer, stopInactivityTimer,
  startTokenRefresh, stopTokenRefresh,
  resetInactivityTimer, WARNING_BEFORE_MS,
  SESSION_TIMEOUT_MS,
} from "@/lib/session";
import { Loader2 } from "lucide-react";
import { Button }  from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";

export default function ProtectedRoute({ children }) {
  const navigate = useNavigate();

  const [checking,      setChecking]      = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [showWarning,   setShowWarning]   = useState(false);
  const [countdown,     setCountdown]     = useState(Math.floor(WARNING_BEFORE_MS / 1000));

  const countdownRef = useRef(null);

  // ── Logout handler ────────────────────────────────────────────────────────

  const doLogout = useCallback(() => {
    clearSession();
    stopInactivityTimer();
    stopTokenRefresh();
    navigate("/", { replace: true });
  }, [navigate]);

  // ── Inactivity warning ────────────────────────────────────────────────────

  const showWarningDialog = useCallback(() => {
    setShowWarning(true);
    setCountdown(Math.floor(WARNING_BEFORE_MS / 1000));

    // Tick countdown display
    countdownRef.current = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(countdownRef.current);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
  }, []);

  const handleStayLoggedIn = useCallback(() => {
    setShowWarning(false);
    clearInterval(countdownRef.current);
    resetInactivityTimer();
  }, []);

  // ── Validate session on mount ─────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;

    async function validate() {
      if (!isLoggedIn()) {
        navigate("/", { replace: true });
        return;
      }

      try {
        const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${getToken()}` },
        });

        if (cancelled) return;

        if (!res.ok) {
          clearSession();
          navigate("/", { replace: true });
          return;
        }

        // Valid session — start timers
        setAuthenticated(true);
        setChecking(false);

        startTokenRefresh();
        startInactivityTimer(showWarningDialog, doLogout);

      } catch {
        if (!cancelled) {
          // Network error — still allow if token exists (offline resilience)
          setAuthenticated(true);
          setChecking(false);
          startTokenRefresh();
          startInactivityTimer(showWarningDialog, doLogout);
        }
      }
    }

    validate();

    return () => {
      cancelled = true;
      stopInactivityTimer();
      stopTokenRefresh();
      clearInterval(countdownRef.current);
    };
  }, [navigate, showWarningDialog, doLogout]);

  // ── Loading ───────────────────────────────────────────────────────────────

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 to-emerald-50">
        <div className="text-center space-y-3">
          <Loader2 className="w-10 h-10 animate-spin text-emerald-500 mx-auto" />
          <p className="text-gray-500 text-sm">Checking session…</p>
        </div>
      </div>
    );
  }

  if (!authenticated) return null;

  return (
    <>
      {children}

      {/* ── Inactivity warning dialog ── */}
      <Dialog open={showWarning} onOpenChange={() => {}}>
        <DialogContent
          className="max-w-sm"
          onInteractOutside={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle className="text-amber-600">
              Still there?
            </DialogTitle>
          </DialogHeader>
          <div className="py-2">
            <p className="text-gray-700 text-sm">
              You'll be logged out in{" "}
              <span className="font-bold text-amber-600 text-lg">{countdown}s</span>{" "}
              due to inactivity.
            </p>
            <p className="text-gray-500 text-xs mt-1">
              Any unsaved progress will be lost.
            </p>
          </div>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={doLogout}
              className="text-gray-500"
            >
              Log Out
            </Button>
            <Button
              onClick={handleStayLoggedIn}
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
              autoFocus
            >
              Stay Logged In
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
