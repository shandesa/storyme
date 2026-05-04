/**
 * lib/generationCache.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Module-level singleton that persists generation state across React Router
 * navigations within the same browser session.
 *
 * WHY this exists:
 *   React Router navigations unmount and remount components, wiping all
 *   React state. When a user navigates from HomePage → PrintOrderPage → Back,
 *   the HomePage remounts fresh and loses the PDF context.
 *
 *   A module-level JS object persists for the full browser tab lifetime,
 *   surviving any number of React Router navigations.
 *
 * WHY not sessionStorage:
 *   Blob URLs (window.URL.createObjectURL) cannot be stored in sessionStorage.
 *   The blob URL exists only in browser memory and remains valid as long as the
 *   tab is open and it hasn't been manually revoked.
 *
 * Lifecycle:
 *   set()   — called before any navigation that should be restorable
 *   get()   — called by HomePage on mount to check if state should be restored
 *   clear() — called on explicit "Create Another Story" or logout
 *
 * Shape:
 * {
 *   step:          "format_select" | "complete"   ← which HomePage step to restore
 *   generationId:  string                         ← backend generation_id
 *   childName:     string
 *   storyId:       string
 *   storyTitle:    string
 *   totalPages:    number
 *   bgGenStatus:   "generating" | "complete" | "failed"
 *   pdfBlobUrl:    string | null                  ← blob: URL if sync gen, else null
 *   generationMode: string
 *   gender:        string
 * }
 */

let _cache = null;

/**
 * Store generation context. Call this before navigating away from a page
 * that should be restorable.
 * @param {Object} data - Generation state to persist
 */
export function setGenCache(data) {
  _cache = { ...data, _cachedAt: Date.now() };
}

/**
 * Retrieve cached generation context.
 * Returns null if no cache or cache is older than SESSION_MAX_AGE_MS.
 * @returns {Object|null}
 */
export function getGenCache() {
  if (!_cache) return null;
  // Cache expires after 30 minutes of inactivity
  const SESSION_MAX_AGE_MS = 30 * 60 * 1000;
  if (Date.now() - (_cache._cachedAt || 0) > SESSION_MAX_AGE_MS) {
    _cache = null;
    return null;
  }
  return _cache;
}

/**
 * Clear the cache. Call on explicit "Create Another Story" or logout.
 */
export function clearGenCache() {
  if (_cache?.pdfBlobUrl) {
    try { window.URL.revokeObjectURL(_cache.pdfBlobUrl); } catch {}
  }
  _cache = null;
}

/**
 * Update specific fields in the cache without replacing the whole object.
 * No-op if no cache exists.
 * @param {Object} updates - Fields to merge
 */
export function updateGenCache(updates) {
  if (_cache) {
    _cache = { ..._cache, ...updates, _cachedAt: Date.now() };
  }
}
