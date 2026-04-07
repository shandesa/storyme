/**
 * Auth API client for StoryMe
 *
 * Uses the same REACT_APP_BACKEND_URL as api.js so calls go directly to the
 * deployed Azure App Service backend — NOT through Azure Static Web Apps.
 *
 * Why: Azure SWA has no API functions configured (api_location is empty in
 * the workflow). Calling a relative /api/* path on the SWA returns 405
 * Method Not Allowed. The backend lives at a separate URL and must be called
 * with its full origin.
 *
 * Simulated OTP: the backend returns the generated OTP in the response body
 * so the UI can surface it in a toast for demo / development purposes.
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";
const AUTH_BASE   = `${BACKEND_URL}/api/auth`;

const TIMEOUT_MS = 10_000;

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
      credentials: "include",
      signal: controller.signal,
      body: JSON.stringify(body),
    });

    clearTimeout(tid);

    let data = null;
    try {
      data = await res.json();
    } catch {
      /* empty body */
    }

    if (!res.ok) {
      return {
        error: true,
        status: res.status,
        message: data?.detail || data?.message || "Request failed",
      };
    }

    return { data };
  } catch (err) {
    clearTimeout(tid);
    return {
      error: true,
      status: 0,
      message: err.name === "AbortError" ? "Request timed out" : "Network error",
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
