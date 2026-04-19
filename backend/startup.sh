#!/bin/bash
# =============================================================================
# StoryMe — Azure App Service Startup Script
# =============================================================================
#
# SET THIS AS THE AZURE PORTAL STARTUP COMMAND:
#   bash startup.sh
#
# Azure Portal → App Service → Configuration → General settings
#            → Startup Command → bash startup.sh → Save
#
# WHY THIS FILE EXISTS (history)
# --------------------------------
# The portal startup command was previously:
#   apt-get install -y -q libgl1 libglib2.0-0 ... && gunicorn ...
#
# That command had three fatal problems:
#
#   1. No `apt-get update` before install.
#      The container's package lists are stale at startup and reference
#      libglib2.0-0 version 2.66.8-1+deb11u7, which returned 404 from
#      debian-security (superseded by +deb11u8). `apt-get update` refreshes
#      the lists and resolves to the available +deb11u8.
#
#   2. No --fix-missing.
#      A single 404 aborted the entire install even though all other packages
#      (libgl1, libxcb1, etc.) downloaded successfully.
#
#   3. `&&` between apt-get and gunicorn.
#      If apt-get exited non-zero, gunicorn NEVER started. The "No new trace
#      in the past 1 min(s)" in Azure Log Stream was caused by this —
#      the server was completely dead, not just slow.
#
# This script fixes all three by:
#   - Running apt-get update first (resolves stale version references)
#   - Using --fix-missing (skips unfetchable packages, installs the rest)
#   - Never using && (gunicorn ALWAYS starts, even if apt-get fails)
#   - Removing `set -e` from this block (errors are logged, not fatal)
#
# =============================================================================

# ── Script configuration ──────────────────────────────────────────────────────
# NOTE: We intentionally do NOT use `set -e` (exit on error) for the system
# dependency installation section. If apt-get fails, we log a warning and
# continue — gunicorn must always start. The Python-level _install_system_deps
# module will retry and handle failures gracefully at the Python layer.
set -uo pipefail

echo "===== STORYME STARTUP ====="
echo "Time:   $(date -u)"
echo "PORT:   ${PORT:-8000}"
echo "Python: $(python3 --version 2>&1)"
echo ""

# =============================================================================
# SYSTEM DEPENDENCIES
# =============================================================================
# OpenCV (opencv-python-headless) and MediaPipe require native Linux shared
# libraries that are NOT bundled in their Python wheels.
#
# Required packages → shared libraries they provide:
#   libgl1        → libGL.so.1        (OpenCV + MediaPipe)
#   libglib2.0-0  → libglib2.0.so.0  (OpenCV + MediaPipe)
#   libxcb1       → libxcb.so.1      (MediaPipe 0.10.x)
#   libsm6        → libSM.so.6       (MediaPipe 0.10.x)
#   libxext6      → libXext.so.6     (MediaPipe 0.10.x)
#   libxrender1   → libXrender.so.1  (MediaPipe 0.10.x)
#
# These packages are NOT persisted across Azure container restarts
# ("Note: Any data outside '/home' is not persisted") — this script
# runs on every cold start, so they are reinstalled each time.
#
# The dpkg check below skips the install on warm restarts (same container
# instance that has already had these installed this session).
# =============================================================================

PACKAGES="libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1"
NEED_INSTALL=false

for pkg in $PACKAGES; do
  if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
    echo "  Missing: $pkg"
    NEED_INSTALL=true
  fi
done

if [ "$NEED_INSTALL" = "true" ]; then
  echo ""
  echo "Installing system dependencies for OpenCV + MediaPipe..."

  # Step 1: Refresh package lists.
  # CRITICAL: Without this, the container's stale package lists reference
  # libglib2.0-0 version 2.66.8-1+deb11u7 (404 on debian-security).
  # After update, the lists point to 2.66.8-1+deb11u8 which is available.
  echo "  → apt-get update (refreshing package lists)..."
  apt-get update -qq 2>&1 | tail -5 || echo "  WARNING: apt-get update had errors (continuing)"

  # Step 2: Install packages.
  # --fix-missing: if a specific package version returns 404 (e.g. due to
  # still-stale lists or mirror issues), skip it and install everything else.
  # We use OR-true (|| true) so gunicorn starts even if apt-get fails.
  # The _install_system_deps.py Python module will diagnose and retry.
  echo "  → apt-get install --fix-missing $PACKAGES..."
  apt-get install -y -q \
    --no-install-recommends \
    --no-install-suggests \
    --fix-missing \
    $PACKAGES 2>&1 | tail -10 \
    || echo "  WARNING: apt-get install had errors (continuing — Python layer will retry)"

  # Verify what actually installed
  echo ""
  echo "  Package status after install:"
  for pkg in $PACKAGES; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
      echo "    ✓ $pkg"
    else
      echo "    ✗ $pkg (not installed — image generation may be unavailable)"
    fi
  done
else
  echo "System dependencies: all packages already installed — skipping apt-get"
fi

echo ""

# =============================================================================
# VIRTUAL ENVIRONMENT
# =============================================================================
# Azure Oryx builds antenv/ at deploy time with paths correct for this runtime.
# The venv is inside the extracted tarball at /tmp/<hash>/antenv.
# =============================================================================

if [ -d "antenv" ]; then
  echo "Activating antenv ($(pwd)/antenv)"
  # shellcheck disable=SC1091
  source antenv/bin/activate
elif [ -d "/home/site/wwwroot/antenv" ]; then
  echo "Activating antenv (/home/site/wwwroot/antenv)"
  # shellcheck disable=SC1091
  source /home/site/wwwroot/antenv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
  echo "Activating .venv"
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "WARNING: No virtual environment found — using system Python"
fi

# =============================================================================
# LOCATE APPLICATION
# =============================================================================
# CI/CD deploys `package: backend`, so CWD is the backend directory.
# Guard against invocation from the repo root.
# =============================================================================

if [ -f "server.py" ]; then
  echo "Application: server.py found in $(pwd)"
elif [ -f "backend/server.py" ]; then
  echo "Application: changing to backend/"
  cd backend
else
  echo "ERROR: server.py not found in $(pwd) or backend/"
  ls -la
  # Don't exit — let gunicorn fail with a meaningful error
fi

echo "Working directory: $(pwd)"
echo "Python binary:     $(which python 2>/dev/null || which python3 2>/dev/null || echo 'not found')"
echo ""

# =============================================================================
# START GUNICORN
# =============================================================================
#
# -k uvicorn.workers.UvicornWorker  — REQUIRED for FastAPI (ASGI application).
#   gunicorn's default sync worker uses the WSGI interface and causes:
#     TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'
#
# --workers 2  — B1 SKU: 1 vCPU, 1.75 GB RAM. 2 workers = concurrency without
#   exhausting memory. UvicornWorker is async so each worker handles many
#   concurrent connections via its event loop.
#
# --timeout 300  — Face extraction + MediaPipe + seamlessClone + PDF can take
#   15–60s on a warm B1 instance. 300s gives ample headroom.
#
# --keep-alive 5  — Frontend warmup poller hits GET /health every 5s.
#   Persistent connections avoid TCP handshake overhead on every probe.
#
# exec replaces the shell process with gunicorn (proper signal handling,
# no zombie shell process).
# =============================================================================

echo "Starting gunicorn with UvicornWorker..."
exec gunicorn \
  -k uvicorn.workers.UvicornWorker \
  server:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 300 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
