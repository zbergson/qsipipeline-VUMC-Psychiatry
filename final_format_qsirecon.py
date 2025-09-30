#!/usr/bin/env python3
"""
Package a stitched atlas (HCP+THOMAS) into qsirecon-compatible atlas directory.

Expected output format:
  atlas-<NAME>/
    atlas-<NAME>_dseg.tsv
    atlas-<NAME>_space-MNI152NLin2009cAsym_res-01_dseg.nii.gz
    atlas-<NAME>_space-MNI152NLin2009cAsym_dseg.json
"""

import argparse, json, shutil
from pathlib import Path
import pandas as pd
from datetime import datetime

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas-name", default="HCPMMP1plusTHOMAS",
                    help="Base name for atlas (e.g., HCPMMP1plusTHOMAS)")
    ap.add_argument("--atlas-root", required=True,
                    help="Directory to write atlas-<name>")
    ap.add_argument("--labels-tsv", required=True,
                    help="Labels table (id, name, hemi, ...)")
    ap.add_argument("--dseg-mni", required=True,
                    help="NIfTI parcellation already in MNI152NLin2009cAsym space")
    ap.add_argument("--notes", default=None, help="Optional provenance notes")
    args = ap.parse_args()

    atlas_dir = Path(args.atlas_root) / f"atlas-{args.atlas_name}"
    atlas_dir.mkdir(parents=True, exist_ok=True)

    # Copy TSV
    tsv_dst = atlas_dir / f"atlas-{args.atlas_name}_dseg.tsv"
    df = pd.read_csv(args.labels_tsv, sep="\t")
    df.to_csv(tsv_dst, sep="\t", index=False)

    # Copy NIfTI (rename with res-01, MNI)
    nii_dst = atlas_dir / f"atlas-{args.atlas_name}_space-MNI152NLin2009cAsym_res-01_dseg.nii.gz"
    shutil.copyfile(args.dseg_mni, nii_dst)

    # Write JSON sidecar
    meta = {
        "SpatialReference": "MNI152NLin2009cAsym",
        "Resolution": "res-01",
        "LabelMap": "dseg",
        "Description": f"Custom stitched atlas {args.atlas_name} (HCP-MMP1 + THOMAS nuclei)",
        "GeneratedBy": [{
            "Name": "package_custom_atlas.py",
            "Version": "1.0",
            "Date": datetime.utcnow().isoformat() + "Z"
        }]
    }
    if args.notes:
        meta["Notes"] = args.notes

    json_dst = atlas_dir / f"atlas-{args.atlas_name}_space-MNI152NLin2009cAsym_dseg.json"
    with open(json_dst, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"✅ Packaged atlas under: {atlas_dir}")

if __name__ == "__main__":
    main()
