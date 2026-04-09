#!/bin/bash
# Startup script for StoryMe backend on Azure App Service.
#
# Azure Oryx creates antenv/ in /home/site/wwwroot during deployment
# (SCM_DO_BUILD_DURING_DEPLOYMENT=true, the default for Python apps).
# This script activates that venv and launches uvicorn.
#
# NOTE: use `python -m uvicorn` rather than bare `uvicorn`.
# The `uvicorn` entry-point script carries a shebang that hard-codes the
# absolute path to the Python binary that created the venv. If the venv
# was built somewhere other than /home/site/wwwroot (e.g. in CI), the
# shebang path is wrong and the script cannot execute. Invoking uvicorn
# as a Python module avoids the shebang entirely and always uses whichever
# `python` is on PATH after activation.

set -e

echo "===== STARTUP SCRIPT BEGIN ====="
echo "Current directory: $(pwd)"
echo "Listing /home/site/wwwroot:"
ls -la /home/site/wwwroot

cd /home/site/wwwroot

# Activate virtual environment if present
if [ -d "antenv" ]; then
    echo "Activating virtual environment..."
    source antenv/bin/activate
else
    echo "WARNING: antenv not found"
fi

echo "Python version:"
python --version

echo "Installing debug info..."
pip list

echo "Navigating to backend directory..."
cd backend

echo "Current directory after cd:"
pwd
ls -la

echo "Starting FastAPI app with uvicorn..."

exec python -m uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level debug
