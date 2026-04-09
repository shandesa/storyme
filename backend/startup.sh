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

cd /home/site/wwwroot

# Activate the Oryx-created virtual environment (antenv/ in wwwroot).
if [ -d "antenv" ]; then
    source antenv/bin/activate
fi

exec python -m uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
