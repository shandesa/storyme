/**
 * Story / backend API client.
 *
 * Uses the deployed backend URL from REACT_APP_BACKEND_URL.
 * Auth calls live in src/api/auth.js (relative /api/auth/* paths).
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";
const API_BASE    = `${BACKEND_URL}/api/v2`;

const MAX_RETRIES = 3;
const TIMEOUT_MS  = 8_000;

// ─── generic fetch wrapper ────────────────────────────────────────────────────

export async function apiFetch(path, options = {}) {
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), TIMEOUT_MS);

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers ?? {}),
        },
        credentials: "include",
        signal: controller.signal,
        ...options,
      });

      clearTimeout(tid);

      let data = null;
      try { data = await res.json(); } catch { /* empty */ }

      if (!res.ok) {
        if (res.status >= 500) throw new Error(`Server error (${res.status})`);
        return { error: true, status: res.status, message: data?.message ?? "Request failed" };
      }

      return data;

    } catch (err) {
      clearTimeout(tid);
      attempt++;

      if (attempt >= MAX_RETRIES) {
        console.error("API request failed:", path, err.message);
        return { error: true, message: err.message ?? "Network error" };
      }

      // Exponential back-off
      await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
    }
  }
}

// ─── Story API ────────────────────────────────────────────────────────────────

export const StoryAPI = {
  /** List all available stories. */
  getStories: () => apiFetch("/stories"),
};
