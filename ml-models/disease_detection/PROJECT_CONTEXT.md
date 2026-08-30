# Vanda Orchid Disease Detection — Component Context

**Purpose of this file:** hand-off context for an AI coding assistant working in this
repository. Read this before making changes to `ml-models/disease_detection/`.

**Last updated:** 29 August 2026 — both models trained and evaluated. Measured results in section 4c.
**Time budget remaining:** ~1.5 days to complete disease model + severity + IoT integration

---

## 1. Project overview

Final-year (4th year) software engineering research project on **Vanda orchids**.
The full system has several components; this document covers one of them.

**My component: disease identification, severity assessment, and treatment
recommendation.**

Given a photograph of an orchid, the system should return:

1. **Disease name** (or healthy, or "unidentified — not healthy")
2. **Plant part** affected
3. **Severity grade**
4. **Treatment recommendation** appropriate to the disease and severity

Target users are **orchid growers** in Sri Lanka. Field photographs are collected
primarily from the **Nuwara Eliya** highland region.

There is a second user role, **admin** (intended to be a person at an orchid
research institute), who can contribute new labelled training data. See section 7.

---

## 2. Scope decision — IMPORTANT

The project originally planned **five disease classes**: Phyllosticta Leaf Spot,
Black Leaf Spot, Anthracnose, Phytophthora Black Rot, and Sooty Mold.

**This was narrowed on 29 Aug 2026 to three classes**, because only these have
enough real field images to train on:

| Class | Real images | Folder name (everywhere) |
|---|---:|---|
| Black Leaf Spot | 152 | `black_leaf_spot` |
| Phyllosticta Leaf Spot | 275 | `phyllosticta_leaf_spot` |
| Healthy | 240 | `healthy` |
| **Total** | **667** | |

**Counts verified on disk 29 Aug 2026.** An earlier draft of this file said
230 healthy images and 657 total; the real figures are 240 and 667. Use the
numbers above in the report.

**Folder naming — settled 29 Aug 2026.** The `raw/` folders were originally
created by hand with hyphens (`black-leaf-spot`). They were renamed to
underscores so a single spelling of each class name is used everywhere: raw,
processed, split, Keras class labels, augmentation manifests, the treatment
knowledge base and the backend. Keras derives class labels from folder names,
so one spelling removes a category of silent mismatch bug.

**One photograph was also renamed.** `20260722_175803.jpg` was the only file
never renamed by hand. Filenames starting with a digit sort before filenames
starting with a letter, so on the first pipeline run it was processed first and
became `processed/Black_LS_0001.jpg`, shifting every other Black Leaf Spot
image down one position. It is now `Black_LS_0152.jpg`, which sorts last, so
`raw/Black_LS_NNNN.jpg` and `processed/Black_LS_NNNN.jpg` are the same
photograph for every N. The pipeline was rebuilt afterwards, before any
labelling was entered. Full note in `data/raw/PROVENANCE.md`.

**Consequence for later.** Because filenames are now stable, the dataset can be
rebuilt at any time without invalidating hand-entered severity labels. But if a
photograph is ever added to or removed from `raw/`, the numbering shifts and the
labels would silently point at the wrong images. Add new images with the next
unused number; never renumber.

Consequences of this decision:

- **Both trained diseases are leaf diseases.** The earlier folder structure of
  `<disease>/leaf/` and `<disease>/stem/` subfolders is **dropped**. Class folders
  are now flat. Any code that walks plant-part subfolders needs updating.
- **Sunburn will be added later** if time allows. Anthracnose, Fusarium and
  Phytophthora are set aside (too few images: 791 anthracnose images exist from an
  earlier collection but that class is out of scope for now; fusarium had 13 and
  phytophthora 20, both unusable).
- **Diseases outside the three classes are handled by confidence thresholding**,
  not by a trained "other" class. If max softmax probability falls below a
  threshold tuned on the validation set (start around 0.60–0.75), the system
  outputs "Unidentified condition — not healthy, expert review recommended."
  This is a deliberate design decision and should be described as such in the
  report.

**Note for the report:** earlier project documents list a different class set.
The report must be made internally consistent with the three classes above.

---

## 3. Repository layout

```
<repo root>/
├── backend/
├── docs/
├── iot/
├── mobile/
├── ml-models/
│   ├── disease_detection/          ← MY COMPONENT
│   │   ├── .venv/
│   │   ├── data/
│   │   ├── models/
│   │   ├── src/
│   │   └── tools/
│   ├── growth_stage/
│   ├── hybrid_pollination/
│   ├── smart_watering/
│   ├── shared/
│   └── notebooks/
└── requirements.txt
```

Other `ml-models/` subfolders belong to teammates. **Do not modify them.**

Two companion documents live beside this one:

- `HOW_TO_RUN.md` — every command, a rehearsed **viva demo script** with what to
  say while each runs, a troubleshooting table, and the Colab procedure.
- `data/raw/PROVENANCE.md` — what was renamed in `raw/` and why.

### Data folder structure

```
ml-models/disease_detection/data/
├── raw/                        original field photographs — NEVER MODIFIED
│   ├── black-leaf-spot/                152 images   (note: hyphens)
│   ├── phyllosticta-leaf-spot/         275 images
│   └── healthy/                        240 images
│
├── processed/                  cleaned copies (EXIF fixed, .jpg, max 1024px)
│   ├── black_leaf_spot/                Black_LS_0001.jpg ...
│   ├── phyllosticta_leaf_spot/         Phyllosticta_LS_0001.jpg ...
│   └── healthy/                        Healthy_0001.jpg ...
│
├── split/                      ORIGINALS ONLY, divided 80/10/10
│   ├── train/<class>/
│   ├── validation/<class>/
│   └── test/<class>/
│
├── split_augmented/            what training actually reads
│   ├── train/<class>/                  augmented 54x
│   ├── validation/<class>/             copied unchanged from split/
│   └── test/<class>/                   copied unchanged from split/
│
├── severity_labels.csv         667 rows; 240 healthy auto 'none', 427 to label
├── leakage_report.txt          evidence for the results chapter
└── split/split_manifest.csv    which original went into which split
```

Each `processed/<class>/` also contains `rename_map.csv`, tracing every new
filename back to its original camera file. Each `split_augmented/train/<class>/`
contains `manifest_<class>.csv`, whose `source_image` column is what the
leakage check reads.

**Design principle:** `raw/` is the only irreplaceable folder. Every other folder is
regenerable by rerunning a script with a fixed random seed (42).

---

## 4. Current state — what is DONE

- 667 field images collected, sorted into three class folders under `data/raw/`
- Earlier baseline model existed for a different 5-class dataset — **superseded**,
  do not reuse its metrics
- Python environment created at `.venv/` with `requirements.txt`
- Five data-preparation scripts written and tested (see section 5)
- **The whole data pipeline has been run.** Steps 1–6 of section 6 are complete:

  | Stage | Result |
  |---|---|
  | EXIF survey | 667 scanned, **330 stored sideways**, 0 corrupt, 0 duplicates |
  | `processed/` | 667 images, upright, RGB, ≤1024px — **1.5 GB → 135 MB** |
  | `split/` | 533 train / 67 validation / 67 test, seed 42, stratified |
  | `split_augmented/train/` | **28,782 files** from 533 originals (54×), 3.8 GB |
  | `split_augmented/{validation,test}/` | 134 original photographs, unmodified |
  | Leakage verification | **PASS on all three checks** — see `data/leakage_report.txt` |

- `data/severity_labels.csv` generated: 667 rows, 240 healthy pre-filled `none`,
  **427 diseased rows awaiting hand-labelling**

## 4b. Current state — what is NOT done

The data pipeline, both models and the treatment knowledge base are done.

- [x] ~~EXIF check~~ — 330 of 667 images physically rotated
- [x] ~~`processed/` / `split/` / `split_augmented/`~~ — 667 / 533·67·67 / 28,782
- [x] ~~Leakage verification~~ — PASS on all three checks
- [x] ~~`severity_labels.csv`~~ — **all 427 diseased rows hand-graded**
- [x] ~~`train.py`, `evaluate.py`~~ — written, and used to produce section 4c
- [x] ~~Disease model~~ — trained on Colab T4, **macro-F1 0.778 on test**
- [x] ~~Severity model~~ — trained, **within-one-grade 0.907 on test**
- [x] ~~Architecture comparison~~ — `compare_models.py`, section 4c
- [x] ~~Treatment knowledge base~~ — `treatment_kb.json` + `treatment.py`

Remaining:

- [ ] **Chemical doses in `treatment_kb.json` are unverified.** Every dose is
      `"VERIFY"` with `"verified": false`. `treatment.py` substitutes a referral
      message, so nothing unsafe reaches a grower, but the entries are not
      finished until sourced from the product label and the Sri Lanka
      Department of Agriculture registered list.
- [ ] End-to-end inference script joining both models to the knowledge base
- [ ] Backend inference endpoint
- [ ] Admin upload / retrain flow
- [ ] IoT integration
- [ ] **Re-split stratified by SEVERITY** — see the limitation in section 4c.
      This is the single highest-value fix for the severity model.

---

## 4c. RESULTS — measured, 29 August 2026

All figures below come from `evaluate.py` and `evaluate_severity.py` on the
**held-out test set of 67 original photographs** that contributed nothing to
training (proven by `tools/check_leakage.py`; see `data/leakage_report.txt`).

Trained on Google Colab, Tesla T4, TensorFlow 2.20.0. The local environment is
TensorFlow 2.21.0 and the saved `.keras` file was confirmed to load there.

**Do not quote `peak_val_accuracy_any_epoch` from the metadata files.**
EarlyStopping keeps the lowest-val_loss epoch, which is usually a different one,
so that field is higher than the saved model actually scores. Only the
`evaluate*.py` outputs are reportable.

### Model 1 — disease classifier

| | Test | Validation |
|---|---:|---:|
| **Macro F1** | **0.7779** | 0.7691 |
| Weighted F1 | 0.8026 | 0.7904 |
| Accuracy | 0.8060 (54/67) | 0.7910 |

Training ran 21 epochs (16 frozen + 5 fine-tuning) before EarlyStopping.

Per class, on test:

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| black_leaf_spot | 0.6000 | 0.6000 | 0.6000 | 15 |
| healthy | 0.8889 | **1.0000** | **0.9412** | 24 |
| phyllosticta_leaf_spot | 0.8400 | 0.7500 | 0.7925 | 28 |

Confusion matrix (rows = true, columns = predicted):

```
                        black   healthy   phyll    total
black_leaf_spot            9        2        4       15
healthy                    0       24        0       24
phyllosticta_leaf_spot     6        1       21       28
```

**Reading this:**

- **Healthy is effectively solved.** 24/24 recall and zero healthy plants
  misdiagnosed as diseased — no wasted spraying.
- **10 of the 13 errors are black ↔ phyllosticta confusion.** These are two
  dark leaf-spot diseases on the same species, so the model fails the way a
  non-expert human fails. That is a defensible error mode, not random noise.
- **Black Leaf Spot is weakest (F1 0.60) and is also the smallest class** —
  122 training originals against Phyllosticta's 219. Direct evidence that more
  data, rather than a better architecture, is what would improve it.
- **3 of 43 diseased plants were called healthy** — the costly error for a
  grower. State this rather than hiding it.
- One error is worth mentioning honestly: `Black_LS_0008.jpg` was called
  healthy at 0.995 confidence. A confidence threshold cannot catch a
  confidently wrong prediction.

### Operating threshold for unknown conditions — 0.70

Chosen from the **validation** sweep. Choosing it from the test sweep would be
tuning on the test set.

| Threshold | Kept | Accuracy on kept | Referred to expert |
|---:|---:|---:|---:|
| 0.60 | 89.6% | 88.3% | 7 |
| **0.70** | **83.6%** | **91.1%** | **11** |
| 0.75 | 77.6% | 94.2% | 15 |

At 0.70 the system answers 84% of cases automatically at 91% accuracy, up from
79% unfiltered. It behaves consistently on test (85% kept, 86% accurate), which
confirms the choice was not fitted to validation noise.

**Honest caveat for the report:** every image in these sweeps belongs to one of
the three trained classes, so anything rejected is a *known* disease being
turned away. The benefit — correctly rejecting a disease the model was never
trained on — cannot be measured, because no images of such a disease were
collected. Say so rather than implying the threshold was validated against
unknown classes.

### Architecture comparison

Five epochs each, frozen base, identical data, seed 42, scored on **validation**.
Never on test — selecting an architecture by test score is tuning on the test set.

| Model | Macro F1 | Params | Size |
|---|---:|---:|---:|
| efficientnetb0 | 0.8318 | 4,053,414 | 17.1 MB |
| **mobilenetv2 (chosen)** | 0.8220 | 2,261,827 | **9.7 MB** |
| scratch_cnn (control) | 0.6025 | 94,531 | 1.2 MB |

**Three conclusions:**

1. **Transfer learning was necessary.** The from-scratch CNN reaches 0.6025
   against MobileNetV2's 0.8220 on identical data. 533 original photographs
   cannot teach useful convolutional filters from nothing. This is the
   empirical answer to "why not build your own architecture?"
2. **EfficientNetB0's advantage is one image.** 0.8507 vs 0.8358 accuracy on 67
   validation images is a difference of exactly one image — within noise — for
   1.8x the download size. MobileNetV2 is the right choice for a phone.
3. **Ignore the latency column in `model_comparison.json`.** It was measured on
   a Colab GPU, where MobileNetV2's depthwise separable convolutions are *less*
   efficient than on the mobile CPUs and NPUs they were designed for. Argue
   model size, and state that latency was not measured on the target device.

### Model 2 — severity classifier

| Metric | Test |
|---|---:|
| Exact-grade accuracy | 0.4651 (20/43) |
| **Within-one-grade accuracy** | **0.9070** |
| Macro F1 | 0.4500 |
| Random baseline | 0.3333 |

| Grade | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| mild | 0.5556 | 0.5882 | 0.5714 | 17 |
| moderate | 0.2308 | 0.2500 | **0.2400** | 12 |
| severe | 0.5833 | 0.5000 | 0.5385 | 14 |

```
              mild  moderate  severe   total
mild            10       5        2       17
moderate         6       3        3       12
severe           2       5        7       14
```

**Why within-one-grade is the honest headline.** mild / moderate / severe are
cut-points on a *continuous* quantity — percentage of leaf area affected. A leaf
at 9% and one at 11% look almost identical but carry different labels. Of 23
errors, **19 are one grade off and only 4 are two grades off**. The model
perceives severity; it cannot resolve an arbitrary boundary.

**Why `moderate` is the worst grade.** It is the middle of an ordered scale,
bounded on both sides, so it has two neighbours to be confused with. Mild and
severe each have only one. The middle class of a three-point ordinal scale is
structurally the hardest, and the confusion matrix shows exactly that — of 12
moderate leaves, 6 went to mild and 3 to severe.

**The safety-relevant number:** a severe leaf graded mild causes a grower to
under-treat a badly infected plant. That occurred in **2 of 14 cases**.

### Known limitation — splits are stratified by disease, not severity

`split_dataset.py` stratified by class folder, which is disease. Severity did
not exist at split time, so its distribution across the splits was left to
chance and came out badly skewed:

| Split | mild | moderate | severe |
|---|---:|---:|---:|
| train | 22% | 33% | **45%** |
| validation | **42%** | 37% | 21% |
| test | 40% | 28% | 33% |

Training is severe-heavy while validation is mild-heavy. This caps achievable
accuracy and is a real limitation rather than a bug. **The fix, and the highest
value next step for this model, is to re-split stratified on the (disease,
severity) pair now that severity labels exist.**

Two further limitations to state:

- The severity model trains on 427 originals, not 667 — healthy images are
  excluded because a healthy plant has no grade.
- The severity test set is 43 images, 12 of them moderate. One image moves
  moderate's recall by 8 percentage points, so per-class figures carry wide
  error bars. Report them with that caveat.

### Summary

| | Disease | Severity |
|---|---:|---:|
| Macro F1 | **0.778** | 0.450 |
| Accuracy | **0.806** | 0.465 |
| Within-one-grade | n/a | **0.907** |
| Test images | 67 | 43 |

Model 1 is solid. Model 2 is weak but fully characterised, with the cause
identified and a specific fix. A weak result that is understood and explained is
a stronger position at a viva than a strong result that is not.

## 5. Scripts

### `tools/augment_dataset.py`

Standalone data-preparation tool with two subcommands. Tested and working.

**`rename` mode** — reads raw photos and for each one: applies EXIF rotation so the
image is genuinely upright in its pixels, converts to RGB, resizes so the longest
side is at most 1024px, saves as `<Prefix>_0001.jpg`. Writes `rename_map.csv`
tracing each new filename back to the original.

**`augment` mode** — for each original produces **54 files**:

- 1 original
- 5 rotations: 45°, 90°, 180°, 225°, 270°
- 8 colour adjustments applied to each of those 6 base images:

| Code | Adjustment | Value |
|---|---|---|
| `bh50` / `bl40` | brightness | +50 / −40 |
| `eh50` / `el40` | exposure | +50 / −40 |
| `ch50` / `cl40` | contrast | +50 / −40 |
| `sh50` / `sl40` | saturation | +50 / −40 |

Naming: `Black_LS_0001_rot45_bh50.jpg`

Two implementation details that matter:

- **45° and 225° rotations leave black triangles in the corners.** The script crops
  the largest clean rectangle from the centre instead. Black corners are a trivially
  learnable shortcut feature — a CNN would learn "black triangles mean rotated
  training image" faster than it learns lesion texture. Use `--corner-mode fill` to
  keep them if ever needed.
- **Exposure is implemented differently from brightness on purpose.** PIL's
  `ImageEnhance.Brightness` scales sRGB values directly. Exposure applies a gain in
  *linear light* measured in stops (`2^(value/100)`), like a camera exposure change.
  Without this distinction `bh50` and `eh50` would be near-duplicates.

Also writes `manifest_<disease>.csv` per class with columns:
`image_id, image_path, disease, plant_part, severity, source_image, rotation,
adjustment, is_original`.

The `severity` column is **inherited from the original** via `--labels`. This is
valid only because no transform changes the proportion of diseased tissue.
**Do not add cropping or zoom to this script** — a crop changes the affected
percentage and silently corrupts every inherited severity label.

The `source_image` column is used to prove no data leakage between splits.

### `src/split_dataset.py`

Splits `data/processed/<class>/` into `data/split/{train,validation,test}/<class>/`.

- **Stratified**: each class split independently at the same ratio, so all three
  classes appear in all three splits
- **Seeded** (42) so the split is reproducible across runs
- Deletes any previous split before writing, so stale files can't linger
- Writes `split_manifest.csv` and asserts no image appears in two splits

This **replaces** the earlier version that walked `<disease>/leaf/` and
`<disease>/stem/` subfolders.

### `src/preprocess.py`

The single definition of training-time and inference-time image preparation.
Resizes to 224x224 and returns **raw 0-255 RGB — it does not scale or divide by
255**, because `mobilenet_v2.preprocess_input` is a layer inside the model.

Also holds `load_class_names()` and `predict()`, which applies the
confidence-threshold rule and returns
`{label, confidence, probabilities, is_confident}`.

The module docstring records **why there is no background removal or lesion
cropping**, which is a question worth pre-empting in the viva:

1. Severity is graded as percentage of leaf area affected. Cropping toward a
   lesion raises that percentage and cropping away lowers it, and augmented
   copies inherit their source's grade — so one crop silently mislabels 54
   files. This is the same reason `augment_dataset.py` has no crop or zoom.
2. A grower's photo has pots, netting and sky in it. A model trained only on
   clean cut-outs degrades exactly where it matters, and removing backgrounds at
   inference too would mean shipping a second segmentation model.

Segmentation-based background removal belongs in the report as **future work**.

### `src/train.py`

Two-stage MobileNetV2 transfer learning.

**Stage 1** freezes the base and trains only the new head at lr 1e-3. The head
starts as random noise, and large gradients from a random head destroy carefully
pretrained convolutional filters. **Stage 2** unfreezes the top 30 layers at
lr 1e-5 so late layers learn orchid-specific lesion texture while early layers
keep the generic edge and colour detectors that 533 photographs could never
teach from scratch. BatchNorm layers stay frozen throughout — updating their
statistics on batches of 32 from 533 photographs destabilises training.

Writes `disease_model.keras`, `disease_model.weights.h5` (fallback if a
Colab-saved `.keras` will not load locally), `class_names.json`,
`training_metadata.json` and `training_history.json`.

`python train.py --smoke-test` runs one epoch on a few batches. **Always run it
before a long Colab run** — it proves the code works end to end so a typo cannot
waste an hour of GPU time.

### `src/evaluate.py`

Per-class precision / recall / F1, macro and weighted F1, a printed and saved
confusion matrix, a confidence-threshold sweep, and every misclassified test
image listed by name and confidence. Writes `metrics_test.json`,
`evaluation_report_test.txt` and `confusion_matrix_test.png`.

Run `python evaluate.py --split validation` to choose the operating threshold.
Choosing it from the test table would be tuning on the test set.

### `src/train_severity.py`

Trains Model 2. Separate from `train.py` because the label does not come from a
folder name: `split_augmented/train/black_leaf_spot/` holds mild, moderate and
severe images mixed together. So this script builds the (path, grade) pairs
itself by reading `severity_labels.csv` for the originals and the augmentation
manifests to map every augmented file back to its source.

That join is what makes 427 hand-graded labels cover ~18,400 training files, and
it is valid only because no augmentation transform changes the proportion of
diseased tissue. Adding crop or zoom to `augment_dataset.py` would silently
break it.

Healthy images are excluded entirely — a healthy plant has no grade, and Model 1
already answers that question.

`--check` reports label coverage and grade balance without training, and warns
when a grade has too few examples or no validation images at all.

### `src/evaluate_severity.py`

Test-set evaluation for Model 2, with two measurements `evaluate.py` does not
make because severity is an **ordered** scale:

- **Within-one-grade accuracy.** Calling a severe leaf moderate is a small
  error; calling it mild is serious. A plain confusion matrix hides that
  distinction. On the test set this is 0.9070 against an exact-match 0.4651 —
  the difference is the whole story of this model.
- **Grade distribution per split**, which exposes the disease-stratified split
  problem documented in section 4c rather than leaving the low score mysterious.

It also counts the specific dangerous error — severe graded mild — separately.

### `src/compare_models.py`

Trains MobileNetV2, EfficientNetB0, ResNet50V2, DenseNet121 and a from-scratch
CNN under identical conditions, then reports macro-F1, accuracy, parameter
count, size on disk and single-image CPU latency.

Exists to answer **"why did you choose this model?"** with measurements rather
than reputation. Everything is held constant except the backbone; each
architecture gets its own official `preprocess_input`, since they were
pretrained with different input scaling and using the wrong one would handicap a
model artificially.

Scored on **validation**, never test — choosing an architecture by test score is
tuning on the test set and would make the final reported number optimistic.

The `scratch_cnn` entry is a control, not a contender: it shows how much of the
performance comes from ImageNet pretraining rather than architecture. Expect it
to do clearly worse, and say so — 533 original photographs cannot teach useful
convolutional filters from nothing.

```bash
python compare_models.py --quick     # proves it runs; NOT reportable
python compare_models.py             # full comparison -- run on Colab
```

### `src/treatment_kb.json` and `src/treatment.py`

Rule-based treatment recommendation keyed by `(disease, severity)`. Entries for
`black_leaf_spot`, `phyllosticta_leaf_spot`, `healthy` and `unidentified`, each
with immediate actions, cultural control, chemical options, monitoring and an
escalate-to-expert flag.

**Chemical doses are deliberately unfilled.** Every dose is marked `"VERIFY"`
with `"verified": false` rather than populated with a plausible-looking number,
because prescribing an unsourced agrochemical rate is unsafe and indefensible.
`treatment.py` enforces this: an unverified option is returned with
`show_dose = False` and a referral message in place of the number, so no
unverified rate can reach a grower even if the front end forgets to check.

To finish it: source each rate from (1) the product label sold in Sri Lanka,
(2) the Department of Agriculture / Registrar of Pesticides registered list, and
(3) the cited reference book. Then set `"verified": true` and fill
`"source_ref"`.

`python treatment.py --check` validates the KB. It also cross-checks
`models/class_names.json`, so a classifier that can predict a class the KB
cannot advise on is reported as a hard problem rather than discovered in a demo.

The out-of-scope section retains the **Phytophthora is an oomycete, not a true
fungus** distinction. Standard fungicides do not work on it; it needs
Metalaxyl-class products. That entry is the single most important thing in the
file even though the classifier cannot predict the class.

### `tools/check_exif.py`

Read-only survey of `data/raw/`, run before anything else. Reports how many
photographs carry an EXIF orientation tag other than 1 — meaning the stored
pixels are not upright even though photo viewers display them correctly. A CNN
reads stored pixels and ignores the tag, so those images would train the model
on sideways leaves. Also reports pixel sizes, colour modes, byte-identical
duplicates and unreadable files. **Result on this dataset: 330 of 667 images
(49%) were stored sideways.** Worth stating in the report as a justification
for the processing stage.

### `tools/make_labels_template.py`

Generates `data/severity_labels.csv` with one row per original image, severity
blank for diseased classes and `none` for healthy, ready for hand-labelling.
Columns: `image_id, filename, class, split, plant_part, severity,
affected_area_percent, notes`. The `split` column lets you label the 341 train
rows first, since those are the ones that actually train the severity model.

**Re-running is safe.** Labels already typed are carried over and the previous
file is backed up with a timestamp, so a rerun can never cost hours of typing.

Two reporting flags:

```bash
python make_labels_template.py --progress   # counts, progress bar, grade mix
python make_labels_template.py --todo       # list rows still needing a grade
```

### `tools/update_manifest_severity.py`

Backfills the `severity` column in the augmentation manifests from
`severity_labels.csv` **without regenerating any images**.

This exists so that hand-labelling and augmentation do not have to wait for each
other. Augmentation was run with severity blank; the disease classifier does not
use severity at all, only the class folders. Once labelling is finished, run this
and every manifest row inherits its source image's grade.

```bash
python update_manifest_severity.py --check   # report only
python update_manifest_severity.py           # write (keeps .csv.bak)
```

### `tools/check_leakage.py`

Proves no original photograph contributed to both training and evaluation.
Runs three independent checks — manifest `source_image` values against the
holdout, training filenames on disk against the holdout (this catches stale
files an interrupted run left behind, which no manifest would list), and
`split_manifest.csv` internal consistency. Exits non-zero on failure, so it can
gate a retrain. Writes `data/leakage_report.txt` for the report.

---

## 6. Data pipeline — the order matters

```
raw/  →  processed/  →  split/  →  split_augmented/
       (rename)      (split)    (augment TRAIN ONLY)
```

**Split before augmenting. This is not optional.**

If augmentation runs before splitting, 54 variants of the same leaf scatter across
train and test. The model then trains on `Black_LS_0001_rot90` and is tested on
`Black_LS_0001_rot180` — the same leaf, same lesions, same lighting, just rotated.
It only has to recognise an image it has memorised. Accuracy would come out near
99% and would predict nothing about real-world performance. This is **data
leakage** and it would invalidate the entire results chapter.

Validation and test sets stay as **original, unmodified photographs**, because they
exist to answer "how does this perform on a photo a grower actually takes?"

### Commands, in order

```bash
cd ml-models/disease_detection

# --- STEP 1: EXIF check (decides whether step 2 is needed) ---
cd tools && python check_exif.py

# --- STEP 2: process ---
python augment_dataset.py rename --input ../data/raw/black_leaf_spot \
    --output ../data/processed/black_leaf_spot --prefix Black_LS
python augment_dataset.py rename --input ../data/raw/phyllosticta_leaf_spot \
    --output ../data/processed/phyllosticta_leaf_spot --prefix Phyllosticta_LS
python augment_dataset.py rename --input ../data/raw/healthy \
    --output ../data/processed/healthy --prefix Healthy

# --- STEP 3: severity label template (fill 427 rows by hand, in parallel) ---
# Rerun this after STEP 4 to populate the 'split' column. Rerunning is safe:
# anything already typed is carried over and the old file is backed up.
python make_labels_template.py

# --- STEP 4: split ---
cd ../src && python split_dataset.py

# --- STEP 5: augment TRAIN ONLY ---
cd ../tools
python augment_dataset.py augment --input ../data/split/train/black_leaf_spot \
    --output ../data/split_augmented/train/black_leaf_spot \
    --disease black_leaf_spot --labels ../data/severity_labels.csv
python augment_dataset.py augment --input ../data/split/train/phyllosticta_leaf_spot \
    --output ../data/split_augmented/train/phyllosticta_leaf_spot \
    --disease phyllosticta_leaf_spot --labels ../data/severity_labels.csv
python augment_dataset.py augment --input ../data/split/train/healthy \
    --output ../data/split_augmented/train/healthy \
    --disease healthy --labels ../data/severity_labels.csv

# --- STEP 6: copy validation + test across UNCHANGED ---
cd ..
cp -r data/split/validation data/split_augmented/
cp -r data/split/test data/split_augmented/
```

### Expected counts

These are the **actual** counts produced on 29 Aug 2026 with seed 42, not
estimates. Reproduce them by rerunning the commands above.

| Class | Total | Train | Val | Test | Train after 54× |
|---|---:|---:|---:|---:|---:|
| black_leaf_spot | 152 | 122 | 15 | 15 | 6,588 |
| phyllosticta_leaf_spot | 275 | 219 | 28 | 28 | 11,826 |
| healthy | 240 | 192 | 24 | 24 | 10,368 |
| **Total** | **667** | **533** | **67** | **67** | **28,782** |

3.8 GB of generated images. `processed/` alone is 135 MB — that is the folder
to upload to Colab.

**Class imbalance to carry into training.** Phyllosticta has 1.8× the training
images of Black Leaf Spot. Without `class_weight` the model will quietly favour
Phyllosticta. See section 9 item 2.

### Leakage verification

Run after step 6. The output belongs in the results chapter as evidence.

```bash
cd tools
python check_leakage.py --report ../data/leakage_report.txt
```

Recorded result, 29 Aug 2026:

```
training files on disk: 28782
distinct originals behind them: 533
held-out images (validation + test): 134

CHECK 1  training source images also in holdout     overlap = 0   PASS
CHECK 2  training filenames from held-out original   leaked = 0   PASS
CHECK 3  originals listed under two splits          clashes = 0   PASS

RESULT: PASS -- no leakage detected.
```

---

## 7. System design decisions

### Unknown-disease handling

Confidence threshold on max softmax probability, tuned on the validation set.
Below threshold → "Unidentified condition — not healthy, expert review recommended."
No trained "other" class.

### Severity assessment

**Three grades, defined by percentage of leaf area affected:**

| Grade | Leaf area affected |
|---|---|
| `mild` | under 10% |
| `moderate` | 10% – 40% |
| `severe` | over 40% |

Grading is by measured area, not impression, so labels stay consistent across 427
images. This grading protocol must be stated in the report.

**Approach: a separate 3-class classifier trained on diseased images only**
(healthy excluded — severity there is always `none`). Same MobileNetV2 transfer
learning recipe, separate `.keras` file. A two-head multi-output model would be
more elegant but is harder to debug under time pressure; two independent models is
the deliberate trade-off.

Labels come from `severity_labels.csv`, applied to the 427 diseased originals and
inherited by their augmented variants through the augmentation manifests.

### Plant part

Both trained diseases are leaf diseases, so plant part is currently always `leaf`.
A separate leaf/stem classifier is deferred — there is not enough stem data
(65 images in the earlier dataset).

### Admin role and model improvement

**Growers** upload photos and receive predictions. They never label anything.

**Admin** (orchid research institute staff) can upload an image of a disease not yet
in the system and manually enter disease name, plant part, and severity. That image
goes into a pending queue.

Rules for the retraining pipeline:

1. **Never retrain from a single image.** Queue new images into
   `data/pending/<disease>/` and only retrain a new class once it has **at least
   25–30 real originals**. 54 augmented copies of one leaf teach the model that
   specific leaf, and an undertrained class will start stealing predictions from
   working classes. Show the admin a counter: `Fusarium: 8/30 images collected`.
2. **Split before augmenting**, same rule as the manual pipeline.
3. **Gated promotion.** After retraining, evaluate on the held-out test set. Replace
   the live model only if macro-F1 is not worse. Save as `model_v2.keras` with a
   `metrics.json`. Keep previous versions.
4. **A new disease also needs a treatment record**, or the system will confidently
   name a disease it cannot advise on. Add treatment fields to the admin form.

This design is described in the report as *human-in-the-loop continual learning with
gated model promotion*.

### Treatment recommendation

Rule-based JSON knowledge base keyed by `(disease, severity)`. Not a model.
Sources must be cited (reference book plus Department of Agriculture guidance).

Note: reference-book treatments may be outdated. Modern options for Phyllosticta
include Boscalid + Pyraclostrobin and Thiophanate-methyl. Phytophthora is an
**oomycete**, not a true fungus, so it needs Metalaxyl-class products (Aliette,
Subdue, Truban, Terrazole) rather than standard fungicides; cinnamon paste is a
natural option. Keep that distinction in the knowledge base even though
Phytophthora is out of scope for the classifier.

### IoT integration

Rule-based disease risk scoring from sensor readings (temperature, humidity, leaf
wetness), not a model. Example: Phytophthora risk is high when temperature is
20–28°C and relative humidity exceeds 85% for more than 6 hours.

---

## 8. Training setup

- **Architecture:** MobileNetV2 transfer learning, ImageNet weights, frozen base,
  then a fine-tuning stage unfreezing the top ~30 layers at learning rate 1e-5
- **Input size:** 224 × 224
- **Training platform:** Google Colab (free T4). Local CPU training would take
  several hours per run.

### Colab notes

- Upload **one zip**, not thousands of loose files, and unzip to `/content/`,
  **not** to the mounted Drive folder. Per-file latency on the Drive mount will
  starve the GPU and turn a 90-second epoch into 15 minutes.
- Better still, upload only the **667 processed originals** (135 MB, measured)
  and run `split_dataset.py` then `augment_dataset.py` on Colab. The augmented
  set is 3.8 GB and uploading it costs far more time than the training does.
  Both scripts are seed-42 deterministic, so the Colab split is identical to
  the local one — the recorded counts and the leakage evidence still hold.
- Checkpoint to Drive, not `/content`, so a dropped session costs one epoch rather
  than the whole run. Use `ModelCheckpoint(save_best_only=True)` and
  `EarlyStopping(patience=5, restore_best_weights=True)`.
- Check `tf.__version__` on Colab against the local version (2.21.0). A `.keras`
  file saved on a newer version may not load locally. Pin it or also call
  `model.save_weights()` as a fallback.
- Expected: ~60–90 s/epoch on a T4 at batch size 32.

---

## 9. Known issues — ALL FIXED 29 Aug 2026

These were real bugs in the earlier 5-class code. `src/` has been rewritten and
every one is now addressed. Kept here because each is worth explaining in the
report, and because a reviewer may ask how they were caught.

1. ~~**Normalisation conflict.**~~ **FIXED.** `preprocess_input` is now a LAYER
   INSIDE the model (`train.py`, `build_model`). The saved `.keras` file accepts
   raw 0-255 RGB and does its own scaling, so there is exactly one place scaling
   happens and the backend cannot double-scale. `preprocess.py` no longer divides
   by 255 and says so in a comment. If `/ 255.0` ever reappears there, it is a bug.

2. ~~**No class weights.**~~ **FIXED.** `compute_class_weights()` uses the
   balanced formula `n_samples / (n_classes * count)` and the result is passed to
   both `fit()` calls. Black Leaf Spot has 122 training originals against
   Phyllosticta's 219 — 1.8x — so without this the model can score acceptably on
   overall accuracy while under-predicting the class a grower most needs caught.

3. ~~**Class names never saved.**~~ **FIXED.** `train.py` writes
   `models/class_names.json` immediately after building the datasets, before any
   training happens. `preprocess.load_class_names()` reads it and `evaluate.py`
   refuses to run without it. Never hardcode the list: index 0 is the
   alphabetically first folder, so adding `anthracnose` later would shift every
   existing index by one and silently remap every prediction.

4. ~~**`NUM_CLASSES` hardcoded to 5.**~~ **FIXED.** Derived from
   `len(class_names)`, which comes from the folders on disk.

5. ~~**No `evaluate.py`.**~~ **WRITTEN.** `src/evaluate.py` produces per-class
   precision / recall / F1, macro and weighted F1, a printed and plotted confusion
   matrix, the confidence-threshold sweep, and a list of every misclassified test
   image. Macro-F1 is the headline number — it weights the 15-image class equally
   with the 28-image one, which overall accuracy does not.

6. ~~**No `EarlyStopping` / `ModelCheckpoint` callbacks.**~~ **FIXED.** Both,
   plus `ReduceLROnPlateau`, on both training stages.

7. ~~**`split_check.py` is outdated**~~ **SUPERSEDED.** Replaced by
   `tools/check_leakage.py`, which checks more (manifests, filenames on disk, and
   the split manifest independently) and exits non-zero on failure so it can gate
   a retrain.

---

## 10. Terminology note

The word "processing" appears at two different stages and they must not be confused
in the report:

- **`data/processed/`** — *file-level* cleanup done once: EXIF orientation, format
  normalisation, resizing to 1024px.
- **`preprocess.py`** — *training-time* preprocessing done on every batch of every
  epoch: resize to 224×224, `mobilenet_v2.preprocess_input` scaling.

---

## 11. Points to defend at the viva

**Why split before augmenting?** Augmenting first scatters variants of the same leaf
across train and test, so the model is tested on images it effectively memorised.
Reported accuracy would be near 99% and meaningless. Splitting first guarantees no
original contributes to both training and evaluation, proven by the `source_image`
overlap check.

**Doesn't augmentation give 28,782 images of training data?** No. It gives 533
images of *information*, presented 54 ways. Augmentation teaches invariance — that a
lesion is still a lesion when rotated or lit differently. It cannot create disease
variation absent from the originals. The honest limitation in the report is 667
originals — 533 of them in training — not 28,782 files.

**Why is the test set only 67 images?** Because it contains only real, unmodified
photographs. A larger test set of augmented copies would be bigger and less
meaningful. Per-class precision, recall, and F1 are reported rather than overall
accuracy.

**Why 45° and 225° rotations if they leave black corners?** They do not, in this
pipeline — the script crops the largest clean rectangle from the centre. Black
corners are a strong, trivially learnable feature that would inflate training
accuracy and collapse at test time.

**Where does preprocessing happen?** At two stages; see section 10.

**Did you build your own architecture, or just use someone else's?**
Fine-tuned MobileNetV2, and that was the correct engineering decision rather
than a shortcut. The classification head is mine; stage 2 unfreezes the top 30
layers so the network genuinely adapts to orchid lesion texture. More
importantly, I tested the alternative: a from-scratch CNN under identical
conditions reaches macro-F1 0.6025 against MobileNetV2's 0.8220. With 533
original training photographs there is not enough data to learn useful
convolutional filters from nothing, and the comparison in section 4c is the
evidence.

**Why MobileNetV2 when EfficientNetB0 scored higher?** It scored higher by one
image on a 67-image validation set — 0.8318 against 0.8220 — which is within
noise, while being 1.8x the download size. The deployment target is a grower's
phone in a shade house, possibly offline, so size is a real constraint. Note
also that the latency figures were measured on a Colab GPU and are not
representative of a phone; the argument rests on model size, not on that column.

**Why is the severity model so much weaker than the disease model?**
Three reasons, all measurable. It trains on 427 originals rather than 667,
because healthy plants have no grade. The grade boundaries are cut-points on a
continuous quantity, so a leaf at 9% and one at 11% affected area look almost
identical yet carry different labels — which is why 19 of 23 errors are one
grade off and within-one-grade accuracy is 0.9070. And my splits were stratified
by disease rather than severity, because severity was not labelled until after
the split, leaving training 45% severe against validation's 21%.

**Why is `moderate` the worst grade?** It is the middle of a three-point ordered
scale, bounded on both sides, so it can be confused with two neighbours. Mild
and severe each have only one. Of 12 moderate test leaves, 6 were graded mild
and 3 severe — pulled apart in both directions. The middle class of an ordinal
scale is structurally the hardest, not a sign of a bug.

**Which errors actually matter?** For disease, a diseased plant called healthy —
3 of 43 on test. For severity, a severe leaf graded mild, because the grower
then under-treats — 2 of 14. Both are reported rather than folded into an
overall accuracy figure.

---

## 12. Immediate next steps

Sections 1-11 describe a component whose data pipeline, two models, evaluation
and treatment knowledge base are complete. What is left, in value order:

1. **End-to-end inference script.** Every part exists but nothing joins them.
   One script should take a photograph and return disease, confidence, severity
   and treatment, applying the 0.70 threshold and skipping the severity model
   when the prediction is healthy. This is also the best live viva demo:
   a real photo in, a full recommendation out.
2. **Verify the chemical doses** in `treatment_kb.json` and set
   `"verified": true`. Until then `treatment.py` returns a referral message
   instead of a rate, which is safe but incomplete.
3. **Re-split stratified by (disease, severity)** and retrain Model 2. The
   45%-vs-21% severe imbalance in section 4c is the main thing holding it back.
4. Backend inference endpoint, admin upload / retrain flow, IoT risk rules.
5. Optional, if time allows: collect more Black Leaf Spot photographs. It is
   the weakest class and also the smallest, and the two facts are connected.

### Report consistency checklist

- Use **667** originals and **533 / 67 / 67**, not the 657 / 525 / 65 figures
  from earlier drafts.
- Quote **macro F1**, not overall accuracy, as the headline for both models.
- Quote only `evaluate.py` / `evaluate_severity.py` output. Never
  `peak_val_accuracy_any_epoch` from the training metadata.
- State the three classes consistently; earlier project documents list five.
- Describe the architecture as **fine-tuned MobileNetV2 transfer learning**,
  and cite the scratch-CNN control as the evidence that this was necessary.
