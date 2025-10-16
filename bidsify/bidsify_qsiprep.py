#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from pathlib import Path

# ------------------------------------------------------------
# Phase Encoding inference mapping
# ------------------------------------------------------------
PED_MAP = {
    "AP": "j-",
    "PA": "j",
    "LR": "i",
    "RL": "i-",
    "SI": "k-",
    "IS": "k",
}
DIR_TOKEN_RE = re.compile(r"(?:^|[_-])dir-([A-Za-z]{2})(?:[_-]|$)")

def infer_phase_encoding_from_name(p: Path) -> str | None:
    m = DIR_TOKEN_RE.search(p.name)
    if not m:
        return None
    return PED_MAP.get(m.group(1).upper())

# ------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------
def ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)

def copy_file(src: Path, dst: Path, overwrite: bool):
    if dst.exists() and not overwrite:
        return
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)

def load_json(p: Path) -> dict:
    with p.open("r") as f:
        return json.load(f)

def save_json(p: Path, obj: dict):
    with p.open("w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")

def maybe_prefix_subject(filename: str, subj: str) -> str:
    return filename if filename.startswith(f"{subj}_") else f"{subj}_{filename}"

def collect_inputs(inputs_root: Path):
    dwi_dir  = inputs_root / "DWI"
    fmap_dir = inputs_root / "FMAP"
    t1_dir   = inputs_root / "T1w"
    for d in [dwi_dir, fmap_dir, t1_dir]:
        if not d.is_dir():
            raise FileNotFoundError(f"Missing directory: {d}")
    return dwi_dir, fmap_dir, t1_dir

# ------------------------------------------------------------
# DWI JSON editing
# ------------------------------------------------------------
def update_dwi_json(json_path: Path, nii_path: Path, dry_run: bool):
    meta = load_json(json_path)
    # (a) EstimatedTotalReadoutTime -> TotalReadoutTime
    if "EstimatedTotalReadoutTime" in meta:
        if "TotalReadoutTime" not in meta or not meta["TotalReadoutTime"]:
            meta["TotalReadoutTime"] = meta["EstimatedTotalReadoutTime"]
        del meta["EstimatedTotalReadoutTime"]
    # (b) Infer PED if missing
    ped_missing = ("PhaseEncodingDirection" not in meta) or not str(meta.get("PhaseEncodingDirection", "")).strip()
    if ped_missing:
        inferred = infer_phase_encoding_from_name(nii_path)
        if inferred:
            meta["PhaseEncodingDirection"] = inferred
    if not dry_run:
        save_json(json_path, meta)
    print(f"[ok] Edited {json_path.name}")

# ------------------------------------------------------------
# FMAP JSON editing (IntendedFor)
# ------------------------------------------------------------
def update_fmap_json(json_path: Path, intended_files: list[str], dry_run: bool):
    meta = load_json(json_path)
    meta["IntendedFor"] = intended_files
    if not dry_run:
        save_json(json_path, meta)
    print(f"[ok] Added IntendedFor to {json_path.name}")

# ------------------------------------------------------------
# Main logic
# ------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Copy pre-made INPUTS into BIDS layout and fix DWI/FMAP JSONs.")
    ap.add_argument("--inputs-root", required=True)
    ap.add_argument("--bids-root", required=True)
    ap.add_argument("--sub", required=True)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    inputs_root = Path(args.inputs_root).expanduser().resolve()
    bids_root   = Path(args.bids_root).expanduser().resolve()
    subj        = args.sub
    overwrite   = args.overwrite
    dry_run     = args.dry_run

    dwi_in, fmap_in, t1_in = collect_inputs(inputs_root)
    subj_root = bids_root / subj
    dwi_out, fmap_out, anat_out = [subj_root / s for s in ("dwi", "fmap", "anat")]
    if not dry_run:
        for d in [dwi_out, fmap_out, anat_out]:
            ensure_dir(d)

    # ---------- DWI ----------
    dwi_files = []
    for nii in sorted(dwi_in.glob("*.nii.gz")):
        out_name = maybe_prefix_subject(nii.name, subj)
        out_nii = dwi_out / out_name
        stem = out_name.replace(".nii.gz", "")
        in_stem = nii.name.replace(".nii.gz", "")

        if dry_run: print(f"[dry-run] Copy {nii} -> {out_nii}")
        else: copy_file(nii, out_nii, overwrite)

        # Companions
        for ext in (".json", ".bval", ".bvec"):
            src = dwi_in / f"{in_stem}{ext}"
            dst = dwi_out / f"{stem}{ext}"
            if src.exists():
                if dry_run: print(f"[dry-run] Copy {src} -> {dst}")
                else: copy_file(src, dst, overwrite)

        # Edit JSON
        out_json = dwi_out / f"{stem}.json"
        if out_json.exists():
            update_dwi_json(out_json, out_nii, dry_run)
        dwi_files.append(f"dwi/{out_nii.name}")

    # ---------- FMAP ----------
    for nii in sorted(fmap_in.glob("*.nii.gz")):
        out_name = maybe_prefix_subject(nii.name, subj)
        out_nii = fmap_out / out_name
        if dry_run: print(f"[dry-run] Copy {nii} -> {out_nii}")
        else: copy_file(nii, out_nii, overwrite)

        in_json = nii.with_suffix("").with_suffix(".json")
        if in_json.exists():
            out_json = fmap_out / Path(out_name).with_suffix("").with_suffix(".json")
            if dry_run: print(f"[dry-run] Copy {in_json} -> {out_json}")
            else: copy_file(in_json, out_json, overwrite)
            update_fmap_json(out_json, dwi_files, dry_run)

    # ---------- T1w ----------
    for nii in sorted(t1_in.glob("*.nii.gz")):
        out_name = maybe_prefix_subject(nii.name, subj)
        out_nii = anat_out / out_name
        if dry_run: print(f"[dry-run] Copy {nii} -> {out_nii}")
        else: copy_file(nii, out_nii, overwrite)

        in_json = nii.with_suffix("").with_suffix(".json")
        if in_json.exists():
            out_json = anat_out / Path(out_name).with_suffix("").with_suffix(".json")
            if dry_run: print(f"[dry-run] Copy {in_json} -> {out_json}")
            else: copy_file(in_json, out_json, overwrite)

    print("[done] All files copied and JSONs updated.")

if __name__ == "__main__":
    main()
