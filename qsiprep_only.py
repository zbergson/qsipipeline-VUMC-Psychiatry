#!/usr/bin/env python3
import argparse, subprocess, sys, os
from pathlib import Path

def run(cmd):
    print("\n[cmd]", " ".join(map(str, cmd)), "\n")
    subprocess.check_call(cmd)

def main():
    ap = argparse.ArgumentParser(description="Run QSIPrep (participant level) with Docker.")
    ap.add_argument("--bids", required=True)
    ap.add_argument("--deriv", required=True)
    ap.add_argument("--work", required=True)
#    ap.add_argument("--fs-license", required=True)
    ap.add_argument("--participant", default=None)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--mem-mb", type=int, default=24000)
    ap.add_argument("--use-syn", action="store_true")
    args = ap.parse_args()

    bids   = str(Path(args.bids).resolve())
    deriv  = str(Path(args.deriv).resolve())
    work   = str(Path(args.work).resolve())
#    fs_lic = str(Path(args.fs_license).resolve())

    # if not os.path.isfile(fs_lic):
    #     print(f"ERROR: FreeSurfer license not found at: {fs_lic}")
    #     sys.exit(2)

    cmd = [
    "docker","run","--rm","-it",
    "--platform","linux/amd64",
    "-v", f"{bids}:/data:ro",
    "-v", f"{deriv}:/out",
    "-v", f"{work}:/work",
    "pennlinc/qsiprep:1.0.1",
    "/data","/out","participant",
    "--dwi-only",
    "--ignore", "fieldmaps",
    "--stop-on-first-crash",
    "--output-resolution","2",
    "--nprocs", str(args.threads),
    "--omp-nthreads", str(args.threads),
    "--mem", str(args.mem_mb),
    "-w","/work","-v","-v",
    ]
    if args.participant:
        cmd += ["--participant-label", args.participant]
    if args.use_syn:
        cmd += ["--use-syn-sdc","warn"]

    run(cmd)

if __name__ == "__main__":
    main()
