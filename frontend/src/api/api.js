/**
 * Story / backend API client
 * ==========================
 * Uses the deployed backend URL from REACT_APP_BACKEND_URL.
 * Auth calls live in src/api/auth.js.
 *
 * Timeout strategy:
 *   STORY_TIMEOUT_MS   — short reads (story list, health) — 15 s
 *   GENERATE_TIMEOUT_MS — image processing (preview, PDF) — 180 s
 *     Face extraction + MediaPipe alignment + LAB colour match +
 *     seamlessClone can take 15–60 s on a warm B1 instance.
 *     180 s gives ample headroom without hanging the UI indefinitely.
 *
 * Retry strategy:
 *   MAX_RETRIES = 3 with exponential back-off for transient errors only.
 *   HTTP 4xx errors are NOT retried (user error, not transient).
 *   HTTP 5xx errors ARE retried (server may be mid-restart).
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL ?? "";
const API_BASE    = `${BACKEND_URL}/api/v2`;

const STORY_TIMEOUT_MS    = 15_000;  // story list, health probes
const GENERATE_TIMEOUT_MS = 180_000; // face blend + PDF generation

const MAX_RETRIES = 3;

// ─── internal fetch wrapper ───────────────────────────────────────────────────

async function apiFetch(path, options = {}, timeoutMs = STORY_TIMEOUT_MS) {
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers ?? {}),
        },
        credentials: "omit",
        signal: controller.signal,
        ...options,
      });

      clearTimeout(tid);

      let data = null;
      try { data = await res.json(); } catch { /* empty */ }

      if (!res.ok) {
        // 4xx — don't retry, surface to caller
        if (res.status < 500) {
          return { error: true, status: res.status, message: data?.detail ?? data?.message ?? "Request failed" };
        }
        // 5xx — may be transient (mid-deploy restart), fall through to retry
        throw new Error(`Server error (${res.status})`);
      }

      return data;

    } catch (err) {
      clearTimeout(tid);
      attempt++;

      if (attempt >= MAX_RETRIES) {
        console.error("API request failed:", path, err.message);
        const isStartingUp = err instanceof TypeError || err.name === "AbortError";
        return {
          error: true,
          message: isStartingUp
            ? "Server is still starting — please try again in a moment."
            : (err.message ?? "Network error"),
        };
      }

      // Exponential back-off: 1s, 2s, 4s …
      await new Promise((r) => setTimeout(r, 1_000 * 2 ** (attempt - 1)));
    }
  }
}

// ─── Story API ────────────────────────────────────────────────────────────────

export const StoryAPI = {
  /** List all available stories. */
  getStories: () => apiFetch("/stories", {}, STORY_TIMEOUT_MS),

  /**
   * Generate a page-1 preview for the given child.
   * Uses a long timeout — face blend + compose takes 15–60 s on warm B1.
   * formData must be a FormData object with: name, image, story_id, mode.
   */
  generatePreview: (formData) =>
    apiFetch("/generate/preview", {
      method: "POST",
      headers: {},         // let browser set multipart boundary
      body: formData,
    }, GENERATE_TIMEOUT_MS),
};

// Re-export for any callers that import apiFetch directly
export { apiFetch };
