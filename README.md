# qsipipeline-VUMC-Psychiatry

## 🧠 Getting Data Into BIDS Format

To use the **QSIPrep/QSIRecon** pipelines, your data must first be organized in **BIDS format**. Follow the steps below carefully.

---

### 1️⃣ T1-weighted DICOM

Download the T1-weighted DICOM file from XNAT:

```
scans -> 201-cs_T1W_3D_TFE_32_channel -> resources -> DICOM -> files -> name.dcm
```

Place this file in:

```
T1w -> T1_series -> name.dcm
```

---

### 2️⃣ DWI Runs (b2000 AP, b1000 AP, b1000 PA)

Download the three DWI runs from XNAT:

```
scans -> bX000ap[a/p]_fov140 -> DICOM -> files -> name.dcm
```

Then place each DICOM in the corresponding folder provided in this repo:

- `dwi_b1000_AP`
- `dwi_b1000_PA`
- `dwi_b2000_AP`

---

### 3️⃣ FreeSurfer Data

1. Download the FreeSurfer data for your participant from XNAT.
2. Rename the folder **“files”** to your participant’s ID in this format: `sub-ID`.
3. Move the renamed folder (and its subdirectories) into the `freesurfer` folder in this repo.
4. Replace the blank `license.txt` file in this repo with your actual **FreeSurfer license**.

---

### ⚙️ Optional: Creating a Custom Atlas (HCP + THOMAS)

If you plan to make a **custom atlas**:

- Add HCP annotation files to the `fsaverage` folder provided by FreeSurfer.
- Download **white-matter-nulled THOMAS data** (LEFT and RIGHT folders) from XNAT.
- Place the `resources` folders in the corresponding `left_THOMAS` and `right_THOMAS` directories.

---

You should now have all required **XNAT files**. Proceed to **BIDSify your data**:

```bash
python3 $SRC_ROOT/bidsify/bidsify_qsiprep.py   --src $SRC_ROOT   --out $BIDS_ROOT   --sub $SUBJ
```

Where:
- `$SRC_ROOT` = path to your working directory  
- `$BIDS_ROOT` = path to your BIDS directory  
- `$SUBJ` = participant ID from XNAT (e.g., `sub-123456`)

After completion, your BIDS folder should contain two subdirectories: `dwi` and `anat`.

Then clean up and label the b1000 PA files as `_sbref`:

```bash
python3 $SRC_ROOT/bidsify/fix_dwi_sidecars_and_sbref.py   --bids-root $BIDS_ROOT   --sub $SUBJ
```

---

## ⚡ Running QSIPrep

Once the BIDS folder is ready, run **QSIPrep**. Example (for local Docker run):

```bash
python3 "$SRC_ROOT/run_qsiprep/qsiprep_only.py"   --bids "$BIDS"   --deriv "$DERIV"   --work "$WORK"   --participant $SUBJ   --threads 12 --mem-mb 32000
```

🕒 Expected runtime: 8–12 hours locally.

Output (under `derivatives/`):
- Preprocessed **DWI** and **anat** files
- **Figures** (e.g., denoising)
- **Transform files** for MNI conversion
- **Logs** describing the pipeline steps

---

## 🧩 Running a Built-In QSIRecon Pipeline

If using a built-in atlas (e.g., *4S*, *Brainnetome*), run:

```bash
docker run --rm --platform linux/amd64   -v "${DERIV}":/in:ro   -v "${OUT}":/out   -v "${WORK}":/work   -v "${FS_DIR}":/fsdir:ro   -v "${FS_LICENSE}":/opt/freesurfer/license.txt:ro   -v "${SPEC_DIR}":/specs:ro   pennlinc/qsirecon:1.0.1     /in /out participant     --input-type qsiprep     --recon-spec /specs/mrtrix_hsvs.yaml     --fs-subjects-dir /fsdir     --fs-license-file /opt/freesurfer/license.txt     --participant-label "${SUBJ}"     --atlases 4S156Parcels     --output-resolution 2.0     --nprocs 12 --omp-nthreads 12 --mem 32000     -w /work --stop-on-first-crash -v -v
```

🧾 Example variable setup:
```
OUT=/derivatives/qsirecon
FS_DIR=/qsiprep/freesurfer
FS_LICENSE=/qsiprep/freesurfer/license.txt
SPEC_DIR=/qsiprep/qsirecon_specs/(yaml_file)
```

If using **MRtrix**, note that the **tckgen() global tractography** step can take a long time (especially >1M streamlines).

---

## 🧬 Running a Custom QSIRecon Pipeline

A custom QSIRecon pipeline is needed for custom atlases.

**Main steps:**

1. Create a subject-level parcellation map  
2. Warp it (ACPC → MNI)  
3. Create a compatible LUT  
4. Integrate atlas + LUT into QSIRecon

---

### Step 1: Build the HCP/THOMAS Parcellation Map

```bash
python3 $SRC_ROOT/create_custom_atlas/build_custom_hcp_thomas.py   --subject "$SUBJ"   --subjects-dir "$SUBJECTS_DIR"   --fsaverage-annot-dir "$SUBJECTS_DIR/fsaverage/label"   --freesurfer-home "$FS_HOME"   --thomas-left-root "$SRC_ROOT/left_THOMAS/resources/left"   --thomas-right-root "$SRC_ROOT/right_THOMAS/resources/right"   --out-root "$CUSTOM_ATLAS"   --keep-hcp-ids
```

Where:
```
$SUBJECTS_DIR=/qsiprep/freesurfer
$FS_HOME=/Applications/freesurfer
$CUSTOM_ATLAS=/qsiprep/custom_atlas
```

Outputs to `/qsiprep/custom_atlas` (~5–10 minutes).

---

### Step 2: Warp FS → ACPC → MNI152NLin2009cAsym

```bash
python3 $SRC_ROOT/create_custom_atlas/warp_parc_to_acpc_and_mni.py   --fs-t1 "$SUBJECTS_DIR/$SUBJ/mri/T1.mgz"   --acpc-t1 "$DERIV/$SUBJ/anat/${SUBJ}_space-ACPC_desc-preproc_T1w.nii.gz"   --parc-fs "${CUSTOM_ATLAS}aparc_HCPMMP1_plus_THOMAS.mgz"   --mni-t1 "$HOME/.cache/templateflow/tpl-MNI152NLin2009cAsym/tpl-MNI152NLin2009cAsym_res-01_T1w.nii.gz"   --xfm-acpc2mni "$DERIV/$SUBJ/anat/${SUBJ}_from-ACPC_to-MNI152NLin2009cAsym_mode-image_xfm.h5"   --outdir "$CUSTOM_ATLAS"   --threads 4
```

Performs:
1. `tkregister2` (FS→ACPC header alignment)  
2. `mri_coreg` (intensity coregistration)  
3. `mri_vol2vol` (resampling)  
4. `antsApplyTransforms` (ACPC→MNI)

---

### Step 3: Correct LUT IDs

```bash
python3 $SRC_ROOT/create_custom_atlas/tidy_LUTS_qsirecon.py   --dseg $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz   --hcp-lut $SRC_ROOT/custom_atlas/hcpmmp1_original.txt   --out-tsv $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.tsv   --thomas-lut $SRC_ROOT/custom_atlas/thomas_lookup.tsv
```

---

### Step 4: Format for QSIRecon

Required structure:
```
atlas-name/
├── atlas-name_dseg.tsv
├── atlas-name_space-MNI152NLin2009cAsym_dseg.json
└── atlas-name_space-MNI152NLin2009cAsym_res-01_dseg.nii.gz
```

Run:

```bash
python3 $SRC_ROOT/create_custom_atlas/final_format_qsirecon.py   --atlas-name HCPMMP1plusTHOMAS   --atlas-root $SRC_ROOT/custom_atlas   --labels-tsv $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.tsv   --dseg-mni $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz   --notes "HCP-MMP1 cortical + THOMAS thalamic stitched in subject space, warped to MNI with antsApplyTransforms."
```

---

### Step 5: Run Custom QSIRecon with Docker

For Apple Silicon, include `--platform linux/amd64`.  
Mount your atlas with `--datasets /atlases` and specify it under `--atlases`.

```bash
docker run --rm --platform linux/amd64   -v "${DERIV}":/in:ro   -v "${OUT}":/out   -v "${WORK}":/work   -v "${FS_DIR}":/fsdir:ro   -v "${ATLAS_ROOT}":/atlases:ro   -v "${FS_LICENSE}":/opt/freesurfer/license.txt:ro   -v "${SPEC_DIR}":/specs:ro   pennlinc/qsirecon:1.0.1     /in /out participant     --input-type qsiprep     --recon-spec /specs/mrtrix_hsvs.yaml     --fs-subjects-dir /fsdir     --fs-license-file /opt/freesurfer/license.txt     --participant-label "${SUBJ}"     --datasets /atlases     --atlases HCPMMP1plusTHOMAS     --output-resolution 2.0     --nprocs 12 --omp-nthreads 12 --mem 32000     -w /work --stop-on-first-crash -v -v
```

This will take a significant amount of time to complete if using >1M streamlines. The results will live in `/derivatives/qsirecon`, including exemplar streamlines, the connectomes, and QA figures. 
---