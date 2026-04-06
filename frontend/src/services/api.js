// Central API service for StoryMe frontend (Refactored)
// ✅ Azure Static Web Apps compatible (/api/*)
// ✅ No dependency on REACT_APP_API_BASE_URL
// ✅ Retry + error handling included

/**
 * Generic API fetch wrapper
 * - Uses relative `/api` path (Azure SWA handles routing)
 * - Retries on network/5xx errors
 * - Standardizes error responses
 */
const apiFetch = async (path, options = {}) => {
  const MAX_RETRIES = 3;
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    try {
      const response = await fetch(`/api${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
        ...options,
      });

      // Handle non-OK responses
      if (!response.ok) {
        if (response.status >= 500) {
          throw new Error("Server error");
        }

        // 4xx → no retry
        const errorData = await response.json().catch(() => ({}));
        return {
          error: true,
          status: response.status,
          message: errorData.message || "Request failed",
        };
      }

      return await response.json();
    } catch (err) {
      attempt++;

      if (attempt >= MAX_RETRIES) {
        return {
          error: true,
          message: err.message || "Network error",
        };
      }

      // Exponential backoff: 500ms → 1s → 2s
      await new Promise((res) =>
        setTimeout(res, 500 * Math.pow(2, attempt))
      );
    }
  }
};

/**
 * API methods
 * NOTE: All frontend should use these — no direct fetch calls
 */
export const api = {
  // Health check
  health: () => apiFetch("/health"),

  // Status APIs
  getStatus: () => apiFetch("/api/status"),

  createStatus: (data) =>
    apiFetch("/api/status", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Story APIs (aligning with your product)
  getStories: () => apiFetch("/v2/stories"),

  generateStory: (payload) =>
    apiFetch("/v2/stories", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export default api;
