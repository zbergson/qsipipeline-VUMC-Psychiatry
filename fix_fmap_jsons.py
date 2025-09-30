#!/usr/bin/env python3
import json, sys, re
from pathlib import Path

def load_json(p):
    with open(p) as f: return json.load(f)

def save_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f: json.dump(obj, f, indent=2)

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 force_fix_fmap_jsons.py /path/to/BIDS sub-256560")
        sys.exit(2)

    bids = Path(sys.argv[1]).resolve()
    sub  = sys.argv[2]
    subdir  = bids / sub
    dwidir  = subdir / "dwi"
    fmapdir = subdir / "fmap"

    # --- collect DWI-derived metadata ---
    dwi_sign = {"AP": None, "PA": None}   # e.g., {'AP':'j-','PA':'j'}
    trt = None                             # TotalReadoutTime (sec)
    ees = None                             # EffectiveEchoSpacing (sec)
    steps = None                           # PhaseEncoding steps (dim-1)

    for jpath in sorted(dwidir.glob("*_dwi.json")):
        J = load_json(jpath)
        # grab signs from any DWI with dir tag
        if "_dir-AP_" in jpath.name and J.get("PhaseEncodingDirection"):
            dwi_sign["AP"] = J["PhaseEncodingDirection"]
        if "_dir-PA_" in jpath.name and J.get("PhaseEncodingDirection"):
            dwi_sign["PA"] = J["PhaseEncodingDirection"]
        # try TRT directly
        trt = trt or J.get("TotalReadoutTime") or J.get("EstimatedTotalReadoutTime")
        # backup: compute from echo spacing * (pe-1)
        ees = ees or J.get("EffectiveEchoSpacing") or J.get("DwellTime")
        steps = steps or J.get("ReconMatrixPE") or J.get("PhaseEncodingSteps")

    if trt is None and (ees and steps):
        try:
            trt = float(ees) * (int(steps) - 1)
        except Exception:
            trt = None

    # final fallbacks
    if dwi_sign["AP"] is None: dwi_sign["AP"] = "j-"   # common default for AP
    if dwi_sign["PA"] is None: dwi_sign["PA"] = "j"    # common default for PA
    if trt is None:
        print("WARNING: Could not infer TotalReadoutTime from DWI metadata.")
        print("         You should replace the placeholder below with your true TRT.")
        trt = 0.05  # placeholder sec; replace with your true TRT if you know it.

    # IntendedFor: all DWI NIfTIs
    intended_for = sorted([f"dwi/{p.name}" for p in dwidir.glob("*_dwi.nii.gz")])

    if not fmapdir.exists():
        print(f"No fmap/ directory at {fmapdir}")
        sys.exit(1)

    changed = []
    for niigz in sorted(fmapdir.glob("*.nii.gz")):
        base = niigz.with_suffix("").with_suffix("")   # strip .nii.gz
        jsn = Path(str(base) + ".json")

        J = {}
        if jsn.exists():
            try:
                J = load_json(jsn)
            except Exception:
                J = {}

        # Determine AP vs PA from filename tag
        # e.g., sub-XXX_dir-AP_run-1_epi.nii.gz
        if "_dir-AP" in niigz.name:
            J["PhaseEncodingDirection"] = dwi_sign["AP"]
        elif "_dir-PA" in niigz.name:
            J["PhaseEncodingDirection"] = dwi_sign["PA"]
        else:
            # If no dir tag, try to guess from name (rare)
            J.setdefault("PhaseEncodingDirection", dwi_sign["AP"])

        # Ensure TRT
        J.setdefault("TotalReadoutTime", trt)

        # Ensure IntendedFor includes all DWIs (safe, QSIPrep can handle)
        J["IntendedFor"] = intended_for

        save_json(jsn, J)
        changed.append((niigz.name, J["PhaseEncodingDirection"], J["TotalReadoutTime"]))

    print("\nPatched/created fmap JSONs:")
    for name, ped, trtval in changed:
        print(f"  {name}: PhaseEncodingDirection={ped}, TotalReadoutTime={trtval:.6f}s")
    print("\nDone. Re-run QSIPrep.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
