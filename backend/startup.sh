#!/bin/bash
# Azure App Service startup script for StoryMe backend.
#
# Azure calls this when STARTUP_COMMAND is set to "bash startup.sh"
# It activates the virtual environment built by Oryx and starts uvicorn.
#
# Set this in Azure Portal → Configuration → General settings → Startup command:
#   bash /home/site/wwwroot/startup.sh

set -e

cd /home/site/wwwroot

# Activate the virtual environment Oryx created during build
if [ -d "antenv" ]; then
    source antenv/bin/activate
fi

# Start the FastAPI app
exec uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
