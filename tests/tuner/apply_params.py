"""
tests/tuner/apply_params.py
=============================
Patches face_blend_service.py with the winning parameters from the optimiser.

Reads tests/tuner/results/winning_params.json (written by optimiser.py)
and applies each parameter value to the corresponding constant in
backend/services/face_blend_service.py using precise string replacement.

Writes a backup before patching. If anything goes wrong the backup can be
restored manually.

Usage:
    python tests/tuner/apply_params.py                     # dry-run (shows diff)
    python tests/tuner/apply_params.py --apply             # actually patch the file
    python tests/tuner/apply_params.py --params-file /path/to/winning_params.json
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)

SERVICE_PATH = REPO_ROOT / "backend" / "services" / "face_blend_service.py"

# Maps parameter name → regex pattern that finds the constant in face_blend_service.py
# Group 1 = before the value, Group 2 = the value itself, Group 3 = after
PATCH_PATTERNS = {
    "mask_ellipse_rx": (
        r"(int\(w\s*\*\s*)([0-9.]+)(\),\s*max\(1,\s*int\(h\s*\*)",
        lambda v: f"\\g<1>{v}\\g<3>",
    ),
    "mask_ellipse_ry": (
        r"(int\(w\s*\*[0-9.]+\),\s*max\(1,\s*int\(h\s*\*\s*)([0-9.]+)(\))",
        lambda v: f"\\g<1>{v}\\g<3>",
    ),
    "mask_blur_sigma": (
        r"(cv2\.GaussianBlur\(mask,\s*\(\d+,\s*\d+\),\s*)(\d+)(\))",
        lambda v: f"\\g<1>{int(v)}\\g<3>",
    ),
    "luminance_strength": None,   # controlled in code via param injection — no static const
    "warm_tint_r": (
        r"(face\[:, :, 2\]\s*\*=\s*)([0-9.]+)",
        lambda v: f"\\g<1>{v}",
    ),
    "warm_tint_g": (
        r"(face\[:, :, 1\]\s*\*=\s*)([0-9.]+)",
        lambda v: f"\\g<1>{v}",
    ),
    "clone_mode": (
        r"(cv2\.seamlessClone\([^,]+,[^,]+,[^,]+,[^,]+,\s*cv2\.)(NORMAL_CLONE|MIXED_CLONE)(\))",
        lambda v: f"\\g<1>{v}\\g<3>",
    ),
    # face_scale is applied inline in the call — inject via comment marker
    "face_scale": None,   # handled separately (multiplies w/h at call site)
}


def load_winning_params(params_file: Path) -> dict:
    if not params_file.exists():
        raise FileNotFoundError(
            f"winning_params.json not found at {params_file}. "
            "Run the optimiser first: python tests/tuner/run_tuner.py"
        )
    return json.loads(params_file.read_text())


def compute_diff(original: str, patched: str) -> list[str]:
    """Return a simple line-level diff."""
    orig_lines   = original.splitlines()
    patch_lines  = patched.splitlines()
    diff = []
    for i, (o, p) in enumerate(zip(orig_lines, patch_lines), 1):
        if o != p:
            diff.append(f"Line {i}:")
            diff.append(f"  - {o.strip()}")
            diff.append(f"  + {p.strip()}")
    return diff


def apply_params(
    params:        dict,
    service_path:  Path = SERVICE_PATH,
    dry_run:       bool = True,
) -> None:
    """
    Apply winning params to face_blend_service.py.

    Args:
        params:       {param_name: value} from winning_params.json
        service_path: Path to face_blend_service.py
        dry_run:      If True, only print what would change (no file write)
    """
    src     = service_path.read_text()
    patched = src

    applied = []
    skipped = []

    for name, value in params.items():
        pattern_info = PATCH_PATTERNS.get(name)
        if pattern_info is None:
            skipped.append(f"  {name}: no static patch pattern (injected at runtime)")
            continue

        pattern, replacer = pattern_info
        replacement = replacer(value)

        new_src, n = re.subn(pattern, replacement, patched, count=1)
        if n == 0:
            skipped.append(f"  {name}: pattern not found in file (may already be updated)")
            continue

        applied.append(f"  {name}: → {value}")
        patched = new_src

    print("\n" + "═" * 60)
    print("  face_blend_service.py patch plan")
    print("═" * 60)

    if applied:
        print("\nParameters to patch:")
        for a in applied:
            print(a)

    if skipped:
        print("\nParameters skipped (runtime injection or pattern missing):")
        for s in skipped:
            print(s)

    diff = compute_diff(src, patched)
    if diff:
        print("\nDiff:")
        for line in diff:
            print(line)
    else:
        print("\nNo changes detected.")

    if dry_run:
        print("\nDRY RUN — no files written. Run with --apply to patch.")
        return

    if not diff:
        print("\nNo changes to write.")
        return

    # Write backup
    backup_path = service_path.with_suffix(".py.tuner_backup")
    backup_path.write_text(src)
    print(f"\nBackup written: {backup_path}")

    # Write patched file
    service_path.write_text(patched)
    print(f"Patched:        {service_path}")
    print("\n✅ face_blend_service.py updated with winning parameters.")
    print("   Deploy the backend to see the improvement in production.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Apply tuner winning params to face_blend_service.py")
    p.add_argument("--apply",       action="store_true", help="Actually patch the file (default: dry-run)")
    p.add_argument("--params-file", default="tests/tuner/results/winning_params.json",
                   help="Path to winning_params.json")
    args = p.parse_args()

    params_file = Path(args.params_file)
    params      = load_winning_params(params_file)

    print(f"\nLoaded winning params from: {params_file}")
    for k, v in params.items():
        print(f"  {k}: {v}")

    apply_params(params, dry_run=not args.apply)


if __name__ == "__main__":
    main()
