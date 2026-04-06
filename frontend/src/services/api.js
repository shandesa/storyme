// Central API service for StoryMe frontend

const API_BASE = process.env.REACT_APP_API_BASE_URL;

if (!API_BASE) {
  console.error("❌ REACT_APP_API_BASE_URL is not defined");
}

export const api = {
  // Health check
  health: async () => {
    const res = await fetch(`${API_BASE}/health`);
    return res.json();
  },

  // Example: status check
  getStatus: async () => {
    const res = await fetch(`${API_BASE}/api/status`);
    return res.json();
  },

  createStatus: async (data) => {
    const res = await fetch(`${API_BASE}/api/status`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    return res.json();
  },
};

export default api;
