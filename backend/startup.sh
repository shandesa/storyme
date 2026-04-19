#!/bin/bash
# =============================================================================
# StoryMe — Azure App Service Startup Script
# =============================================================================
#
# LOCATION: This file MUST live inside backend/ so it is included in the
# deployment package (CI/CD deploys `package: backend`, not the repo root).
# The root-level startup.sh is never deployed and was the cause of the
# Oryx auto-detection fallback that used sync/WSGI workers for FastAPI.
#
# USAGE:
#   Option A (recommended): Leave "Startup Command" empty in Azure Portal.
#     Azure reads backend/Procfile which now calls gunicorn directly with
#     UvicornWorker. No apt-get system dep install on this path.
#
#   Option B: Set the Azure Portal Startup Command to:
#     bash startup.sh
#     This script installs system deps (libgl1 etc. for MediaPipe/OpenCV)
#     then starts gunicorn with UvicornWorker. Use this if face-blend
#     fails due to missing shared libraries.
#
# WHY UvicornWorker:
#   FastAPI is an ASGI framework. gunicorn's default "sync" worker uses the
#   WSGI interface (environ, start_response) but FastAPI.__call__ expects
#   the ASGI interface (scope, receive, send). Using sync workers causes:
#     TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'
#   UvicornWorker wraps uvicorn inside gunicorn, giving ASGI + process
#   supervision + graceful restarts.
#
# =============================================================================

set -e

echo "===== STORYME STARTUP ====="
echo "Time:   $(date -u)"
echo "PORT:   ${PORT:-8000}"
echo "Python: $(python3 --version 2>&1)"

# ── System dependencies (MediaPipe + OpenCV require these on headless Linux) ──
# Only install if not already present — saves ~3 min on warm container restarts.
# These packages are NOT persisted across container restarts on Azure App Service
# ("Note: Any data outside '/home' is not persisted"), but the same container
# instance keeps them in-memory for the duration of its lifecycle.

NEED_INSTALL=false
for pkg in libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1; do
  if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
    NEED_INSTALL=true
    break
  fi
done

if [ "$NEED_INSTALL" = "true" ]; then
  echo "Installing system dependencies (required by MediaPipe/OpenCV)..."
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
# Azure Oryx builds antenv/ at deploy time with paths correct for the Azure
# runtime. Check the most likely locations in order.

if [ -d "antenv" ]; then
  echo "Activating antenv (current dir: $(pwd))"
  source antenv/bin/activate
elif [ -d "/home/site/wwwroot/antenv" ]; then
  echo "Activating antenv (/home/site/wwwroot)"
  source /home/site/wwwroot/antenv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
  echo "Activating .venv"
  source .venv/bin/activate
else
  echo "WARNING: No virtual environment found — using system Python"
fi

# ── Locate server.py ──────────────────────────────────────────────────────────
# When deployed via CI/CD (package: backend), the working directory IS the
# backend directory. Guard against being invoked from the repo root.

if [ -f "server.py" ]; then
  echo "server.py found in CWD: $(pwd)"
elif [ -f "backend/server.py" ]; then
  echo "Changing to backend/"
  cd backend
else
  echo "ERROR: server.py not found in $(pwd) or backend/"
  ls -la
  exit 1
fi

echo "Running from: $(pwd)"
echo "Python:       $(which python 2>/dev/null || which python3)"

# ── Start FastAPI via gunicorn + UvicornWorker ────────────────────────────────
#
# -k uvicorn.workers.UvicornWorker
#   REQUIRED for FastAPI (ASGI). gunicorn's default "sync" worker uses the
#   WSGI interface and causes:
#     TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'
#
# --workers 2
#   B1 SKU has 1 vCPU and 1.75 GB RAM. 2 workers allows concurrent requests
#   (e.g. health probe + OTP call) without exhausting memory.
#
# --timeout 300
#   Face extraction + MediaPipe align + seamlessClone + PDF generation can
#   take 15-60s on a warm B1. 300s gives ample headroom.
#
# --keep-alive 5
#   Frontend warmup poller (GET /health every 5s) benefits from persistent
#   connections. Avoids TCP handshake overhead on every probe.

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
