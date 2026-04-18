/**
 * Server Warm-Up Utility
 * ======================
 * Azure App Service B1 on a cold start takes 3–5 minutes because the
 * appCommandLine runs `apt-get install` (47 packages) before starting gunicorn.
 * During this period the backend TCP port is not open at all — any fetch()
 * throws "Failed to fetch" immediately (not a timeout, a connection refusal).
 *
 * This module solves the problem with a proactive warm-up:
 *   1. On LoginPage mount, start polling GET /health every POLL_INTERVAL_MS.
 *   2. If the server responds 200 within MAX_WAIT_MS, resolve as "ready".
 *   3. If MAX_WAIT_MS elapses without a response, resolve as "timeout" —
 *      the user can still try; we just can't guarantee success.
 *   4. Callers can subscribe to status changes via the callback pattern.
 *
 * The warm-up request has its own short per-attempt timeout (ATTEMPT_TIMEOUT_MS)
 * so polling doesn't pile up during the startup window.
 */

const BACKEND_URL      = process.env.REACT_APP_BACKEND_URL ?? "";
const HEALTH_ENDPOINT  = `${BACKEND_URL}/health`;

const POLL_INTERVAL_MS  = 5_000;   // probe every 5 s
const ATTEMPT_TIMEOUT_MS = 4_000;  // each probe has 4 s to respond
const MAX_WAIT_MS        = 360_000; // give up after 6 minutes (cold start ceiling)

export const WarmupStatus = {
  IDLE:    "idle",      // not yet started
  POLLING: "polling",   // pinging /health, server not yet responding
  READY:   "ready",     // /health returned 200 — server is live
  TIMEOUT: "timeout",   // MAX_WAIT_MS elapsed without a 200
};

/**
 * Ping /health once with a hard per-attempt timeout.
 * Returns true if the server responded 200, false otherwise.
 */
async function pingHealth() {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ATTEMPT_TIMEOUT_MS);
  try {
    const res = await fetch(HEALTH_ENDPOINT, {
      method:      "GET",
      credentials: "omit",
      signal:      controller.signal,
    });
    clearTimeout(tid);
    return res.ok;
  } catch {
    clearTimeout(tid);
    return false;
  }
}

/**
 * Start a warm-up polling loop.
 *
 * @param {(status: string, elapsedMs: number) => void} onStatusChange
 *   Called whenever status transitions or elapsed time updates.
 *
 * @returns {{ stop: () => void }}
 *   Call stop() to cancel polling (e.g. on component unmount).
 */
export function startWarmup(onStatusChange) {
  let stopped    = false;
  let intervalId = null;
  const startTime = Date.now();

  onStatusChange(WarmupStatus.POLLING, 0);

  const poll = async () => {
    if (stopped) return;

    const elapsed = Date.now() - startTime;

    if (elapsed >= MAX_WAIT_MS) {
      clearInterval(intervalId);
      onStatusChange(WarmupStatus.TIMEOUT, elapsed);
      return;
    }

    const alive = await pingHealth();
    if (stopped) return; // component may have unmounted during await

    if (alive) {
      clearInterval(intervalId);
      onStatusChange(WarmupStatus.READY, Date.now() - startTime);
    } else {
      onStatusChange(WarmupStatus.POLLING, Date.now() - startTime);
    }
  };

  // First probe immediately, then every POLL_INTERVAL_MS
  poll();
  intervalId = setInterval(poll, POLL_INTERVAL_MS);

  return {
    stop: () => {
      stopped = true;
      if (intervalId !== null) clearInterval(intervalId);
    },
  };
}
