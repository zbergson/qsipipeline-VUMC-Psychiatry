# qsipipeline-VUMC-Psychiatry

## Getting Data Into BIDS Format

In order to use the QSIPrep/QSIRecon pipelines, the data must be in BIDS format. This can be accomplished by following the steps below:

1) Download the raw dicom file from a participants' T1w scan on XNAT: scans -> 201-cs_T1W_3D_TFE_32_channel -> resources -> DICOM -> files -> name.dcm. Place this file in the T1w folder provided in this repo T1w -> T1_series -> name.dcm

2) Download the three DWI runs (b2000 AP, b1000 AP, b1000 PA) from a participant. Follow this file structure to find the dicoms: scans -> bX000ap[a/p]_fov140 -> DICOM -> files -> name.dcm. Place this file in the corresponding DWI folder (dwi_b1000_AP, dwi_b1000_PA, dwi_b2000_AP) provided in this repo. 


3) Download the freesurfer data for your participant on XNAT. Rename the folder "files" to your participant's ID in this format: sub-ID. Take the renamed folder (and its subdirectories) and place it in the freesurfer folder provided in this repo. You will see a blank license.txt file in this repo. Replace this file with your license.txt file from freesurfer. 

*IF YOU ARE MAKING A CUSTOM ATLAS WITH HCP/THOMAS*

3a) You will also see HCP annotation files in the provided freesurfer folder. These files will need to be added to the fsaverage folder provider by freesurfer to make the HCP parcellation, which is not provided by freesurfer by default. 

3b) Download the white matter nulled THOMAS data from XNAT, by downloading the LEFT and RIGHT folders. We are only using white matter nulled THOMAS data. Place the resources folder (along with its subdirectories) in the corresponding left_THOMAS or right_THOMAS folders. 

*You should now have all the required XNAT files. You are ready to "bidisfy" your data*

Please run the following shell script in your terminal:

```
python3 $SRC_ROOT/bidsify/bidsify_qsiprep.py \   
  --src $SRC_ROOT \
  --out $BIDS_ROOT \
  --sub $SUBJ
```
This calls the file "bidsify_qsiprep.py". ```$SRC_ROOT= path to your working directory```, ```$BIDS_ROOT= path to bids directory```, ```$SUBJ=sub-{insert participant ID from XNAT} from derived from XNAT ```.

After this script completes, you should have a BIDS folder that contain two subdirectories: DWI and anat. Then run the following shell script in your terminal to clean up the json files in the DWI folder and make the b1000 PA files (just nii.gz and .json) end with "_sbref". 

```
python3 $SRC_ROOT/bidsify/fix_dwi_sidecars_and_sbref.py \
  --bids-root $BIDS_ROOT \
  --sub $SUBJ
```

## Running QSIPrep

After you have successfully created your BIDS folder, we need to run QSIPrep. The code below runs the qsiprep pipeline in docker. This will have to be changed when running on accre/xnat. Note, if running on your local, this step will likely take 8-12 hours. 

```
python3 "$SRC_ROOT/run_qsiprep/qsiprep_only.py" \    
  --bids "$BIDS" \
  --deriv "$DERIV" \
  --work "$WORK" \
  --participant $SUBJ \
  --threads 12 --mem-mb 32000
```
The final output for QSIPrep will live under the derivatives folder. The output includes figures (denoising, etc.), dwi (preprocessed dwi images, along with assets used to create it), anat (ACPC space files, xfm file to help with MNI space conversion), and logs that describe the steps conducted by QSIPrep. 

## Running Built-In QSIRecon Pipeline

If you are using a built-in QSIRecon atlas (e.g, 4S, Brainnetome) the rest of the way is relatively straightforward (albeit, computationally intensive). If you are using docker on your local machine, the following code needs to be run:

```
docker run --rm --platform linux/amd64 \
  -v "${DERIV}":/in:ro \
  -v "${OUT}":/out \
  -v "${WORK}":/work \
  -v "${FS_DIR}":/fsdir:ro \
  -v "${FS_LICENSE}":/opt/freesurfer/license.txt:ro \
  -v "${SPEC_DIR}":/specs:ro \
  pennlinc/qsirecon:1.0.1 \
    /in /out participant \
    --input-type qsiprep \
    --recon-spec /specs/mrtrix_hsvs.yaml \
    --fs-subjects-dir /fsdir \
    --fs-license-file /opt/freesurfer/license.txt \
    --participant-label "${SUBJ}" \
    --atlases 4S156Parcels \
    --output-resolution 2.0 \
    --nprocs 12 --omp-nthreads 12 --mem 32000 \
    -w /work --stop-on-first-crash -v -v
```

```OUT = /derivatives/qsirecon```, ```FSDIR = /qsiprep/freesurfer```, ```FS_LICENSE = /qsiprep/freesurfer/license.txt```, ```SPEC_DIR=/qsiprep/qsirecon_specs/(yaml_file)```; under the atlases flag, choose one of the built in qsirecon atlases, such as 4S156Parcels, specify the output-resolution you identified in the QSIPrep pipeline. That is about it. If you are using MRtrix, expect the tckgen() global tractography step to take quite a while, especially if you are building more than 1M streamlines. Run this code and you are done!

## Running A CUSTOM QSIRecon Pipeline (Custom Atlas)

The main reason one would build a custom QSIRecon pipeline is to use a custom atlas. There are many steps one has to complete to do this successfully:

1) Create your custom parcellation map for each subject
2) Warp the subject space parcellation map to ACPC space -> MNI152NLin2009cAsym space (requirement of QSIRecon)
3) Create LUT that QSIREcon can use for your connectome
4) Insert this information into your QSIRecon pipeline

This is considerably harder than using the built-in QSIREcon atlases. If your research questions can be reasonably answered using these atlases, use them. If not, I have a framework (described below) for using a custom atlas. This framework/code is predicated on the use of the HCP Glasser atlas and THOMAS parcellation of subthalamic nuclei. If these parcellation maps don't work for you, I think the framework/code I have laid out here can be modified to fit your needs. 

### Creating the HCP/THOMAS parcellation map 

This is accomplished in the following steps in the code ```/qsiprep/create_custom_atlas/build_custom_hcp_thomas.py```:

1) Move the files ```lh.HCP-MMP1.annot & rh.HCP-MMP1.annot``` into the ```/freesurfer/fsaverage/labels``` folder, if you have not already done so.
2) Run the following code:
```python3 $SRC_ROOT/create_custom_atlas/build_custom_hcp_thomas.py \
  --subject "$SUBJ" \
  --subjects-dir "$SUBJECTS_DIR" \
  --fsaverage-annot-dir "$SUBJECTS_DIR/fsaverage/label" \
  --freesurfer-home "$FS_HOME" \
  --thomas-left-root  "$SRC_ROOT/left_THOMAS/resources/left" \
  --thomas-right-root "$SRC_ROOT/right_THOMAS/resources/right" \
  --out-root "$CUSTOM_ATLAS" \
  --keep-hcp-ids
```
Where: ```$SUBJECTS_DIR = /qsiprep/freesurfer```, ```$FS_HOME = where your freesurfer application lives on your computer (e.g., /Applications/freesurfer)```, ```$CUSTOM_ATLAS = /qsiprep/custom_atlas```
This code does three things: 

2a) Projects fsaverage HCP-MMP1 surface space annot to subject, builds subject-space volummetric aparc, and returns subject annot files
2b) Uses the THOMAS 'crop_wmnull.nii.gz' as moving intensity and apply that LTA to the left 'thomas.nii.gz' and right 'thomasr.nii.gz' label volumes (nearest), returns THOMAS mgz files
2c) Overwrite HCP labels with THOMAS nuclei, remapping THOMAS to safe ID ranges, and safely merging THOMAS into the HCP parcellation
2d) Outputs an atlas tsv file that will eventually be rewritten in the following steps

Once this code has been run (5-10 minutes), the output will all be places in the ```qsiprep/custom_atlas``` folder. 

### Warping from FS -> ACPC -> MNI152NLin2009cAsym

This accomplished by in the following steps using the code from ```/qsiprep/create_custom_atlas/warp_parc_to_acpc_and_mni.py```

```
python3 $SRC_ROOT/create_custom_atlas/warp_parc_to_acpc_and_mni.py \
  --fs-t1        "$SUBJECTS_DIR/$SUBJ/mri/T1.mgz" \
  --acpc-t1      "$DERIV/$SUBJ/anat/${SUBJ}_space-ACPC_desc-preproc_T1w.nii.gz" \ 
  --parc-fs      "${CUSTOM_ATLAS}aparc_HCPMMP1_plus_THOMAS.mgz" \
  --mni-t1       "$HOME/.cache/templateflow/tpl-MNI152NLin2009cAsym/tpl-MNI152NLin2009cAsym_res-01_T1w.nii.gz" \
  --xfm-acpc2mni "$DERIV/$SUBJ/anat/${SUBJ}_from-ACPC_to-MNI152NLin2009cAsym_mode-image_xfm.h5" \
  --outdir       "$CUSTOM_ATLAS" \
  --threads 4
```

This code accomplishes the following things:

1) tkregister2 (header init FS->ACPC)
2) mri_coreg (intensity coreg FS->ACPC)
3) mri_vol2vol (resample stitched parcellation we just created to ACPC)
4) antsApplyTransforms (ACPC parcellation -> MNI); Here, I use templateflow to grab the MNI152NLin2009cAsym at a resolution of 1mm; this command also uses the MNI152NLin2009cAsym xfm file from QSIPrep to complete the transformation

The output from this code lives in the ```/qsiprep/custom_atlas``` folder

### Create final formatting for QSIRecon

Earlier, the ```build_custom_hcp_thomas.py``` file created a LUT ```/qsiprep/custom_atlas/atlas_labels.tsv```. The "id" column values in this file are wrong, and we will correct this using the code below:

```
python3 $SRC_ROOT/create_custom_atlas/tidy_LUTS_qsirecon.py \
  --dseg $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz \
  --hcp-lut $SRC_ROOT/custom_atlas/hcpmmp1_original.txt \
  --out-tsv $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.tsv \
  --thomas-lut $SRC_ROOT/custom_atlas/thomas_lookup.tsv
```
This command includes the original HCP LUT provided by MRtrix3 ```$SRC_ROOT/custom_atlas/hcpmmp1_original.txt``` and a THOMAS LUT that created ```$SRC_ROOT/custom_atlas/thomas_lookup.tsv```; they should already exist in the repo when you pull it down. 

Finally, we need to format our custom atlas assets into a structure that QSIRecon will accept. This involves specifying a parent folder ```atlas-name``` and the inclusion of three files within this folder formatted the following way:

- atlas-name_dseg.tsv
- atlas-name_space-MNI152NLin2009cAsym_dseg.json
- atlas-name_space-MNI152NLin2009cAsym_res-{resolution number, in our case 01}_dseg.nii.gz

We also will need a ```dataset_description.json``` file in the overall ```/qsiprep/custom_atlas``` directory. The following code will set this up for you:

```
python3 $SRC_ROOT/create_custom_atlas/final_format_qsirecon.py \
  --atlas-name HCPMMP1plusTHOMAS \
  --atlas-root $SRC_ROOT/custom_atlas \
  --labels-tsv $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.tsv \
  --dseg-mni  $SRC_ROOT/custom_atlas/parcellation_space-MNI152NLin2009cAsym_dseg.nii.gz \
  --notes "HCP-MMP1 cortical + THOMAS thalamic stitched in subject space, warped to MNI with antsApplyTransforms."
```

### Running Custom QSIRecon pipeline with Docker

You have to specify ```--platform linux/amd64``` if you are running this on an Apple Silicon chip. You must include a ```--datasets /atlases``` flag here to get QSIRecon to load in your custom atlas. Moreover, you specify your custom atlas under the ```--atlases``` flag with your custom atlases name. In this case it is ```HCPMMP1plusTHOMAS```. 

```
docker run --rm --platform linux/amd64 \
  -v "${DERIV}":/in:ro \
  -v "${OUT}":/out \
  -v "${WORK}":/work \
  -v "${FS_DIR}":/fsdir:ro \
  -v "${ATLAS_ROOT}":/atlases:ro \
  -v "${FS_LICENSE}":/opt/freesurfer/license.txt:ro \
  -v "${SPEC_DIR}":/specs:ro \
  pennlinc/qsirecon:1.0.1 \
    /in /out participant \
    --input-type qsiprep \
    --recon-spec /specs/mrtrix_hsvs.yaml \
    --fs-subjects-dir /fsdir \
    --fs-license-file /opt/freesurfer/license.txt \
    --participant-label "${SUBJ}" \
    --datasets /atlases \
    --atlases HCPMMP1plusTHOMAS \
    --output-resolution 2.0 \
    --nprocs 12 --omp-nthreads 12 --mem 32000 \
    -w /work --stop-on-first-crash -v -v
```
