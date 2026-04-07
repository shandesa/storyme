#!/bin/bash
# Startup script for StoryMe backend on Azure App Service.
#
# Set this once in Azure Portal:
#   storyme-backend → Configuration → General settings
#   → Startup Command: bash /home/site/wwwroot/startup.sh
#   → Save → Restart
#
# Oryx builds the app into /home/site/wwwroot and creates a virtualenv
# called `antenv`. This script activates it and launches uvicorn.

set -e

cd /home/site/wwwroot

# Activate the Oryx-created virtual environment
if [ -d "antenv" ]; then
    source antenv/bin/activate
fi

exec uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
