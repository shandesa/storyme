/**
 * Auth API client for StoryMe
 *
 * Calls go directly to the Azure App Service backend using REACT_APP_BACKEND_URL.
 * Azure SWA has no API functions (api_location is empty) so relative /api/* paths
 * return 405 Method Not Allowed.
 *
 * credentials: "omit" — the auth API returns JSON (not cookies/sessions).
 * Cross-origin cookie sharing is unnecessary here and was causing CORS preflight
 * failures because browsers reject Access-Control-Allow-Origin: * when
 * Access-Control-Allow-Credentials: true is also present.
 *
 * Simulated OTP: the backend returns the generated OTP in the response body
 * so the UI can surface it in a toast for demo / development purposes.
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";
const AUTH_BASE   = `${BACKEND_URL}/api/auth`;

// Azure App Service B1 can take up to 20-25s on a cold start.
// 30s gives enough headroom without blocking the user too long.
const TIMEOUT_MS = 30_000;

/**
 * POST wrapper — returns { data } on success, { error, status, message } on failure.
 */
async function post(path, body) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${AUTH_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // "omit" — no cookies needed for a JSON auth API.
      // Using "include" cross-origin forces the browser to reject wildcard CORS
      // responses, and we have no session cookies to send anyway.
      credentials: "omit",
      signal: controller.signal,
      body: JSON.stringify(body),
    });

    clearTimeout(tid);

    let data = null;
    try {
      data = await res.json();
    } catch {
      /* empty body — some error responses have no JSON payload */
    }

    if (!res.ok) {
      return {
        error: true,
        status: res.status,
        message: data?.detail || data?.message || `Request failed (${res.status})`,
      };
    }

    return { data };
  } catch (err) {
    clearTimeout(tid);
    if (err.name === "AbortError") {
      return {
        error: true,
        // Helpful debug log for timeout issues
        console.error("Request timeout:", err),
        status: 0,
        message:
          "Request timed out — the server may be starting up. Please try again in a moment.",
      };
    }
    return {
      error: true,
      // Helpful debug log for CORS / network issues
      console.error("Fetch error:", err),
      status: 0,
      message: "Network error — check your connection and try again.",
    };
  }
}

/**
 * Send OTP to mobile number.
 * Returns { data: { message, otp? } }
 * The `otp` field is only present in simulated / dev mode.
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
  return post("/verify-otp", { mobile, otp });
}

/**
 * Password-based login.
 * Returns { data: { status: "LOGIN_SUCCESS", user: {...} } }
 */
export async function loginWithPassword(mobile, password) {
  return post("/login-password", { mobile, password });
}

/**
 * Register a new user.
 * Returns { data: { status: "REGISTERED", user: {...} } }
 */
export async function register(mobile, password) {
  return post("/register", { mobile, password });
}
