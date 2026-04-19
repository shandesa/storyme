"""
_install_system_deps.py
=======================
Installs Linux system libraries required by OpenCV and MediaPipe at Python
import time — before any cv2 or mediapipe import in the process.

MUST be the very first import in server.py.

WHY THIS APPROACH
-----------------
cv2 (opencv-python-headless) and mediapipe are Python wheels that link against
native Linux shared libraries NOT bundled inside the wheels. Those libraries
must exist on the OS before any `import cv2` or `import mediapipe` runs.

Required shared libraries → apt packages:
  libGL.so.1        → libgl1          (OpenCV + MediaPipe)
  libglib2.0.so.0   → libglib2.0-0   (OpenCV + MediaPipe)
  libxcb.so.1       → libxcb1        (MediaPipe 0.10.x)
  libSM.so.6        → libsm6         (MediaPipe 0.10.x)
  libXext.so.6      → libxext6       (MediaPipe 0.10.x)
  libXrender.so.1   → libxrender1    (MediaPipe 0.10.x)

All other Python packages (azure-storage-blob, reportlab, PIL, motor):
no extra system libraries needed.

KNOWN ISSUES FIXED IN THIS VERSION
------------------------------------
1. --fix-missing flag added to apt-get install.
   Without it, a single package returning 404 from debian-security (e.g.
   libglib2.0-0 version u7 superseded by u8) aborted the ENTIRE install,
   leaving all other successfully-downloaded packages unused. The server then
   had ZERO native libs installed and cv2 failed to import.

2. check=False on apt-get install subprocess.
   With check=True, the CalledProcessError was caught and logged, but the
   partially-downloaded packages were silently discarded. Now we use
   check=False and verify which packages actually got installed afterward.

3. cv2 import test via isolated subprocess.
   If libglib2.0-0 is still missing after apt-get, importing cv2 in the main
   process can HANG the dynamic linker (dlopen blocks waiting for a missing
   .so). This caused gunicorn workers to appear frozen for 60–120s with no
   log output ("No new trace in the past 1 min"). Now we test the cv2 import
   in a subprocess with a hard 15s timeout. If it hangs or fails, we log a
   warning and the main process never attempts the hanging import.

4. apt-get update errors are non-fatal.
   A transient 404 during apt-get update (stale package list) now only logs
   a warning instead of aborting the whole operation.
"""

import subprocess
import sys
import logging

# Set up logging immediately — basicConfig may not have run yet.
# We add our own StreamHandler so output always appears in Azure Log Stream
# regardless of the logging configuration in server.py.
_log = logging.getLogger(__name__)
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    _log.addHandler(_h)
_log.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────────────────────────────
# Package manifest
# Keep this list minimal — every package added increases cold-start time.
# Packages are installed one batch; individual failures do NOT abort the rest
# (--fix-missing handles that).
# ──────────────────────────────────────────────────────────────────────────────
_REQUIRED_APT_PACKAGES = [
    # apt package name    shared library it provides     needed by
    ("libgl1",            "libGL.so.1",                  "OpenCV + MediaPipe"),
    ("libglib2.0-0",      "libglib2.0.so.0",             "OpenCV + MediaPipe"),
    ("libxcb1",           "libxcb.so.1",                 "MediaPipe 0.10.x"),
    ("libsm6",            "libSM.so.6",                  "MediaPipe 0.10.x"),
    ("libxext6",          "libXext.so.6",                "MediaPipe 0.10.x"),
    ("libxrender1",       "libXrender.so.1",             "MediaPipe 0.10.x"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Helper: check a single apt package
# ──────────────────────────────────────────────────────────────────────────────

def _is_installed(package: str) -> bool:
    """
    Return True if an apt package is installed (dpkg status 'ii').
    Returns False on any error (dpkg not found, timeout, etc.).
    """
    try:
        r = subprocess.run(
            ["dpkg", "-l", package],
            capture_output=True, text=True, timeout=5,
        )
        return any(
            line.startswith("ii") and package in line
            for line in r.stdout.splitlines()
        )
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Helper: isolated cv2 import test with timeout
# ──────────────────────────────────────────────────────────────────────────────

def _cv2_imports_safely(timeout_seconds: int = 15) -> bool:
    """
    Test whether cv2 can be imported without hanging the main process.

    On some Linux configurations, importing cv2 when a required shared library
    (e.g. libglib2.0.so.0) is missing causes the dynamic linker's dlopen() to
    BLOCK rather than raise immediately. This hangs the gunicorn worker silently
    for 60–120 seconds with no log output.

    We test the import in a child subprocess with a hard timeout. If it
    succeeds within the timeout, the main process can safely import cv2.
    If it hangs or raises, we log a warning and skip the import.

    Args:
        timeout_seconds: Kill the test subprocess if it runs longer than this.

    Returns:
        True  — cv2 imports cleanly (main process can safely import it)
        False — cv2 is broken or missing (main process must NOT import it)
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import cv2; print('ok')"],
            capture_output=True, text=True,
            timeout=timeout_seconds,
        )
        ok = result.returncode == 0 and "ok" in result.stdout
        if not ok:
            _log.warning(
                "cv2 import test failed (exit %d): %s",
                result.returncode,
                (result.stderr or result.stdout or "no output")[:300],
            )
        return ok
    except subprocess.TimeoutExpired:
        _log.warning(
            "cv2 import test TIMED OUT after %ds — dynamic linker likely "
            "blocked on a missing .so file. Generation routes will be disabled.",
            timeout_seconds,
        )
        return False
    except Exception as e:
        _log.warning("cv2 import test raised %s: %s", type(e).__name__, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Main installation function
# ──────────────────────────────────────────────────────────────────────────────

def ensure_system_dependencies() -> bool:
    """
    Install missing system libraries and verify cv2 can be imported safely.

    Steps:
      1. Check which required packages are missing via dpkg.
      2. If all present AND cv2 imports cleanly → return True immediately.
      3. Run apt-get update (failures are non-fatal — stale cache warning only).
      4. Run apt-get install with --fix-missing so ONE package's 404 does not
         abort the entire install. All other packages are installed normally.
      5. Re-verify which packages are now installed.
      6. Run isolated cv2 import test (subprocess + 15s timeout) to confirm
         the libraries are loadable without hanging the main process.
      7. Return True only if cv2 test passes; False otherwise (server still
         starts, only generation routes are disabled).

    Returns:
        True  — all packages installed AND cv2 imports safely
        False — some packages missing or cv2 still broken after install attempt
                (server continues running; non-generation routes are unaffected)
    """
    # ── Step 1: Check what is missing ────────────────────────────────────────
    missing = [
        pkg for pkg, _, _ in _REQUIRED_APT_PACKAGES
        if not _is_installed(pkg)
    ]

    if not missing:
        _log.info(
            "System deps: all %d packages already installed — testing cv2 import...",
            len(_REQUIRED_APT_PACKAGES),
        )
        if _cv2_imports_safely():
            _log.info("System deps: cv2 imports cleanly ✓")
            return True
        _log.warning(
            "System deps: packages installed but cv2 import failed. "
            "Will attempt reinstall."
        )
        # Fall through to reinstall

    if missing:
        _log.info(
            "System deps: %d package(s) missing → %s",
            len(missing), ", ".join(missing),
        )
        for pkg, lib, needed_by in _REQUIRED_APT_PACKAGES:
            if pkg in missing:
                _log.info("  %-20s  provides %-22s  (needed by %s)", pkg, lib, needed_by)

    # ── Step 2: apt-get update (non-fatal) ───────────────────────────────────
    # Refreshes the local package list so apt sees the latest versions.
    # Errors here are logged as warnings only — stale cache is better than
    # nothing, and the actual install uses --fix-missing anyway.
    _log.info("System deps: running apt-get update...")
    try:
        r = subprocess.run(
            ["apt-get", "update", "-qq"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            _log.warning(
                "apt-get update exited %d (non-fatal, continuing): %s",
                r.returncode, (r.stderr or "")[:200],
            )
        else:
            _log.info("System deps: apt-get update OK")
    except subprocess.TimeoutExpired:
        _log.warning("apt-get update timed out after 120s (non-fatal, continuing)")
    except FileNotFoundError:
        _log.warning("apt-get not found — not a Debian/Ubuntu system")
        return False
    except Exception as e:
        _log.warning("apt-get update error (non-fatal): %s", e)

    # ── Step 3: apt-get install with --fix-missing ────────────────────────────
    # --fix-missing: if a specific package version 404s on the mirror (e.g.
    # libglib2.0-0 u7 superseded by u8 on debian-security), apt skips that
    # package and installs everything else successfully instead of aborting.
    # We use check=False and verify afterward which packages actually installed.
    packages_to_install = [pkg for pkg, _, _ in _REQUIRED_APT_PACKAGES]
    _log.info(
        "System deps: running apt-get install --fix-missing for: %s",
        ", ".join(packages_to_install),
    )
    try:
        r = subprocess.run(
            [
                "apt-get", "install",
                "-y",                        # non-interactive
                "-q",                        # quiet output
                "--no-install-recommends",   # no optional extras
                "--no-install-suggests",     # no suggestions
                "--fix-missing",             # KEY: skip 404 packages, install rest
            ] + packages_to_install,
            capture_output=True, text=True,
            timeout=300,
            check=False,                     # KEY: don't raise on non-zero exit
        )
        if r.returncode == 0:
            _log.info("System deps: apt-get install completed (exit 0)")
        else:
            # Non-zero exit is expected when --fix-missing skips a package.
            # We verify the actual state below via dpkg.
            _log.warning(
                "System deps: apt-get install exited %d (some packages may have "
                "been skipped due to --fix-missing — verifying actual state):\n%s",
                r.returncode,
                (r.stderr or r.stdout or "")[:400],
            )
    except subprocess.TimeoutExpired:
        _log.warning("apt-get install timed out after 300s")
    except Exception as e:
        _log.warning("apt-get install raised %s: %s", type(e).__name__, e)

    # ── Step 4: Re-verify what is now installed ───────────────────────────────
    still_missing = [
        pkg for pkg, _, _ in _REQUIRED_APT_PACKAGES
        if not _is_installed(pkg)
    ]
    installed_now = [
        pkg for pkg, _, _ in _REQUIRED_APT_PACKAGES
        if pkg not in still_missing
    ]

    if installed_now:
        _log.info("System deps: installed ✓ → %s", ", ".join(installed_now))
    if still_missing:
        _log.warning(
            "System deps: still missing after install attempt → %s. "
            "These packages could not be fetched (mirror 404 or network issue). "
            "Image generation will be unavailable until they are installed.",
            ", ".join(still_missing),
        )

    # ── Step 5: Isolated cv2 import test ─────────────────────────────────────
    # Even if all packages installed, test cv2 in a subprocess to confirm the
    # dynamic linker can resolve all symbols. If cv2 hangs during import (due
    # to a missing transitive .so), the timeout kills the test subprocess rather
    # than hanging the main gunicorn worker.
    _log.info("System deps: testing cv2 import in isolated subprocess (timeout=15s)...")
    if _cv2_imports_safely(timeout_seconds=15):
        _log.info("System deps: cv2 imports cleanly ✓ — generation routes enabled")
        return True
    else:
        _log.warning(
            "System deps: cv2 import test failed — generation routes will be "
            "disabled. Server continues with auth/stories/health routes active."
        )
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Module-level execution
# Runs automatically on `import _install_system_deps` in server.py.
# The result is stored in _deps_ok and exposed via the /health endpoint.
# ──────────────────────────────────────────────────────────────────────────────
_deps_ok: bool = ensure_system_dependencies()
