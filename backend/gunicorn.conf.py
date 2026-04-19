"""
gunicorn.conf.py — StoryMe production configuration
====================================================

This file is automatically read by gunicorn on startup when it is present
in the current working directory. It requires NO command-line flags and NO
portal startup command configuration.

WHY THIS FILE EXISTS — THE ROOT CAUSE
--------------------------------------
Azure App Service uses Oryx to auto-generate the gunicorn startup command.
Oryx generates:

    gunicorn --timeout 600 --access-logfile '-' server:app

Oryx does NOT pass a -k / --worker-class flag. Gunicorn therefore uses its
built-in default: 'sync' (a WSGI worker).

FastAPI is an ASGI framework. Its __call__ signature is:

    async def __call__(self, scope, receive, send)   ← ASGI: 3 args

The sync (WSGI) worker calls the app as:

    app(environ, start_response)                      ← WSGI: 2 args

This mismatch causes every single request to fail with:

    TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'

WHY THE PROCFILE APPROACH FAILED
---------------------------------
The CI/CD workflow deploys 'package: backend'. Azure compresses the backend
directory into output.tar.zst and stores it at /home/site/wwwroot/. At
runtime, Oryx runs:

    create-script -appPath /home/site/wwwroot -output /opt/startup/startup.sh

Oryx's create-script looks for Procfile at /home/site/wwwroot/Procfile.
But our Procfile is INSIDE the compressed tarball, extracted to /tmp/8de9d.../
Oryx never sees it and falls back to Flask auto-detection every time.

WHY THIS FILE WORKS
--------------------
Gunicorn reads gunicorn.conf.py from its CWD at startup. Oryx extracts the
tarball to /tmp/8de9d.../ and runs gunicorn from there. Our gunicorn.conf.py
is inside the tarball, so it IS at /tmp/8de9d.../gunicorn.conf.py — exactly
where gunicorn looks.

Precedence rules (gunicorn 24.x):
  command-line flags  >  config file  >  built-in defaults

Since Oryx does not pass -k/--worker-class on the command line, our config
file value (uvicorn.workers.UvicornWorker) overrides the built-in default
(sync). This is guaranteed behavior regardless of what Oryx generates.

SETTINGS
---------
See: https://docs.gunicorn.org/en/stable/settings.html
"""

# ── Worker class (THE critical setting) ───────────────────────────────────────
# UvicornWorker embeds an uvicorn ASGI server inside each gunicorn worker
# process. This is the only correct worker type for FastAPI/Starlette apps.
worker_class = "uvicorn.workers.UvicornWorker"

# ── Worker count ──────────────────────────────────────────────────────────────
# Azure B1 SKU: 1 vCPU, 1.75 GB RAM.
# 2 workers allows concurrent requests (e.g. health probe + OTP call)
# without exhausting memory. UvicornWorker is async so each worker handles
# many concurrent connections via the event loop.
workers = 2

# ── Request timeout ───────────────────────────────────────────────────────────
# Face extraction + MediaPipe alignment + LAB colour match + seamlessClone
# + PDF generation can take 15–60s on a warm B1. 300s gives headroom.
# Oryx sets --timeout 600 on the command line which overrides this value,
# but we set it here as a documented safety net.
timeout = 300

# ── Keep-alive ────────────────────────────────────────────────────────────────
# The frontend warmup poller (GET /health every 5s) benefits from persistent
# connections. Avoids TCP handshake overhead on every probe.
keepalive = 5

# ── Logging (stdout so Azure streams them to Log Stream) ─────────────────────
accesslog = "-"
errorlog  = "-"
loglevel  = "info"
