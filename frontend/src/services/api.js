// Central API service for StoryMe frontend (FINAL FIXED VERSION)
// ✅ Azure SWA compatible
// ✅ No env dependency
// ✅ Retry + timeout + error handling

const API_PREFIX = "/api";

/**
 * Generic API fetch wrapper
 */
const apiFetch = async (path, options = {}) => {
  const MAX_RETRIES = 3;
  const TIMEOUT = 8000;

  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT);

    try {
      const response = await fetch(`${API_PREFIX}${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
        credentials: "include", // future-proof (auth/session)
        signal: controller.signal,
        ...options,
      });

      clearTimeout(timeoutId);

      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (!response.ok) {
        if (response.status >= 500) {
          throw new Error(`Server error (${response.status})`);
        }

        return {
          error: true,
          status: response.status,
          message: data?.message || "Request failed",
        };
      }

      return data;

    } catch (err) {
      clearTimeout(timeoutId);
      attempt++;

      if (attempt >= MAX_RETRIES) {
        console.error("API failed:", path, err.message);

        return {
          error: true,
          message: err.message || "Network error",
        };
      }

      await new Promise((res) =>
        setTimeout(res, 500 * Math.pow(2, attempt))
      );
    }
  }
};

/**
 * API methods
 */
export const api = {
  // Health check
  health: () => apiFetch("/health"),

  // Status APIs (⚠️ FIXED: no double /api)
  getStatus: () => apiFetch("/status"),

  createStatus: (data) =>
    apiFetch("/status", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Story APIs
  getStories: () => apiFetch("/v2/stories"),

  generateStory: (payload) =>
    apiFetch("/v2/stories", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export default api;
