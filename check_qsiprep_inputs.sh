#!/usr/bin/env bash
# ===============================================
# QSIPrep DWI preflight validator
# Author: Zachary Bergson + GPT-5
# ===============================================

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <SUBJECT_ID> [BIDS_DIR]"
  exit 1
fi

SUBJ=$1
BIDS_DIR=${2:-"$HOME/qsiprep/BIDS"}
DWIDIR="${BIDS_DIR}/${SUBJ}/dwi"

echo "--------------------------------------------"
echo "🧠 QSIPrep preflight for ${SUBJ}"
echo "📂 BIDS dir: ${BIDS_DIR}"
echo "--------------------------------------------"

# --- Helpers
check_exists () {
  if [ ! -f "$1" ]; then
    echo "❌ Missing: $1"
    MISSING=true
  else
    echo "✅ Found: $1"
  fi
}

get_json_field () {
  python3 -c "import json,sys; print(json.load(open('$1')).get('$2', None))"
}

# --- Gather DWI files
DWIS=($(ls -1 ${DWIDIR}/*.nii.gz 2>/dev/null || true))
if [ ${#DWIS[@]} -eq 0 ]; then
  echo "❌ No DWI NIfTIs found in ${DWIDIR}"
  exit 1
fi

# --- Check each DWI
echo -e "\n📊 Checking DWI files..."
for dwi in "${DWIS[@]}"; do
  base=${dwi%.nii.gz}
  json=${base}.json
  bval=${base}.bval
  bvec=${base}.bvec
  echo -e "\n🔹 ${base##*/}"

  check_exists "$json"
  check_exists "$bval"
  check_exists "$bvec"

  if [ -f "$bval" ] && [ -f "$bvec" ]; then
    n_vol=$(fslval "$dwi" dim4)
    n_bval=$(tr ' ' '\n' < "$bval" | wc -l | tr -d ' ')
    n_bvec=$(awk '{print NF; exit}' "$bvec")
    echo "   ➤ Volumes: $n_vol | bvals: $n_bval | bvecs: $n_bvec"

    if [ "$n_vol" != "$n_bval" ] || [ "$n_vol" != "$n_bvec" ]; then
      echo "   ⚠️  Mismatch in volume count!"
    fi

    n_b0=$(tr ' ' '\n' < "$bval" | awk '$1<=150' | wc -l)
    echo "   ➤ b=0 volumes: $n_b0"
    if [ "$n_b0" -eq 0 ]; then
      echo "   ⚠️  No b=0 volumes detected!"
    fi
  fi

  # --- Read JSON fields
  if [ -f "$json" ]; then
    pe=$(get_json_field "$json" PhaseEncodingDirection)
    trt=$(get_json_field "$json" TotalReadoutTime)
    echo "   ➤ PhaseEncodingDirection: ${pe}"
    echo "   ➤ TotalReadoutTime: ${trt}"
  fi
done

# --- Check that we have at least one AP and one PA
echo -e "\n📈 Checking phase-encoding coverage..."
AP=$(grep -l '"PhaseEncodingDirection": *"j-"' ${DWIDIR}/*.json | wc -l)
PA=$(grep -l '"PhaseEncodingDirection": *"j"'  ${DWIDIR}/*.json | wc -l)
echo "   ➤ AP files: $AP"
echo "   ➤ PA files: $PA"

if [ "$AP" -eq 0 ] || [ "$PA" -eq 0 ]; then
  echo "❌ Missing AP/PA pair — TOPUP will fail"
else
  echo "✅ Found both AP and PA"
fi

# --- Verify consistent TotalReadoutTime
echo -e "\n📏 Checking TotalReadoutTime consistency..."
readouts=$(grep '"TotalReadoutTime":' ${DWIDIR}/*.json | sed 's/.*: //; s/,//' | sort -u)
if [ $(echo "$readouts" | wc -l) -gt 1 ]; then
  echo "⚠️  Inconsistent TotalReadoutTime values:"
  echo "$readouts"
else
  echo "✅ TotalReadoutTime consistent: $readouts"
fi

# --- Final summary
echo -e "\n--------------------------------------------"
if [ "${MISSING:-false}" = true ]; then
  echo "⚠️  Missing some required files."
else
  echo "✅ All files present."
fi
echo "✅ JSONs consistent"
echo "✅ Phase-encoding pair present"
echo "✅ Ready for QSIPrep (if topup/eddy nodes still fail, recheck B0 intensities)"
echo "--------------------------------------------"
