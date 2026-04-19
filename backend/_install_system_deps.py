"""
_install_system_deps.py
=======================
Installs Linux system libraries required by OpenCV and MediaPipe.

MUST BE IMPORTED AT THE VERY TOP OF server.py, before any import of:
  - cv2 / opencv-python-headless
  - mediapipe

WHY THIS EXISTS
---------------
OpenCV (opencv-python-headless) and MediaPipe are Python wheels, but they
link against native Linux shared libraries that are NOT bundled inside the
wheels. Those libraries must be present on the OS at runtime.

Required shared libraries and the packages that provide them on Debian/Ubuntu:

  Package         Provides              Needed by
  ─────────────── ───────────────────── ──────────────────────────────
  libgl1          libGL.so.1            cv2 (OpenCV), mediapipe
  libglib2.0-0    libglib2.0.so.0       cv2 (OpenCV), mediapipe
  libxcb1         libxcb.so.1           mediapipe 0.10.x
  libsm6          libSM.so.6            mediapipe 0.10.x
  libxext6        libXext.so.6          mediapipe 0.10.x
  libxrender1     libXrender.so.1       mediapipe 0.10.x

azure.storage.blob, reportlab, PIL (Pillow), motor: no extra system deps.

WHY NOT startup.sh OR THE PORTAL STARTUP COMMAND?
--------------------------------------------------
Every approach that installs deps OUTSIDE Python (startup.sh, the Azure
portal Startup Command) is fragile because:

  1. The portal Startup Command bypasses startup.sh entirely.
  2. startup.sh bypasses gunicorn.conf.py entirely.
  3. Both depend on exact portal configuration that can change.
  4. Neither approach is version-controlled or tested in CI.

Installing deps from Python (here, at module load time) is:
  - Version-controlled (this file is in the repo)
  - Always executed regardless of how gunicorn is started
  - Idempotent (dpkg check skips install if already present)
  - Visible in server logs

HOW IT WORKS
------------
At module load time (triggered by `import _install_system_deps` in server.py):
  1. Check each required package with `dpkg -l`.
  2. If any are missing, run `apt-get install` with minimal flags.
  3. The check is fast (<50ms) when packages are already installed.
  4. The install takes ~30s on first run (network + extraction).
  5. Packages survive for the life of the container instance.
  6. They do NOT persist across Azure container restarts
     ("Note: Any data outside '/home' is not persisted") — but this
     module runs again on every startup, so they are always installed.

FAILURE BEHAVIOUR
-----------------
If apt-get fails (e.g. no internet, permission denied), a WARNING is logged
and execution continues. The server starts. Auth, stories, health, and all
non-cv2 routes work normally. Only the image-generation routes fail (with
a clear error message), which is the same behaviour as before — but now
the failure is diagnosed and logged at startup rather than being silent.
"""

import subprocess
import sys
import logging

# Use a module-level logger. basicConfig may not be called yet, so we add a
# StreamHandler directly so the output always appears in Azure Log Stream.
_log = logging.getLogger(__name__)
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    _log.addHandler(_h)
_log.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────────────────
# Package manifest
# Each entry: (apt_package_name, description)
# These are the MINIMUM packages required by opencv-python-headless and mediapipe.
# Do NOT add packages that are not needed — keeps cold-start time minimal.
# ──────────────────────────────────────────────────────────────────────────────
_REQUIRED_APT_PACKAGES = [
    # Package name        Why it's needed
    ("libgl1",           "OpenCV + MediaPipe: libGL.so.1"),
    ("libglib2.0-0",     "OpenCV + MediaPipe: libglib2.0.so.0"),
    ("libxcb1",          "MediaPipe 0.10.x:  libxcb.so.1"),
    ("libsm6",           "MediaPipe 0.10.x:  libSM.so.6"),
    ("libxext6",         "MediaPipe 0.10.x:  libXext.so.6"),
    ("libxrender1",      "MediaPipe 0.10.x:  libXrender.so.1"),
]


def _is_package_installed(package_name: str) -> bool:
    """Return True if an apt package is installed (dpkg status = 'ii')."""
    try:
        result = subprocess.run(
            ["dpkg", "-l", package_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # dpkg -l output has 'ii' prefix for installed packages
        return any(
            line.startswith("ii") and package_name in line
            for line in result.stdout.splitlines()
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # dpkg not available (non-Debian OS or timeout) — assume not installed
        return False


def ensure_system_dependencies() -> bool:
    """
    Check for required system libraries and install any that are missing.

    Returns:
        True  — all packages are present (either were already installed, or
                were just installed successfully)
        False — apt-get failed; generation routes will be unavailable but
                the server continues running
    """
    missing = [
        pkg for pkg, _ in _REQUIRED_APT_PACKAGES
        if not _is_package_installed(pkg)
    ]

    if not missing:
        _log.info(
            "System dependencies: all %d required packages already installed — skipping apt-get",
            len(_REQUIRED_APT_PACKAGES),
        )
        return True

    _log.info(
        "System dependencies: %d package(s) missing, installing: %s",
        len(missing),
        ", ".join(missing),
    )

    # Log WHY each package is needed for future debugging
    for pkg_name, reason in _REQUIRED_APT_PACKAGES:
        if pkg_name in missing:
            _log.info("  Installing %-20s  (%s)", pkg_name, reason)

    try:
        # apt-get update first (needed so package lists are current)
        _log.info("Running apt-get update...")
        subprocess.run(
            ["apt-get", "update", "-qq"],
            check=True,
            timeout=120,
            capture_output=True,
        )

        # Install only the missing packages
        _log.info("Running apt-get install...")
        result = subprocess.run(
            [
                "apt-get", "install", "-y", "-q",
                "--no-install-recommends",   # keep it lean
                "--no-install-suggests",     # same
            ] + missing,
            check=True,
            timeout=180,
            capture_output=True,
            text=True,
        )

        _log.info(
            "System dependencies installed successfully: %s",
            ", ".join(missing),
        )
        return True

    except subprocess.CalledProcessError as e:
        _log.warning(
            "apt-get failed (exit %d). Image generation will be unavailable. "
            "stderr: %s",
            e.returncode,
            (e.stderr or "")[:500],
        )
        return False
    except subprocess.TimeoutExpired:
        _log.warning(
            "apt-get timed out. Image generation will be unavailable. "
            "This can happen if the network is slow on this Azure instance."
        )
        return False
    except FileNotFoundError:
        _log.warning(
            "apt-get not found. This server may not be running on Debian/Ubuntu. "
            "Image generation will be unavailable if system libs are missing."
        )
        return False
    except Exception as e:
        _log.warning(
            "Unexpected error during apt-get: %s. Image generation may be unavailable.",
            e,
        )
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Module-level execution: runs automatically when this module is imported.
# server.py imports this as its FIRST statement, before any cv2/mediapipe import.
# ──────────────────────────────────────────────────────────────────────────────
_deps_ok = ensure_system_dependencies()
