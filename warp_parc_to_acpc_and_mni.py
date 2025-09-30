#!/usr/bin/env python3
"""
warp_parc_to_acpc_and_mni.py

Runs the exact sequence you’ve been executing manually:

1) tkregister2    : header-based init FS->ACPC  (DAT + init LTA)
2) mri_coreg      : intensity-based coreg FS->ACPC (DAT + refined LTA)
3) mri_vol2vol    : resample stitched parcellation from FS grid -> ACPC (NN)
4) antsApplyTransforms : ACPC parcellation -> MNI152NLin2009cAsym (NN)

All inputs are paths you already have. Outputs land in --outdir.
"""

import argparse, os, sys, shutil, subprocess
from pathlib import Path

def run(cmd, env=None):
    """Print + execute a command, raising on error."""
    print("[cmd]", " ".join(map(str, cmd)), flush=True)
    subprocess.check_call(list(map(str, cmd)), env=env)

def which_or_die(name):
    p = shutil.which(name)
    if p is None:
        sys.exit(f"ERROR: could not find executable '{name}' in PATH")
    return p

def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--fs-t1",        required=True, help="FreeSurfer T1 (e.g., $SUBJECTS_DIR/sub-XXXX/mri/T1.mgz)")
    ap.add_argument("--acpc-t1",      required=True, help="ACPC-space T1 from qsiprep (…_space-ACPC_desc-preproc_T1w.nii.gz)")
    ap.add_argument("--parc-fs",      required=True, help="Stitched parcellation in FS/native space (e.g., .mgz)")
    ap.add_argument("--mni-t1",       required=True, help="MNI152NLin2009cAsym T1 (TemplateFlow res-01 T1w)")
    ap.add_argument("--xfm-acpc2mni", required=True, help="ACPC→MNI transform (H5) from qsiprep")
    ap.add_argument("--outdir",       required=True, help="Output directory")
    ap.add_argument("--threads",      type=int, default=4, help="Threads for mri_coreg")
    ap.add_argument("--parc-acpc-out", default=None, help="Optional explicit ACPC parcellation output (nii.gz or mgz)")
    ap.add_argument("--parc-mni-out",  default=None, help="Optional explicit MNI parcellation output (nii.gz)")
    args = ap.parse_args()

    # Ensure executables exist
    tkregister2 = which_or_die("tkregister2")
    mri_coreg   = which_or_die("mri_coreg")
    mri_vol2vol = which_or_die("mri_vol2vol")
    antsApply   = which_or_die("antsApplyTransforms")

    # Resolve paths
    FS_T1   = Path(args.fs_t1).resolve()
    ACPC_T1 = Path(args.acpc_t1).resolve()
    PARC_FS = Path(args.parc_fs).resolve()
    MNI_T1  = Path(args.mni_t1).resolve()
    XFM     = Path(args.xfm_acpc2mni).resolve()
    OUTDIR  = Path(args.outdir).resolve()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # Derived outputs
    LTA_INIT   = OUTDIR/"FS2ACPC_init.lta"
    REG_INIT   = OUTDIR/"FS2ACPC.dat"
    REG_COREG  = OUTDIR/"FS2ACPC_coreg.dat"
    LTA_COREG  = OUTDIR/"FS2ACPC_coreg.lta"

    if args.parc_acpc_out:
        PARC_ACPC = Path(args.parc_acpc_out).resolve()
    else:
        # Default to NIfTI in the outdir
        PARC_ACPC = OUTDIR/"parcellation_space-ACPC_dseg.nii.gz"

    if args.parc_mni_out:
        PARC_MNI = Path(args.parc_mni_out).resolve()
    else:
        PARC_MNI = OUTDIR/"parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz"

    # Sanity checks
    for pth in [FS_T1, ACPC_T1, PARC_FS, MNI_T1, XFM]:
        if not pth.exists():
            sys.exit(f"ERROR: missing input: {pth}")

    print("\n== Step 1: tkregister2 (header init FS->ACPC) ==")
    run([
        tkregister2,
        "--mov",  FS_T1,
        "--targ", ACPC_T1,
        "--regheader",
        "--noedit",
        "--reg",   REG_INIT,
        "--ltaout", LTA_INIT,
    ])

    print("\n== Step 2: mri_coreg (intensity coreg FS->ACPC) ==")
    # Note: modern FreeSurfer uses --ref (not --targ) for mri_coreg
    run([
        mri_coreg,
        "--mov", FS_T1,
        "--ref", ACPC_T1,
        "--reg", REG_COREG,
        "--lta", LTA_COREG,
        "--threads", args.threads,
    ])

    print("\n== Step 3: mri_vol2vol (resample stitched parcellation to ACPC, NN) ==")
    run([
        mri_vol2vol,
        "--mov",  PARC_FS,
        "--targ", ACPC_T1,
        "--o",    PARC_ACPC,
        "--lta",  LTA_COREG,
        "--nearest",
        "--no-save-reg",
    ])

    print("\n== Step 4: antsApplyTransforms (ACPC parcellation -> MNI, NN) ==")
    run([
        antsApply,
        "-d", "3", "-v", "1",
        "-i",  PARC_ACPC,
        "-r",  MNI_T1,
        "-o",  PARC_MNI,
        "-n",  "NearestNeighbor",
        "-t",  XFM,
    ])

    print("\nAll done ✅")
    print(f" ACPC parcellation : {PARC_ACPC}")
    print(f" MNI parcellation  : {PARC_MNI}")
    print(f" Init reg (DAT)    : {REG_INIT}")
    print(f" Coreg reg (DAT)   : {REG_COREG}")
    print(f" Coreg LTA         : {LTA_COREG}")

if __name__ == "__main__":
    main()
