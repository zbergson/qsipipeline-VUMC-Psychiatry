#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import nibabel as nib
import pandas as pd


def load_present_ids(dseg_path: Path) -> set[int]:
    img = nib.load(str(dseg_path))
    data = img.get_fdata()
    # keep integer labels > 0
    vals = np.unique(data[data > 0]).astype(int)
    return set(map(int, vals.tolist()))


# ---------- name normalization helpers ----------
LEFT_PATTERNS = (r"^L[_\- ]", r"^Left[_\- ]", r"^lh[_\- ]", r"^ctx\-lh\-", r"^LH[_\- ]")
RIGHT_PATTERNS = (r"^R[_\- ]", r"^Right[_\- ]", r"^rh[_\- ]", r"^ctx\-rh\-", r"^RH[_\- ]")

def detect_hemi(name: str) -> str | None:
    for p in LEFT_PATTERNS:
        if re.search(p, name, flags=re.IGNORECASE):
            return "L"
    for p in RIGHT_PATTERNS:
        if re.search(p, name, flags=re.IGNORECASE):
            return "R"
    return None

def strip_hemi_prefix(name: str) -> str:
    # remove common hemi prefixes; keep ROI core
    name = re.sub(r"^(ctx\-lh\-|ctx\-rh\-)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^(lh|rh)[_\- ]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^(L|R|Left|Right|LH|RH)[_\- ]", "", name, flags=re.IGNORECASE)
    # unify trailing _ROI to just ROI name (we keep the base without side)
    name = re.sub(r"(_ROI)$", "", name, flags=re.IGNORECASE)
    return name

def normalized_lr(name: str) -> tuple[str | None, str]:
    hemi = detect_hemi(name)
    base = strip_hemi_prefix(name)
    # Some HCP names include things like "Area_4"; keep underscores
    base = base.strip()
    return hemi, base


# ---------- HCP LUT (MRtrix) ----------
def load_hcp_lut(hcp_txt: Path) -> dict[int, tuple[str, str]]:
    """
    Returns {index: (normalized_label, source)}, source="HCP-MMP1".
    Accepts MRtrix-style two-column files (index, name) or more columns.
    """
    mapping: dict[int, tuple[str, str]] = {}
    # Robust read: try whitespace-delimited, ignore comment lines
    rows = []
    with open(hcp_txt, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            parts = re.split(r"\s+", line)
            # Expect at least: index name ...
            try:
                idx = int(parts[0])
            except ValueError:
                continue
            if len(parts) >= 2:
                name = parts[1]
            else:
                # skip if no name
                continue
            hemi, base = normalized_lr(name)
            if hemi:
                label = f"{hemi}-{base}"
            else:
                label = base  # rarely happens; keep as-is
            mapping[idx] = (label, "HCP-MMP1")
    return mapping


# ---------- THOMAS LUT (TSV) ----------
def load_thomas_lut(thomas_tsv: Path) -> dict[int, tuple[str, str]]:
    """
    Returns {index: (normalized_label, source)}, source="THOMAS".
    Accepts TSV with at least columns for id and a label or name.
    Optional 'hemi' column; otherwise inferred from label text.
    """
    df = pd.read_csv(thomas_tsv, sep="\t")
    # Find columns
    col_id = next((c for c in df.columns if c.lower() in {"id", "index", "label_id"}), None)
    col_name = next((c for c in df.columns if c.lower() in {"name", "label"}), None)
    col_hemi = next((c for c in df.columns if "hemi" in c.lower()), None)

    if col_id is None or col_name is None:
        raise ValueError(f"THOMAS TSV needs at least 'id' and 'label'/'name' columns. Found: {list(df.columns)}")

    mapping: dict[int, tuple[str, str]] = {}
    for _, row in df.iterrows():
        try:
            idx = int(row[col_id])
        except Exception:
            continue
        raw_name = str(row[col_name])
        hemi = None
        if col_hemi is not None and pd.notna(row[col_hemi]):
            hemi = str(row[col_hemi]).strip().upper()[0]  # L/R
            if hemi not in {"L", "R"}:
                hemi = None
        # infer if not present
        if hemi is None:
            hemi = detect_hemi(raw_name)

        base = strip_hemi_prefix(raw_name)
        label = f"{hemi}-{base}" if hemi in {"L", "R"} else base
        mapping[idx] = (label, "THOMAS")
    return mapping


def main():
    ap = argparse.ArgumentParser(description="Build a tidy atlas TSV (index,label,source) from HCP/THOMAS lookups restricted to labels present in a dseg.")
    ap.add_argument("--dseg", required=True, type=Path, help="Parcellation NIfTI (e.g., parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz)")
    ap.add_argument("--hcp-lut", required=True, type=Path, help="MRtrix HCP-MMP1 lookup text file (e.g., hcpmmp1_original.txt)")
    ap.add_argument("--thomas-lut", required=True, type=Path, help="THOMAS lookup TSV")
    ap.add_argument("--out-tsv", required=True, type=Path, help="Output TSV with columns: index, label, source")
    args = ap.parse_args()

    if not args.dseg.exists():
        sys.exit(f"ERROR: dseg not found: {args.dseg}")
    if not args.hcp_lut.exists():
        sys.exit(f"ERROR: HCP LUT not found: {args.hcp_lut}")
    if not args.thomas_lut.exists():
        sys.exit(f"ERROR: THOMAS LUT not found: {args.thomas_lut}")

    present = load_present_ids(args.dseg)
    hcp_map = load_hcp_lut(args.hcp_lut)
    thomas_map = load_thomas_lut(args.thomas_lut)

    rows = []
    for idx in sorted(present):
        if idx in hcp_map:
            label, source = hcp_map[idx]
        elif idx in thomas_map:
            label, source = thomas_map[idx]
        else:
            label, source = (f"Unknown-{idx}", "Unknown")
        rows.append({"index": int(idx), "label": label, "source": source})

    out_df = pd.DataFrame(rows, columns=["index", "label", "source"])
    args.out_tsv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out_tsv, sep="\t", index=False)
    print(f"Wrote {len(out_df)} rows -> {args.out_tsv}")


if __name__ == "__main__":
    main()
