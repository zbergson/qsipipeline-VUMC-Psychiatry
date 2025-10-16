#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Optional

# =========================================
# Helpers and constants
# =========================================
PED_MAP = {
    "AP": "j-",
    "PA": "j",
    "LR": "i",
    "RL": "i-",
    "SI": "k-",
    "IS": "k",
}

DIR_TOKEN_RE = re.compile(r"(?:^|[_-])dir-([A-Za-z]{2})(?:[_-]|$)", re.IGNORECASE)
BVAL_TOKEN_RE = re.compile(r"(?:^|[_-])b(\d{3,5})(?:[^0-9]|$)", re.IGNORECASE)

# Some scanners export shorthand like "...b2000app..." or "...b1000apa..."
ALT_DIR_HINTS = {
    "app": "AP",
    "apa": "PA",
    "_ap_": "AP",
    "_pa_": "PA",
    "-ap-": "AP",
    "-pa-": "PA",
    "_lr_": "LR",
    "_rl_": "RL",
    "_si_": "SI",
    "_is_": "IS",
}

def find_bval_from_name(p: Path) -> Optional[str]:
    m = BVAL_TOKEN_RE.search(p.name)
    if m:
        return m.group(1)
    return None

def find_dir_from_name(p: Path) -> Optional[str]:
    # Prefer explicit BIDS-like dir-XX
    m = DIR_TOKEN_RE.search(p.name)
    if m:
        return m.group(1).upper()
    # fallback to common hints
    low = f"_{p.name.lower()}_"
    for hint, val in ALT_DIR_HINTS.items():
        if hint in low:
            return val
    return None

def infer_ped_from_dir(dir_token: Optional[str]) -> Optional[str]:
    if not dir_token:
        return None
    return PED_MAP.get(dir_token.upper())

def ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)

def copy_file(src: Path, dst: Path):
    if dst.exists():
        return
    shutil.copy2(src, dst)

def load_json(p: Path) -> dict:
    with p.open("r") as f:
        return json.load(f)

def save_json(p: Path, obj: dict):
    with p.open("w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")

def strict_dwi_bids_name(subj: str, bval: str, dir_token: str, suffix: str) -> str:
    return f"{subj}_acq-b{bval}_dir-{dir_token}_dwi{suffix}"

def strict_fmap_bids_name(subj: str, bval: str, dir_token: str, suffix: str) -> str:
    return f"{subj}_acq-b{bval}_dir-{dir_token}_epi{suffix}"

def strict_t1w_bids_name(subj: str, suffix: str) -> str:
    return f"{subj}_T1w{suffix}"

# =========================================
# JSON editing
# =========================================
def update_dwi_json(json_path: Path, ped: Optional[str]):
    meta = load_json(json_path)
    # EstimatedTotalReadoutTime -> TotalReadoutTime
    if "EstimatedTotalReadoutTime" in meta:
        if "TotalReadoutTime" not in meta or not meta["TotalReadoutTime"]:
            meta["TotalReadoutTime"] = meta["EstimatedTotalReadoutTime"]
        del meta["EstimatedTotalReadoutTime"]
    # PhaseEncodingDirection if missing
    if ("PhaseEncodingDirection" not in meta) or (str(meta.get("PhaseEncodingDirection", "")).strip() == ""):
        if ped:
            meta["PhaseEncodingDirection"] = ped
        save_json(json_path, meta)
    print(f"[ok] DWI JSON updated: {json_path.name}")

def update_fmap_json(json_path: Path, ped: Optional[str], intended_files: list[str]):
    meta = load_json(json_path)
    # EstimatedTotalReadoutTime -> TotalReadoutTime (if present)
    if "EstimatedTotalReadoutTime" in meta:
        if "TotalReadoutTime" not in meta or not meta["TotalReadoutTime"]:
            meta["TotalReadoutTime"] = meta["EstimatedTotalReadoutTime"]
        del meta["EstimatedTotalReadoutTime"]
    # IntendedFor
    meta["IntendedFor"] = intended_files
    # PhaseEncodingDirection if missing
    if ("PhaseEncodingDirection" not in meta) or (str(meta.get("PhaseEncodingDirection", "")).strip() == ""):
        if ped:
            meta["PhaseEncodingDirection"] = ped
        save_json(json_path, meta)
    print(f"[ok] FMAP JSON updated: {json_path.name}")

# =========================================
# Per-subject processing
# =========================================
def process_one_subject(inputs_root: Path, bids_root: Path, subj: str):
    dwi_in  = inputs_root / subj / "DWI"
    fmap_in = inputs_root / subj / "fmap"
    t1_in   = inputs_root / subj / "T1w"
    if not dwi_in.is_dir():
        raise FileNotFoundError(f"Missing directory: {dwi_in}")
    if not fmap_in.is_dir():
        raise FileNotFoundError(f"Missing directory: {fmap_in}")
    if not t1_in.is_dir():
        raise FileNotFoundError(f"Missing directory: {t1_in}")

    # Output dirs
    subj_root = bids_root / subj
    dwi_out   = subj_root / "dwi"
    fmap_out  = subj_root / "fmap"
    anat_out  = subj_root / "anat"
    for d in [dwi_out, fmap_out, anat_out]:
        ensure_dir(d)

    # ---------- DWI ----------
    intended_for_list = []
    for nii in sorted(dwi_in.glob("*.nii.gz")):
        bval = find_bval_from_name(nii)
        dir_token = find_dir_from_name(nii)
        if not bval or not dir_token:
            raise ValueError(f"Cannot infer bval/dir from DWI file name: {nii.name}")
        out_name = strict_dwi_bids_name(subj, bval, dir_token, ".nii.gz")
        out_nii = dwi_out / out_name
        copy_file(nii, out_nii)

        companions = {
            ".bval": dwi_in / nii.name.replace(".nii.gz", ".bval"),
            ".bvec": dwi_in / nii.name.replace(".nii.gz", ".bvec"),
            ".json": dwi_in / nii.name.replace(".nii.gz", ".json"),
        }
        for ext, src in companions.items():
            if src.exists():
                dst = dwi_out / strict_dwi_bids_name(subj, bval, dir_token, ext)
                copy_file(src, dst)
            else:
                if ext != ".json":
                    print(f"[warn] Missing companion {ext} for {nii.name}")

        out_json = dwi_out / strict_dwi_bids_name(subj, bval, dir_token, ".json")
        ped = infer_ped_from_dir(dir_token)
        if out_json.exists():
            update_dwi_json(out_json, ped)
        else:
            print(f"[warn] No JSON found for {out_nii.name}; cannot update PED/ReadoutTime.")
        intended_for_list.append(f"dwi/{out_nii.name}")

    # ---------- FMAP ----------
    for nii in sorted(fmap_in.glob("*.nii.gz")):
        bval = find_bval_from_name(nii)
        dir_token = find_dir_from_name(nii)
        if not bval or not dir_token:
            raise ValueError(f"Cannot infer bval/dir from FMAP file name: {nii.name}")
        out_name = strict_fmap_bids_name(subj, bval, dir_token, ".nii.gz")
        out_nii = fmap_out / out_name
        copy_file(nii, out_nii)

        in_json = nii.with_suffix("").with_suffix(".json")
        if in_json.exists():
            out_json = fmap_out / strict_fmap_bids_name(subj, bval, dir_token, ".json")
            copy_file(in_json, out_json)
            ped = infer_ped_from_dir(dir_token)
            update_fmap_json(out_json, ped, intended_for_list)
        else:
            print(f"[warn] No JSON for fmap {nii.name}")

    # ---------- T1w ----------
    for nii in sorted(t1_in.glob("*.nii.gz")):
        out_name = strict_t1w_bids_name(subj, ".nii.gz")
        out_nii = anat_out / out_name
        copy_file(nii, out_nii)

        in_json = nii.with_suffix("").with_suffix(".json")
        if in_json.exists():
            out_json = anat_out / strict_t1w_bids_name(subj, ".json")
            copy_file(in_json, out_json)

# =========================================
# Dataset-level files
# =========================================
def write_dataset_description(bids_root: Path):
    ds_path = bids_root / "dataset_description.json"
    if ds_path.exists():
        return
    ds = {
        "Name": "BIDS dataset",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw"
    }
    with ds_path.open("w") as f:
        json.dump(ds, f, indent=2, sort_keys=True)
        f.write("\n")

def update_participants_tsv(bids_root: Path, subjects: list[str]):
    tsv_path = bids_root / "participants.tsv"
    rows = sorted(set(subjects))
    if tsv_path.exists():
        # Merge
        try:
            import pandas as _pd
            df_old = _pd.read_csv(tsv_path, sep="\t")
            old = set(df_old["participant_id"].astype(str).tolist())
            rows = sorted(old.union(rows))
        except Exception:
            pass
    with tsv_path.open("w") as f:
        f.write("participant_id\n")
        for s in rows:
            f.write(f"{s}\n")

# =========================================
# CLI
# =========================================
def main():
    ap = argparse.ArgumentParser(description="Batch BIDS copier with strict naming and JSON fixes.")
    ap.add_argument("--inputs-root", required=True, help="Folder containing INPUTS/sub-*/{DWI,fmap,T1w}")
    ap.add_argument("--bids-root", required=True, help="Output BIDS root")
    ap.add_argument("--sub", action="append", help="Subject(s) to process (e.g., sub-257032). Repeatable.")
    args = ap.parse_args()

    inputs_root = Path(args.inputs_root).expanduser().resolve()
    bids_root   = Path(args.bids_root).expanduser().resolve()

    # Subjects
    if args.sub:
        subjects = args.sub
    else:
        subjects = [p.name for p in sorted(inputs_root.glob("sub-*")) if p.is_dir()]
        if not subjects:
            raise FileNotFoundError(f"No 'sub-*' folders found in {inputs_root}")

    processed = []
    for subj in subjects:
        print(f"=== Processing {subj} ===")
        process_one_subject(inputs_root, bids_root, subj)
        processed.append(subj)

    write_dataset_description(bids_root)
    update_participants_tsv(bids_root, processed)

    print(f"[done] Processed {len(processed)} participant(s).")

if __name__ == "__main__":
    main()

#Command to run QSIPrep container in docker:
# docker run --rm -it \                           
#   --platform linux/amd64 \
#   -v "${INPUTS}":/inputs:ro \
#   -v "${BIDS}":/bids \
#   -v "${DERIV}":/out \
#   -v "${WORK}":/work \
#   -v "${FS_LICENSE}":/opt/freesurfer/license.txt:ro \
#   -v "$(dirname "${BIDSIFY}")":/scripts:ro \
#   --entrypoint /bin/bash \
#   pennlinc/qsiprep:1.0.1 \
#   -lc 'set -euxo pipefail; \
#        python /scripts/'"$(basename "${BIDSIFY}")"' \
#          --inputs-root /inputs \
#          --bids-root /bids && \
#        qsiprep /bids /out participant \
#          --stop-on-first-crash \
#          --output-resolution 2 \
#          --nprocs 12 \
#          --write-graph \
#          --omp-nthreads 12 \
#          --mem 32000 \
#          -w /work \
#          --fs-license-file /opt/freesurfer/license.txt'