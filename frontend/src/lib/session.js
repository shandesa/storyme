/**
 * src/lib/session.js
 * -------------------
 * Session management for StoryMe.
 *
 * Storage: sessionStorage
 *   - Cleared automatically when the browser tab closes
 *   - Survives page refreshes within the same session
 *   - NOT shared between tabs (each tab = independent session)
 *   - Never stored in localStorage (would persist across browser restarts)
 *
 * Inactivity timeout:
 *   SESSION_TIMEOUT_MS (default: matches backend SESSION_TIMEOUT_SECONDS = 600s)
 *   WARNING_BEFORE_MS  (default: 30 seconds before logout)
 *   Timer resets on: mousemove, keydown, click, touchstart, scroll
 *   On timeout: session is cleared and user is redirected to /
 *
 * Token refresh:
 *   The backend token expires at SESSION_TIMEOUT_SECONDS.
 *   We call POST /api/auth/refresh every REFRESH_INTERVAL_MS to keep
 *   the token alive while the user is active. If the refresh fails
 *   (token expired, server error) we clear the session.
 */

const TOKEN_KEY  = "storyme_token";
const MOBILE_KEY = "storyme_mobile";

// ─── Configuration ────────────────────────────────────────────────────────────
// Must match or be less than backend SESSION_TIMEOUT_SECONDS (default 600).
export const SESSION_TIMEOUT_MS  = 10 * 60 * 1000;   // 10 minutes
export const WARNING_BEFORE_MS   = 30 * 1000;          // warn 30s before logout
export const REFRESH_INTERVAL_MS =  5 * 60 * 1000;    // refresh token every 5 min

// ─── Token storage ────────────────────────────────────────────────────────────

export function saveSession(token, mobile) {
  try {
    sessionStorage.setItem(TOKEN_KEY,  token);
    sessionStorage.setItem(MOBILE_KEY, mobile);
  } catch (e) {
    console.warn("sessionStorage unavailable:", e);
  }
}

export function getToken() {
  try { return sessionStorage.getItem(TOKEN_KEY)  || null; } catch { return null; }
}

export function getMobile() {
  try { return sessionStorage.getItem(MOBILE_KEY) || null; } catch { return null; }
}

export function clearSession() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(MOBILE_KEY);
  } catch { /* ignore */ }
}

export function isLoggedIn() {
  return !!getToken();
}

// ─── Auth headers ─────────────────────────────────────────────────────────────

export function authHeaders() {
  const token  = getToken();
  const mobile = getMobile();
  const h = {};
  if (token)  h["Authorization"]  = `Bearer ${token}`;
  if (mobile) h["X-User-Mobile"]  = mobile;
  return h;
}

// ─── Inactivity timer ─────────────────────────────────────────────────────────

let _inactivityTimer   = null;
let _warningTimer      = null;
let _onWarning         = null;   // callback() → show warning dialog
let _onLogout          = null;   // callback() → clear session + redirect
let _activityListeners = null;

const ACTIVITY_EVENTS = ["mousemove", "keydown", "click", "touchstart", "scroll"];

function _resetTimers() {
  clearTimeout(_inactivityTimer);
  clearTimeout(_warningTimer);

  if (!_onLogout) return;   // not started

  // Warning fires WARNING_BEFORE_MS before logout
  _warningTimer = setTimeout(() => {
    if (_onWarning) _onWarning();
  }, SESSION_TIMEOUT_MS - WARNING_BEFORE_MS);

  // Logout fires at full timeout
  _inactivityTimer = setTimeout(() => {
    stopInactivityTimer();
    clearSession();
    if (_onLogout) _onLogout();
  }, SESSION_TIMEOUT_MS);
}

/**
 * Start the inactivity timer.
 *
 * @param {Function} onWarning  — called 30s before logout; show a dialog
 * @param {Function} onLogout   — called at timeout; clear session + redirect
 */
export function startInactivityTimer(onWarning, onLogout) {
  _onWarning = onWarning;
  _onLogout  = onLogout;

  // Remove any previous listeners
  stopInactivityTimer();

  // Activity handler resets both timers
  const handler = () => _resetTimers();
  _activityListeners = handler;
  ACTIVITY_EVENTS.forEach((ev) => window.addEventListener(ev, handler, { passive: true }));

  // Start
  _resetTimers();
}

/**
 * Stop the inactivity timer and remove all activity listeners.
 * Call this on logout or when leaving protected pages.
 */
export function stopInactivityTimer() {
  clearTimeout(_inactivityTimer);
  clearTimeout(_warningTimer);
  if (_activityListeners) {
    ACTIVITY_EVENTS.forEach((ev) =>
      window.removeEventListener(ev, _activityListeners)
    );
    _activityListeners = null;
  }
}

/**
 * Manually reset the inactivity timer (call after any user API action).
 */
export function resetInactivityTimer() {
  _resetTimers();
}

// ─── Token refresh loop ───────────────────────────────────────────────────────

let _refreshInterval = null;
const BACKEND_URL    = process.env.REACT_APP_BACKEND_URL ?? "";

async function _refreshToken() {
  const token = getToken();
  if (!token) return;

  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/refresh`, {
      method:  "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.token) {
        const mobile = getMobile();
        saveSession(data.token, mobile);
      }
    } else if (res.status === 401) {
      // Token expired on backend — clear session
      stopTokenRefresh();
      stopInactivityTimer();
      clearSession();
      if (_onLogout) _onLogout();
    }
  } catch { /* network error — will retry next interval */ }
}

export function startTokenRefresh() {
  stopTokenRefresh();
  _refreshInterval = setInterval(_refreshToken, REFRESH_INTERVAL_MS);
}

export function stopTokenRefresh() {
  if (_refreshInterval) {
    clearInterval(_refreshInterval);
    _refreshInterval = null;
  }
}
