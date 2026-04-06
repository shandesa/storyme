import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// 🔥 GLOBAL FETCH INTERCEPTOR (Stage 2 migration)
// This stabilizes all existing API calls without modifying components

if (typeof window !== "undefined" && !window.__FETCH_WRAPPED__) {
  const originalFetch = window.fetch;

  window.fetch = async (url, options = {}) => {
    try {
      let updatedUrl = url;

      if (typeof url === "string") {

        // ✅ Fix "undefined" base URL bug
        if (url.includes("undefined")) {
          console.warn("⚠️ Fixing undefined API URL:", url);
          updatedUrl = url.replace("undefined", "");
        }

        // ✅ Normalize API paths to /api/*
        if (updatedUrl.includes("/api/") && !updatedUrl.startsWith("/api")) {
          updatedUrl = `/api${updatedUrl.split("/api")[1]}`;
        }
      }

      const response = await originalFetch(updatedUrl, options);

      // Optional: log failed responses
      if (!response.ok) {
        console.warn(`API error: ${response.status}`, updatedUrl);
      }

      return response;

    } catch (err) {
      console.error("Network error:", err);
      throw err;
    }
  };

  // Prevent double wrapping
  window.__FETCH_WRAPPED__ = true;
}
