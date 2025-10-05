#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_dwi_sidecars_and_sbref.py
-----------------------------
Post-process an existing BIDS subject to:
  (A) Fix DWI JSON sidecars:
      - Promote EstimatedTotalReadoutTime -> TotalReadoutTime (delete Estimated*)
      - Add PhaseEncodingDirection if missing (infer from filename)
  (B) Rename ONLY the b1000 PA pair (.nii.gz + .json) so basename ends with _sbref
      - Detects by simple token checks: "acq-b1000" in name, "dir-PA" in name, endswith "_dwi"
      - Case-insensitive

Usage:
  python fix_dwi_sidecars_and_sbref.py --bids-root /path/to/BIDS --sub sub-257032
"""

import argparse
import json
from pathlib import Path

# ----------------------- JSON helpers -----------------------

def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(p: Path, obj):
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def infer_ped_from_name_and_meta(fname: str, meta: dict):
    """Infer PhaseEncodingDirection using filename tokens first, then metadata."""
    f = fname.lower()
    if "dir-ap" in f:
        return "j-"
    if "dir-pa" in f:
        return "j"
    axis = meta.get("PhaseEncodingAxis")
    if axis in {"i", "j", "k"}:
        sd = (meta.get("SeriesDescription") or "").lower()
        if "ap" in sd and "pa" not in sd:
            return f"{axis}-"
        if "pa" in sd and "ap" not in sd:
            return axis
        return axis
    # last resort default
    return "j"

def fix_json(js_path: Path):
    meta = load_json(js_path)
    changed = False

    if "TotalReadoutTime" not in meta and "EstimatedTotalReadoutTime" in meta:
        meta["TotalReadoutTime"] = meta["EstimatedTotalReadoutTime"]
        del meta["EstimatedTotalReadoutTime"]
        changed = True
        print(f"[fix] {js_path.name}: set TotalReadoutTime from EstimatedTotalReadoutTime")

    if "PhaseEncodingDirection" not in meta:
        ped = infer_ped_from_name_and_meta(js_path.stem, meta)
        meta["PhaseEncodingDirection"] = ped
        changed = True
        print(f"[fix] {js_path.name}: added PhaseEncodingDirection = {ped}")

    if changed:
        save_json(js_path, meta)
    else:
        print(f"[ok] {js_path.name}: no JSON fixes needed")

    return changed

# ----------------------- Rename helpers -----------------------

def to_sbref_name(base: str):
    """Replace suffix _dwi with _sbref; if already _sbref do nothing; else append _sbref."""
    if base.endswith("_dwi"):
        return base[:-4] + "_sbref"
    if base.endswith("_sbref"):
        return base
    return base + "_sbref"

def is_b1000_pa_dwi_basename(base: str, subj: str):
    """Robust token-based check (subj already includes 'sub-')."""
    b = base.lower()
    return (
        b.startswith(subj.lower()) and
        "acq-b1000" in b and
        "dir-pa" in b and
        b.endswith("_dwi")
    )

def rename_b1000_pa_to_sbref(dwi_dir: Path, subj: str):
    """Rename ONLY the b1000 PA (.json + .nii.gz) to *_sbref."""
    jsons = sorted(dwi_dir.glob("*.json"))
    renamed = 0
    for js in jsons:
        base = js.name[:-5]  # strip .json
        if not is_b1000_pa_dwi_basename(base, subj):
            continue

        nii = dwi_dir / (base + ".nii.gz")
        new_base = to_sbref_name(base)
        if new_base == base:
            print(f"[ok] {base}: already *_sbref")
            continue

        new_js = dwi_dir / (new_base + ".json")
        new_nii = dwi_dir / (new_base + ".nii.gz")

        print(f"[mv] {js.name}  -> {new_js.name}")
        js.replace(new_js)

        if nii.exists():
            print(f"[mv] {nii.name} -> {new_nii.name}")
            nii.replace(new_nii)
        else:
            print(f"[warn] {nii.name} not found; only JSON renamed")

        renamed += 1

    if renamed == 0:
        print("[info] No b1000 PA DWI pair found to rename (check naming).")
    else:
        print(f"[summary] Renamed {renamed} b1000 PA pair(s) to *_sbref")

# ----------------------- CLI -----------------------

def main():
    ap = argparse.ArgumentParser(description="Fix DWI JSONs and rename b1000 PA files to *_sbref.")
    ap.add_argument("--bids-root", required=True, type=Path, help="Path to BIDS root")
    ap.add_argument("--sub", required=True, help="Subject ID (already includes 'sub-', e.g., sub-257032)")
    args = ap.parse_args()

    sub_dir = args.bids_root / args.sub
    dwi_dir = sub_dir / "dwi"

    if not dwi_dir.exists():
        raise SystemExit(f"[error] DWI folder not found: {dwi_dir}")

    # (A) Fix all DWI JSONs
    for js in sorted(dwi_dir.glob("*.json")):
        fix_json(js)

    # (B) Rename only the b1000 PA pair to *_sbref
    rename_b1000_pa_to_sbref(dwi_dir, args.sub)

if __name__ == "__main__":
    main()
