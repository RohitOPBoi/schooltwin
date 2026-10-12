"""Baseline Manifest and Immutability Verification for SchoolTwin.

Ensures pack/story_baseline cannot be overwritten, modified, or deleted,
and verifies SHA-256 hashes of all baseline files against MANIFEST.sha256.
"""
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import ROOT

BASELINE_DIR = ROOT / "pack" / "story_baseline"
MANIFEST_FILE = BASELINE_DIR / "MANIFEST.sha256"


class BaselineCorruptionError(RuntimeError):
    """Raised when the baseline pack files deviate from the frozen SHA-256 manifest."""
    pass


class BaselineProtectionError(PermissionError):
    """Raised when an operation attempts to write to or modify the protected baseline."""
    pass


def load_manifest(manifest_path: Optional[Path] = None) -> Dict[str, str]:
    """Loads relative file paths and expected SHA-256 hashes from MANIFEST.sha256."""
    mp = manifest_path or MANIFEST_FILE
    if not mp.exists():
        raise FileNotFoundError(f"Baseline manifest missing at {mp}")
    mapping: Dict[str, str] = {}
    for line in mp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            sha, rel = parts[0].strip(), parts[1].strip()
            mapping[rel] = sha
    return mapping


def verify_baseline_manifest(
    baseline_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """Verifies that all files in the baseline directory match the committed MANIFEST.sha256.

    Returns (is_valid, list_of_mismatches_or_missing).
    """
    bdir = baseline_dir or BASELINE_DIR
    mpath = manifest_path or (bdir / "MANIFEST.sha256")
    if not mpath.exists():
        return False, [f"Manifest file missing: {mpath}"]

    try:
        expected = load_manifest(mpath)
    except Exception as e:
        return False, [f"Failed to read manifest: {e}"]

    errors: List[str] = []
    # Check all expected files exist and match hash
    for rel_str, expected_hash in expected.items():
        fpath = bdir / rel_str
        if not fpath.exists():
            errors.append(f"Missing baseline file: {rel_str}")
            continue
        try:
            actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                errors.append(
                    f"Hash mismatch for {rel_str}: expected {expected_hash}, got {actual_hash}"
                )
        except Exception as e:
            errors.append(f"Failed to hash {rel_str}: {e}")

    # Check for extraneous uncommitted files (excluding MANIFEST.sha256, user_flags.json, and ephemeral temp files)
    for p in bdir.rglob("*"):
        if p.is_file() and p.name not in ("MANIFEST.sha256", "user_flags.json"):
            rel_str = p.relative_to(bdir).as_posix()
            if rel_str not in expected:
                errors.append(f"Untracked extraneous file in baseline: {rel_str}")

    return len(errors) == 0, errors


def assert_baseline_intact(baseline_dir: Optional[Path] = None) -> None:
    """Raises BaselineCorruptionError if baseline does not verify."""
    ok, errors = verify_baseline_manifest(baseline_dir)
    if not ok:
        raise BaselineCorruptionError(
            f"Baseline directory is corrupted or modified:\n" + "\n".join(errors[:10])
        )


def check_write_allowed(target_path: Path) -> None:
    """Enforces that writes into pack/story_baseline are strictly forbidden."""
    try:
        resolved_target = target_path.resolve()
        resolved_baseline = BASELINE_DIR.resolve()
        if resolved_target == resolved_baseline or resolved_baseline in resolved_target.parents:
            raise BaselineProtectionError(
                f"Protected baseline immutability violation: write denied to '{target_path}'"
            )
    except BaselineProtectionError:
        raise
    except Exception:
        pass
