/**
 * Auth API client for StoryMe
 * ============================
 * Calls go directly to the Azure App Service backend (REACT_APP_BACKEND_URL).
 * Azure SWA has no API functions (api_location is empty), so relative /api/*
 * paths return 405 Method Not Allowed — all auth calls must be absolute.
 *
 * credentials: "omit" — the auth API returns JSON tokens, not cookies.
 * Using "include" cross-origin would force the browser to reject wildcard
 * CORS responses (spec prohibits Allow-Origin:* + Allow-Credentials:true).
 *
 * Cold-start resilience:
 *   Azure App Service B1 takes 3–5 minutes to cold-start because the portal
 *   appCommandLine runs `apt-get install` before starting gunicorn. During
 *   this window every fetch() throws "Failed to fetch" (connection refused,
 *   not a timeout). We handle this with:
 *
 *   1. Per-attempt timeout: ATTEMPT_TIMEOUT_MS (30s) — aborts a hanging
 *      request so we can retry rather than block the UI indefinitely.
 *   2. Retry loop: up to MAX_ATTEMPTS retries with RETRY_DELAY_MS back-off.
 *      Total wait ceiling ≈ 30s × 8 attempts + back-off ≈ 5 minutes — enough
 *      to cover the longest observed cold-start.
 *   3. Caller-facing messages distinguish "timeout/starting up" from genuine
 *      network errors.
 *
 * Simulated OTP:
 *   The backend returns the generated OTP in the response body for demo /
 *   development mode. Remove the `otp` field when real SMS is wired up.
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";

// Session utilities — imported lazily to avoid circular deps
// saveSession(token, mobile) stores in sessionStorage
async function _saveSession(token, mobile) {
  try {
    const { saveSession } = await import("@/lib/session");
    saveSession(token, mobile);
  } catch { /* non-fatal */ }
}
const AUTH_BASE   = `${BACKEND_URL}/api/auth`;

// Per-attempt hard timeout. If a single attempt takes longer than this,
// abort it and retry (don't block the UI for multiple minutes on one call).
const ATTEMPT_TIMEOUT_MS = 30_000;

// Retry configuration for cold-start resilience.
// Total ceiling ≈ MAX_ATTEMPTS × ATTEMPT_TIMEOUT_MS + cumulative back-off ≈ 5 min.
const MAX_ATTEMPTS    = 8;
const RETRY_DELAY_MS  = 3_000; // base delay between retries (increases linearly)

/**
 * Determine whether an error is a transient network/startup error that
 * warrants a retry, vs a definitive failure (4xx, invalid JSON, etc.)
 */
function isRetryable(err) {
  // AbortError = our own timeout — server may still be starting up, retry
  if (err && err.name === "AbortError") return true;
  // TypeError "Failed to fetch" = connection refused / no server yet, retry
  if (err instanceof TypeError) return true;
  return false;
}

/**
 * POST to an auth endpoint with per-attempt timeout and cold-start retry.
 *
 * Returns:
 *   { data }             — on HTTP 2xx
 *   { error, status, message } — on HTTP 4xx/5xx or exhausted retries
 */
async function post(path, body) {
  let lastErr = null;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), ATTEMPT_TIMEOUT_MS);

    try {
      const res = await fetch(`${AUTH_BASE}${path}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "omit",
        signal:  controller.signal,
        body:    JSON.stringify(body),
      });

      clearTimeout(tid);

      let data = null;
      try { data = await res.json(); } catch { /* empty body */ }

      if (!res.ok) {
        // HTTP error — do NOT retry 4xx (bad request, wrong OTP, etc.)
        return {
          error:   true,
          status:  res.status,
          message: data?.detail || data?.message || `Request failed (${res.status})`,
        };
      }

      return { data };

    } catch (err) {
      clearTimeout(tid);
      lastErr = err;

      if (!isRetryable(err)) {
        // Definitive failure — no point retrying
        console.error(`Auth ${path} non-retryable error:`, err);
        break;
      }

      const isTimeout = err.name === "AbortError";
      console.warn(
        `Auth ${path} attempt ${attempt}/${MAX_ATTEMPTS} failed` +
        ` (${isTimeout ? "timeout" : "connection refused"}).` +
        (attempt < MAX_ATTEMPTS ? ` Retrying in ${RETRY_DELAY_MS * attempt}ms…` : " Giving up.")
      );

      if (attempt < MAX_ATTEMPTS) {
        // Linear back-off: 3s, 6s, 9s, … so later retries space out naturally
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * attempt));
      }
    }
  }

  // All attempts exhausted — build a user-friendly message
  const isTimeout = lastErr && lastErr.name === "AbortError";
  const isConnRefused = lastErr instanceof TypeError;

  let message;
  if (isTimeout || isConnRefused) {
    message =
      "The server is still starting up — this can take up to 5 minutes on first use. " +
      "Please try again in a moment.";
  } else {
    message = lastErr?.message || "Network error — check your connection and try again.";
  }

  console.error(`Auth ${path} failed after ${MAX_ATTEMPTS} attempts:`, lastErr);
  return { error: true, status: 0, message };
}


// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Send OTP to mobile number.
 * Returns { data: { message, otp? } }
 * `otp` is only present in simulated / dev mode.
 */
export async function sendOtp(mobile) {
  return post("/send-otp", { mobile });
}

/**
 * Verify OTP.
 * Returns:
 *   NEW_USER  → { data: { status: "NEW_USER" } }
 *   EXISTING  → { data: { status: "LOGIN_SUCCESS", user: {...} } }
 */
export async function verifyOtp(mobile, otp) {
  const result = await post("/verify-otp", { mobile, otp });
  // If existing user, backend returns a token — save it immediately
  if (!result.error && result.data?.token) {
    await _saveSession(result.data.token, mobile);
  }
  return result;
}

/**
 * Password-based login.
 * Returns { data: { status: "LOGIN_SUCCESS", user: {...} } }
 */
export async function loginWithPassword(mobile, password) {
  const result = await post("/login-password", { mobile, password });
  if (!result.error && result.data?.token) {
    await _saveSession(result.data.token, mobile);
  }
  return result;
}

/**
 * Register a new user.
 * Returns { data: { status: "REGISTERED", user: {...} } }
 */
export async function register(mobile, password, displayName = "") {
  const result = await post("/register", { mobile, password, display_name: displayName });
  if (!result.error && result.data?.token) {
    await _saveSession(result.data.token, mobile);
  }
  return result;
}

/**
 * Record the user's Terms & Conditions decision.
 * accepted=true  → { data: { status: "TERMS_ACCEPTED", user: {...} } }
 * accepted=false → { data: { status: "TERMS_REJECTED" } }
 */
export async function acceptTerms(mobile, accepted) {
  return post("/accept-terms", { mobile, accepted });
}
