#!/bin/bash

set -e

echo "===== CUSTOM STARTUP SCRIPT ====="

cd /home/site/wwwroot

echo "Listing root:"
ls -la

# Activate virtual environment
if [ -d "antenv" ]; then
    echo "Activating virtual environment..."
    source antenv/bin/activate
fi

echo "Python version:"
python --version

echo "Going to backend..."
cd backend

echo "Current dir:"
pwd
ls -la

echo "Starting FastAPI via uvicorn..."

exec python -m uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level debug
