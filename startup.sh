#!/bin/bash
# =============================================================================
# StoryMe — Azure App Service Startup Script
# =============================================================================
# This script is declared in backend/Procfile: web: bash startup.sh
# It is used when Azure App Service does NOT have an appCommandLine override
# in the portal. If appCommandLine IS set, it overrides this script entirely.
#
# NOTE TO OPS: For faster cold starts, clear the "Startup Command" field in
# Azure Portal → App Service → Configuration → General settings and rely on
# this Procfile-based startup instead. The appCommandLine runs apt-get on
# every cold start (~4 min). This script checks before installing (~30s if
# packages are cached by the OS, ~3 min if not).
# =============================================================================

set -e

echo "===== STORYME STARTUP ====="
echo "Time: $(date -u)"
echo "PORT: ${PORT:-8000}"
echo "Python: $(python3 --version 2>&1)"

# ── System dependencies (MediaPipe + OpenCV need these on headless Linux) ────
# Check before installing to avoid the full apt-get cost on warm restarts.
# On Azure App Service each instance is fresh (packages not cached across
# deployments), but within a single warm instance this saves time on restarts.

NEED_INSTALL=false
for pkg in libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1; do
  if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
    NEED_INSTALL=true
    break
  fi
done

if [ "$NEED_INSTALL" = "true" ]; then
  echo "Installing system dependencies (required by MediaPipe/OpenCV)…"
  apt-get update -qq 2>/dev/null
  apt-get install -y -q --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    libgl1
  echo "System dependencies installed."
else
  echo "System dependencies already present — skipping apt-get."
fi

# ── Activate virtual environment ──────────────────────────────────────────────
# Azure Oryx builds antenv/ at deploy time. Look in both possible locations.
if [ -d "antenv" ]; then
  echo "Activating antenv (current dir)"
  source antenv/bin/activate
elif [ -d "/home/site/wwwroot/antenv" ]; then
  echo "Activating antenv (/home/site/wwwroot)"
  source /home/site/wwwroot/antenv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
  echo "Activating .venv"
  source .venv/bin/activate
else
  echo "No virtual environment found — using system Python"
fi

# ── Locate the backend directory ──────────────────────────────────────────────
# The deployment package is the backend/ directory, so server.py is in CWD.
# But if this script is invoked from the repo root, cd into backend/ first.
if [ -f "server.py" ]; then
  echo "server.py found in CWD: $(pwd)"
elif [ -f "backend/server.py" ]; then
  echo "Changing to backend/"
  cd backend
else
  echo "ERROR: server.py not found in $(pwd) or backend/"
  exit 1
fi

echo "Starting from: $(pwd)"
echo "Python path: $(which python)"

# ── Start the application ─────────────────────────────────────────────────────
# Use gunicorn with UvicornWorker for production (process supervision,
# graceful restarts). PORT env var is set by Azure App Service.
#
# --timeout 300  : allow up to 5 min per request (face blend + PDF gen)
# --workers 2    : two worker processes on B1 (1 vCPU / 1.75 GB RAM)
# --keep-alive 5 : keep idle connections alive for polling clients
# --access-logfile - : route access logs to stdout (visible in Azure logs)

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
