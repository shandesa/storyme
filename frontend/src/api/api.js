// Centralized API client for StoryMe frontend
// ✅ Azure Static Web Apps compatible (/api/*)
// ✅ No env dependency
// ✅ Retry + timeout + safe JSON handling

const API_PREFIX = "/api";
const MAX_RETRIES = 3;
const TIMEOUT = 8000;

/**
 * Generic API fetch wrapper
 */
export const apiFetch = async (path, options = {}) => {
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT);

    try {
      const response = await fetch(`${API_PREFIX}${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {})
        },
        credentials: "include", // future-safe (auth/session)
        signal: controller.signal,
        ...options
      });

      clearTimeout(timeoutId);

      // Safe JSON parsing
      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      // Handle non-OK responses
      if (!response.ok) {
        if (response.status >= 500) {
          throw new Error(`Server error (${response.status})`);
        }

        return {
          error: true,
          status: response.status,
          message: data?.message || "Request failed"
        };
      }

      return data;

    } catch (error) {
      clearTimeout(timeoutId);
      attempt++;

      if (attempt >= MAX_RETRIES) {
        console.error("API failed:", path, error.message);

        return {
          error: true,
          message: error.message || "Network error"
        };
      }

      // Exponential backoff
      await new Promise(resolve =>
        setTimeout(resolve, 500 * Math.pow(2, attempt))
      );
    }
  }
};

/**
 * Story APIs
 */
export const StoryAPI = {
  // Fetch all stories
  getStories: () => apiFetch("/v2/stories"),

  // Generate story
  generateStory: (payload) =>
    apiFetch("/v2/stories", {
      method: "POST",
      body: JSON.stringify(payload)
    })
};
