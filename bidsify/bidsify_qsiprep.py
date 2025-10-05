#!/usr/bin/env python3
"""
bidsify_qsiprep.py
------------------
Convert a single-participant dataset organized as:
  SRC_ROOT/
    T1w/   <series folders with DICOMs>
    DWI/   <series folders with DICOMs>
    topup/ <series folders with DICOMs>
into a BIDS-compliant folder suitable for QSIPrep.

Requirements:
- Python 3.8+
- dcm2niix on PATH (https://github.com/rordenlab/dcm2niix)

Usage:
  python bidsify_qsiprep.py \
      --src /path/to/SRC_ROOT \
      --out /path/to/BIDS_ROOT \
      --sub $SUBJ \
      [--map-ap "app|APA"] [--map-pa "apa|APP"] \
      [--dry-run]
"""

import argparse
from pathlib import Path
import json, subprocess, shutil, re

def run(cmd):
    print("[cmd]", " ".join(map(str, cmd)))
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        print(r.stdout)
        raise SystemExit(f"Command failed: {' '.join(map(str, cmd))}")
    return r.stdout

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def load_json(p: Path):
    with open(p, 'r') as f:
        return json.load(f)

def write_json(p: Path, obj):
    with open(p, 'w') as f:
        json.dump(obj, f, indent=2)

def detect_dir_from_json(json_path: Path):
    try:
        j = load_json(json_path)
        return j.get("PhaseEncodingDirection", None)  # e.g., "j-" or "j"
    except Exception:
        return None

def sign_to_dir_label(phase_encoding_direction: str, default=None):
    if phase_encoding_direction in ("j-", "i-", "k-"):
        return "AP"
    if phase_encoding_direction in ("j", "i", "k"):
        return "PA"
    return default

def detect_dir_from_name(name: str, ap_regex: str, pa_regex: str):
    if re.search(ap_regex, name, flags=re.IGNORECASE):
        return "AP"
    if re.search(pa_regex, name, flags=re.IGNORECASE):
        return "PA"
    return None

def max_bval_from_bval_file(bval_path: Path):
    try:
        txt = Path(bval_path).read_text().strip().split()
        vals = [float(x) for x in txt if x.strip()]
        return int(round(max(vals)))
    except Exception:
        return None

def sanitize(s: str):
    return re.sub(r'[^A-Za-z0-9]+', '', s)

def bidsify(src_root: Path, out_root: Path, sub: str, ap_regex: str, pa_regex: str, dry: bool=False):
    sub_dir = out_root / sub
    dwi_dir = sub_dir / "dwi"
    anat_dir = sub_dir / "anat"
    ensure_dir(dwi_dir); ensure_dir(anat_dir)

    # top-level metadata
    ds_desc = {"Name": f"BIDS dataset for {sub}", "BIDSVersion": "1.9.0", "DatasetType": "raw"}
    if not dry:
        write_json(out_root / "dataset_description.json", ds_desc)
        with open(out_root / "participants.tsv", "w") as f:
            f.write("participant_id\n" + sub + "\n")

    # --- T1w ---
    t1w_root = src_root / "T1w"
    if t1w_root.exists():
        t1_series = sorted([p for p in t1w_root.iterdir() if p.is_dir()])
        if t1_series:
            t1_tmp = out_root / "_tmp_t1w"
            ensure_dir(t1_tmp)
            print(f"[info] Converting T1w from {t1_series[0]}")
            if not dry:
                run(["dcm2niix", "-ba", "y", "-z", "y", "-o", str(t1_tmp), str(t1_series[0])])
                nii = next(iter(t1_tmp.glob("*.nii.gz")), None)
                jpath = next(iter(t1_tmp.glob("*.json")), None)
                shutil.move(str(nii), str(anat_dir / f"{sub}_T1w.nii.gz"))
                if jpath:
                    shutil.move(str(jpath), str(anat_dir / f"{sub}_T1w.json"))
                shutil.rmtree(t1_tmp, ignore_errors=True)

    # track DWIs for IntendedFor
    dwi_relpaths = []

    # --- DWI ---
    dti_root = src_root / "DWI"
    if dti_root.exists():
        dti_series = sorted([p for p in dti_root.iterdir() if p.is_dir()])
        run_idx = {}
        for ser in dti_series:
            tmp = out_root / f"_tmp_dwi_{sanitize(ser.name)}"
            ensure_dir(tmp)
            print(f"[info] Converting DWI from {ser}")
            if not dry:
                run(["dcm2niix", "-ba", "y", "-z", "y", "-o", str(tmp), str(ser)])
                nii = next(iter(tmp.glob("*.nii.gz")), None)
                bval = next(iter(tmp.glob("*.bval")), None)
                bvec = next(iter(tmp.glob("*.bvec")), None)
                jpath = next(iter(tmp.glob("*.json")), None)

                maxb = max_bval_from_bval_file(bval) or 0
                acq = f"b{int(round(maxb,-2))}" if maxb>0 else "b0"

                ped = detect_dir_from_json(jpath)
                dirlbl = sign_to_dir_label(ped, default=None)
                if dirlbl is None:
                    dirlbl = detect_dir_from_name(ser.name, ap_regex, pa_regex) or "AP"

                key = (acq, dirlbl)
                run_idx[key] = run_idx.get(key, 0) + 1
                run_tag = f"_run-{run_idx[key]}" if run_idx[key] > 1 else ""

                base = f"{sub}_acq-{acq}_dir-{dirlbl}{run_tag}_dwi"
                shutil.move(str(nii), str(dwi_dir / f"{base}.nii.gz"))
                shutil.move(str(bval), str(dwi_dir / f"{base}.bval"))
                shutil.move(str(bvec), str(dwi_dir / f"{base}.bvec"))
                shutil.move(str(jpath), str(dwi_dir / f"{base}.json"))

                dwi_relpaths.append(f"dwi/{base}.nii.gz")
                shutil.rmtree(tmp, ignore_errors=True)

    # --- Fieldmaps ---
    # fmap_root = src_root / "topup"
    # if fmap_root.exists():
    #     fmap_series = sorted([p for p in fmap_root.iterdir() if p.is_dir()])
    #     for i, ser in enumerate(fmap_series, 1):
    #         tmp = out_root / f"_tmp_fmap_{sanitize(ser.name)}"
    #         ensure_dir(tmp)
    #         print(f"[info] Converting topup from {ser}")
    #         if not dry:
    #             run(["dcm2niix", "-ba", "y", "-z", "y", "-o", str(tmp), str(ser)])
    #             nii = next(iter(tmp.glob("*.nii.gz")), None)
    #             jpath = next(iter(tmp.glob("*.json")), None)

    #             ped = detect_dir_from_json(jpath)
    #             dirlbl = sign_to_dir_label(ped, default=None)
    #             if dirlbl is None:
    #                 dirlbl = detect_dir_from_name(ser.name, ap_regex, pa_regex) or "AP"

    #             base = f"{sub}_dir-{dirlbl}_run-{i}_epi"
    #             shutil.move(str(nii), str(fmap_dir / f"{base}.nii.gz"))
    #             j = load_json(jpath)
    #             j["IntendedFor"] = dwi_relpaths
    #             write_json(fmap_dir / f"{base}.json", j)
    #             shutil.rmtree(tmp, ignore_errors=True)

    # print("[ok] BIDS conversion complete at", sub_dir)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sub", required=True)
    ap.add_argument("--map-ap", default=r'app|APA|AP\b')
    ap.add_argument("--map-pa", default=r'apa|APP|PA\b')
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bidsify(Path(args.src), Path(args.out), args.sub, args.map_ap, args.map_pa, dry=args.dry_run)

if __name__ == "__main__":
    main()
