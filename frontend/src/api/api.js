// Centralized API client for StoryMe frontend
// Aligned with Azure Static Web Apps: all backend calls go via `/api/*`
// This removes dependency on environment variables like VITE_API_URL

/**
 * Generic API fetch wrapper
 * - Uses relative path (/api/...)
 * - Handles retries (network + 5xx errors)
 * - Adds exponential backoff
 * - Centralizes error handling
 */
export const apiFetch = async (path, options = {}) => {
  const MAX_RETRIES = 3;
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    try {
      const response = await fetch(`/api${path}`, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {})
        },
        ...options
      });

      // Handle non-OK responses
      if (!response.ok) {
        // Retry only for server errors
        if (response.status >= 500) {
          throw new Error("Server error, retrying...");
        }

        // For client errors (4xx), do not retry
        const errorData = await response.json().catch(() => ({}));
        return {
          error: true,
          status: response.status,
          message: errorData.message || "Request failed"
        };
      }

      // Success
      return await response.json();

    } catch (error) {
      attempt++;

      if (attempt >= MAX_RETRIES) {
        return {
          error: true,
          message: error.message || "Network error"
        };
      }

      // Exponential backoff: 500ms, 1s, 2s
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

  // Example: create/generate story (extend as needed)
  generateStory: (payload) =>
    apiFetch("/v2/stories", {
      method: "POST",
      body: JSON.stringify(payload)
    })
};
