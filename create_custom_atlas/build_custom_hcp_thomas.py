#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
import tempfile
import json

import numpy as np
import nibabel as nib
from nibabel.freesurfer.io import read_annot

# -------------------- small helpers -------------------- #
def run(cmd, env=None):
    print("[cmd]", " ".join(map(str, cmd)))
    subprocess.check_call(list(map(str, cmd)), env=env)

def fsrun(fs_home, exe, args):
    fsbin = Path(fs_home) / "bin" / exe
    env = os.environ.copy()
    env["FREESURFER_HOME"] = str(fs_home)
    if "SUBJECTS_DIR" not in env:
        raise RuntimeError("SUBJECTS_DIR must be set in the environment.")
    run([fsbin] + list(map(str, args)), env=env)

# -------------------- THOMAS -------------------- #
def thomas_to_fs_with_coreg(
    fs_home, fs_t1_mgz, left_dir, right_dir, out_left_mgz, out_right_mgz
):
    """
    Use THOMAS 'crop_wmnull.nii.gz' as moving intensity and apply that LTA to the
    left 'thomas.nii.gz' and right 'thomasr.nii.gz' label volumes (nearest).
    """
    # LEFT
    l_mov = Path(left_dir) / "files" / "crop_wmnull.nii.gz"
    l_lbl = Path(left_dir) / "files" / "thomas.nii.gz"
    if not l_mov.exists() or not l_lbl.exists():
        raise FileNotFoundError(f"Left THOMAS inputs not found: {l_mov}, {l_lbl}")
    l_lta = Path(out_left_mgz).with_suffix(".lta")
    fsrun(fs_home, "mri_coreg", ["--mov", l_mov, "--ref", fs_t1_mgz, "--lta", l_lta])
    fsrun(
        fs_home, "mri_vol2vol",
        ["--mov", l_lbl, "--targ", fs_t1_mgz, "--o", out_left_mgz, "--lta", l_lta, "--nearest"],
    )

    # RIGHT
    r_mov = Path(right_dir) / "files" / "crop_wmnull.nii.gz"
    r_lbl = Path(right_dir) / "files" / "thomasr.nii.gz"
    if not r_mov.exists() or not r_lbl.exists():
        raise FileNotFoundError(f"Right THOMAS inputs not found: {r_mov}, {r_lbl}")
    r_lta = Path(out_right_mgz).with_suffix(".lta")
    fsrun(fs_home, "mri_coreg", ["--mov", r_mov, "--ref", fs_t1_mgz, "--lta", r_lta])
    fsrun(
        fs_home, "mri_vol2vol",
        ["--mov", r_lbl, "--targ", fs_t1_mgz, "--o", out_right_mgz, "--lta", r_lta, "--nearest"],
    )

# -------------------- HCP (surface -> subject -> volume) -------------------- #
def make_hcp_vol_aparc(fs_home, subjects_dir, subj, fsavg_annot_dir, out_aparc_mgz):
    """
    1) project fsaverage HCP-MMP1 annot to subject
    2) build subject-space volumetric aparc
    Returns paths to subject annot files.
    """
    subj_dir = Path(subjects_dir) / subj
    fs_t1 = subj_dir / "mri" / "T1.mgz"
    if not fs_t1.exists():
        raise FileNotFoundError(f"Subject T1 not found: {fs_t1}")

    lh_annot_src = Path(fsavg_annot_dir) / "lh.HCP-MMP1.annot"
    rh_annot_src = Path(fsavg_annot_dir) / "rh.HCP-MMP1.annot"
    if not lh_annot_src.exists() or not rh_annot_src.exists():
        raise FileNotFoundError("HCP-MMP1 annot not found in fsaverage label dir.")

    subj_label = subj_dir / "label"
    subj_label.mkdir(parents=True, exist_ok=True)
    lh_annot_trg = subj_label / "lh.HCP-MMP1.annot"
    rh_annot_trg = subj_label / "rh.HCP-MMP1.annot"

    fsrun(fs_home, "mri_surf2surf",
          ["--hemi","lh","--srcsubject","fsaverage","--trgsubject",subj,
           "--sval-annot", lh_annot_src, "--tval", lh_annot_trg])
    fsrun(fs_home, "mri_surf2surf",
          ["--hemi","rh","--srcsubject","fsaverage","--trgsubject",subj,
           "--sval-annot", rh_annot_src, "--tval", rh_annot_trg])

    fsrun(fs_home, "mri_aparc2aseg",
          ["--s", subj, "--annot", "HCP-MMP1",
           "--o", out_aparc_mgz, "--volmask"])

    return lh_annot_trg, rh_annot_trg

# -------------------- THOMAS name helpers -------------------- #
_num_name_re = re.compile(r"^(\d+)\s*[-_]\s*([A-Za-z0-9]+)")

def thomas_value_to_name_map(root_dir: Path) -> dict[int,str]:
    """
    Try to infer {value -> nucleus_name} from:
      1) per-nucleus files like '2-AV.nii.gz' in resources/<side>/files
      2) MV/nucleiVols.txt (if present)
      3) fallback to THOMAS_<value>
    """
    files_dir = root_dir / "files"
    mv_dir = root_dir / "files" / "MV"
    mapping: dict[int,str] = {}

    # (1) Per-nucleus filenames
    if files_dir.exists():
        for p in files_dir.glob("*.nii*"):
            m = _num_name_re.match(p.name)
            if m:
                val = int(m.group(1))
                name = m.group(2)
                # standardize casing
                mapping[val] = name.upper()

    # (2) nucleiVols.txt (optional; various formats exist)
    nv = mv_dir / "nucleiVols.txt"
    if nv.exists():
        try:
            for line in nv.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # try patterns: "2 AV", "2-AV", "2,AV", etc.
                toks = re.split(r"[,\s\t:-]+", line)
                if len(toks) >= 2 and toks[0].isdigit():
                    val = int(toks[0])
                    name = toks[1].upper()
                    mapping[val] = name
        except Exception:
            pass

    return mapping

# -------------------- merging THOMAS into HCP -------------------- #
def stitch_thomas_into_aparc(
    hcp_vol_mgz, thomas_left_mgz, thomas_right_mgz, out_merged_mgz,
    keep_hcp_ids=True, left_offset=8000, right_offset=9000
):
    """
    Overwrite HCP labels with THOMAS nuclei, remapping THOMAS to safe ID ranges.
    Returns remap dicts {orig_val -> new_val} for left and right.
    """
    base = nib.load(str(hcp_vol_mgz))
    data = base.get_fdata().astype(np.int32)

    left = nib.load(str(thomas_left_mgz)).get_fdata().astype(np.int32)
    right = nib.load(str(thomas_right_mgz)).get_fdata().astype(np.int32)

    th_mask = (left > 0) | (right > 0)
    # Zero out any HCP labels inside THOMAS thalamus mask before overlay
    before = int(np.count_nonzero(data[th_mask]))
    out = data.copy()
    out[th_mask] = 0
    print(f"Zeroed {before} HCP voxels inside THOMAS mask before merging.")
    left_map = {}
    right_map = {}

    if keep_hcp_ids:
        l_nonzero = left > 0
        r_nonzero = right > 0
        if l_nonzero.any():
            l_unique = np.unique(left[l_nonzero])
            for i, v in enumerate(sorted(l_unique), 1):
                left_map[int(v)] = int(left_offset + i)
            l_re = np.zeros_like(left)
            for v, nv in left_map.items():
                l_re[left == v] = nv
            left = l_re
        if r_nonzero.any():
            r_unique = np.unique(right[r_nonzero])
            for i, v in enumerate(sorted(r_unique), 1):
                right_map[int(v)] = int(right_offset + i)
            r_re = np.zeros_like(right)
            for v, nv in right_map.items():
                r_re[right == v] = nv
            right = r_re

    out[left > 0] = left[left > 0]
    out[right > 0] = right[right > 0]

    nib.save(nib.Nifti1Image(out.astype(np.int32), base.affine, base.header), str(out_merged_mgz))
    return left_map, right_map

# -------------------- TSV writer -------------------- #
def write_tsv(rows, out_path: Path):
    with open(out_path, "w") as f:
        f.write("id\tname\themi\tsource\n")
        for r in rows:
            f.write(f"{r['id']}\t{r['name']}\t{r['hemi']}\t{r['source']}\n")

def make_hcp_rows_from_annots(lh_annot, rh_annot):
    """
    Read subject-space HCP-MMP1 annots and return rows for the TSV.
    Works with both ndarray ctab and objects having .table.
    """
    rows = []
    for hemi, annot in (("L", lh_annot), ("R", rh_annot)):
        labels, ctab, names = read_annot(str(annot))

        # ctab can be ndarray or have .table
        table = getattr(ctab, "table", ctab)
        if table is None:
            # Fallback: derive unique label ids from 'labels'
            # (this is rare, but keeps us robust)
            label_ids = np.unique(labels)
            # If names list length matches label_ids length, zip them;
            # else fabricate names.
            if len(names) == len(label_ids):
                pairs = zip(label_ids, names)
            else:
                pairs = ((lid, f"label_{int(lid)}") for lid in label_ids)
            for lid, nm in pairs:
                nm = nm.decode("utf-8") if isinstance(nm, bytes) else str(nm)
                rows.append({"id": int(lid), "name": nm, "hemi": hemi, "source": "HCP-MMP1"})
            continue

        # Normal path: 5th column is the FS label id used in the volume
        if table.ndim != 2 or table.shape[1] < 5:
            raise RuntimeError(f"Unexpected ctab shape from {annot}: {table.shape}")
        label_ids = table[:, 4]

        # 'names' can be bytes; make them str
        clean_names = [n.decode("utf-8") if isinstance(n, (bytes, bytearray)) else str(n) for n in names]

        # Align by index (ctab rows correspond to names by index)
        for nid, nm in zip(label_ids, clean_names):
            rows.append({"id": int(nid), "name": nm, "hemi": hemi, "source": "HCP-MMP1"})
    return rows


def make_thomas_rows_from_maps(
    left_map, right_map, left_root: Path, right_root: Path
):
    """
    Use remap dicts (orig->new) and try to give human-readable names.
    """
    l_names = thomas_value_to_name_map(left_root)
    r_names = thomas_value_to_name_map(right_root)

    rows = []
    for orig, new in sorted(left_map.items()):
        nm = l_names.get(orig, f"THOMAS_{orig}")
        rows.append({"id": new, "name": f"{nm}", "hemi": "L", "source": "THOMAS"})
    for orig, new in sorted(right_map.items()):
        nm = r_names.get(orig, f"THOMAS_{orig}")
        rows.append({"id": new, "name": f"{nm}", "hemi": "R", "source": "THOMAS"})
    return rows


# -------------------- CLI -------------------- #
def main():
    p = argparse.ArgumentParser(
        description="Build subject HCP volumetric parcellation, coreg THOMAS (Fix B), stitch, and export TSV."
    )
    p.add_argument("--subject", required=True, help="FreeSurfer subject id (e.g., sub-256560)")
    p.add_argument("--subjects-dir", required=True, help="FreeSurfer SUBJECTS_DIR")
    p.add_argument("--fsaverage-annot-dir", required=True, help="fsaverage/label directory (has lh/rh.HCP-MMP1.annot)")
    p.add_argument("--freesurfer-home", default=os.environ.get("FREESURFER_HOME", "/Applications/freesurfer"))

    # THOMAS roots (each has files/ocrop_t1.nii.gz and files/thomas(.nii.gz|r).)
    p.add_argument("--thomas-left-root", required=True, help="left_THOMAS/resources/left")
    p.add_argument("--thomas-right-root", required=True, help="right_THOMAS/resources/right")

    p.add_argument("--out-root", required=True, help="Output directory")
    p.add_argument("--keep-hcp-ids", action="store_true", help="Keep HCP IDs; map THOMAS into high ranges")
    p.add_argument("--left-offset", type=int, default=8000)
    p.add_argument("--right-offset", type=int, default=9000)


    args = p.parse_args()

    os.environ["SUBJECTS_DIR"] = str(Path(args.subjects_dir))

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    subj_dir = Path(args.subjects_dir) / args.subject
    fs_t1 = subj_dir / "mri" / "T1.mgz"
    if not fs_t1.exists():
        raise FileNotFoundError(f"Missing FS T1: {fs_t1}")

    # 1) HCP volumetric parcellation (and get subject-space annots back)
    hcp_vol = out_root / "aparc_HCP-MMP1.mgz"
    lh_annot_trg, rh_annot_trg = make_hcp_vol_aparc(
        args.freesurfer_home, args.subjects_dir, args.subject, args.fsaverage_annot_dir, hcp_vol
    )

    # 2) THOMAS → FS 
    thomas_left_in_fs  = out_root / "thomas_left_in_FS.mgz"
    thomas_right_in_fs = out_root / "thomas_right_in_FS.mgz"
    thomas_to_fs_with_coreg(
        args.freesurfer_home, fs_t1,
        Path(args.thomas_left_root), Path(args.thomas_right_root),
        thomas_left_in_fs, thomas_right_in_fs
    )

    # 3) Stitch THOMAS into HCP
    merged = out_root / "aparc_HCPMMP1_plus_THOMAS.mgz"
    left_map, right_map = stitch_thomas_into_aparc(
        hcp_vol, thomas_left_in_fs, thomas_right_in_fs, merged,
        keep_hcp_ids=args.keep_hcp_ids,
        left_offset=args.left_offset,
        right_offset=args.right_offset
    )

    # 4) Build TSV
    rows = []
    rows += make_hcp_rows_from_annots(lh_annot_trg, rh_annot_trg)
    rows += make_thomas_rows_from_maps(left_map, right_map,
                                       Path(args.thomas_left_root), Path(args.thomas_right_root))
    tsv_path = out_root / "atlas_labels.tsv"
    write_tsv(rows, tsv_path)

    # 5) Manifest for downstream use
    manifest = {
        "subject": args.subject,
        "subjects_dir": str(Path(args.subjects_dir)),
        "outputs": {
            "hcp_aparc": str(hcp_vol),
            "thomas_left_in_fs": str(thomas_left_in_fs),
            "thomas_right_in_fs": str(thomas_right_in_fs),
            "merged_hcp_thomas": str(merged),
            "labels_tsv": str(tsv_path),
        }
    }
    with open(out_root / "build_hcp_thomas_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print("\nDone.\nOutputs:")
    for k, v in manifest["outputs"].items():
        print(f"  {k}: {v}")
    print("\nQC (Freeview):")
    print(f"  freeview -v {subj_dir/'mri/T1.mgz'} {merged}:colormap=lut:opacity=0.5")
    print(f"\nLabel table: {tsv_path}")

if __name__ == "__main__":
    sys.exit(main())
