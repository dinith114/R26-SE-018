# How to run this component — including a live viva demo

Everything here is run from `ml-models/disease_detection/`.

---

## 0. One-time setup

```bash
cd ml-models/disease_detection
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

On Windows the interpreter is `.venv/Scripts/python.exe`. On Linux/macOS it is
`.venv/bin/python`. Every command below is written for Windows; swap that one
path if you are elsewhere.

**Activating the environment** (so you can just type `python`):

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Git Bash
source .venv/Scripts/activate
```

Your prompt gains a `(.venv)` prefix. If PowerShell refuses with an execution
policy error, either use Git Bash or run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

---

## 1. Viva demo — what to run in front of the panel

Pick from this table. **Rehearse once before the viva**, and have a terminal
already open at the right folder with the venv activated.

| # | Command | Runs for | What it proves |
|---|---|---|---|
| 1 | `python check_leakage.py` | ~2 s | Results are honest — **best single demo** |
| 2 | `python make_labels_template.py --progress` | instant | Labelling protocol and progress |
| 3 | `python split_dataset.py --dry-run` | ~1 s | The split is stratified and reproducible |
| 4 | `python check_exif.py` | ~40 s | Why the processing stage was necessary |
| 5 | `python evaluate.py` | ~30 s | Test metrics and confusion matrix |
| 6 | `python treatment.py --disease black_leaf_spot --severity moderate` | instant | The treatment knowledge base working |
| 7 | `python treatment.py --check` | instant | Every predictable class has advice |

**Do NOT run these live** — they take too long and rewrite your dataset:

- `augment_dataset.py augment …` — about 5 minutes, writes 28,782 files
- `split_dataset.py` without `--dry-run` — deletes and rebuilds `data/split/`
- `train.py` — hours on a CPU

If the panel asks to see augmentation, run the demo in section 3 instead: it
augments **one** image into 54 in a temporary folder and touches nothing.

### The demos, in full

```bash
# 1 -- THE ONE TO SHOW. Proves no training image leaked into the test set.
cd tools
../.venv/Scripts/python.exe check_leakage.py
```

Expected ending: `RESULT: PASS -- no leakage detected.`

Say while it runs: *"Augmentation turns one photograph into 54 files. If I had
augmented before splitting, rotated copies of the same leaf would sit in both
training and test, so the model would be tested on images it had memorised.
This script proves that did not happen — it checks the manifests, the
filenames on disk, and the split manifest independently."*

```bash
# 2 -- Severity labelling protocol and how far along it is.
cd tools
../.venv/Scripts/python.exe make_labels_template.py --progress
```

Say: *"Severity is graded by percentage of leaf area affected — under 10%
mild, 10 to 40% moderate, over 40% severe. Grading by measured area rather
than impression is what keeps 427 labels consistent."*

```bash
# 3 -- The split, reported without changing anything.
cd src
../.venv/Scripts/python.exe split_dataset.py --dry-run
```

Say: *"Stratified, so all three classes appear in all three splits in the same
proportion. Seeded with 42, so anyone re-running this gets exactly my split."*

```bash
# 4 -- Why the processing stage exists.
cd tools
../.venv/Scripts/python.exe check_exif.py
```

Say: *"Half my photographs — 330 of 667 — were stored sideways with a hidden
EXIF tag telling viewers to rotate them. Your eyes never see the problem
because photo apps obey that tag. A CNN reads the stored pixels and ignores
it, so it would have been learning from sideways leaves."*

```bash
# 5 -- Test-set metrics (only after training).
cd src
../.venv/Scripts/python.exe evaluate.py
```

Say: *"I report per-class precision, recall and F1 rather than overall accuracy.
The test set is 67 real photographs and only 15 of them are Black Leaf Spot, so
one error moves that class's recall by nearly 7 points while barely touching
overall accuracy."*

```bash
# 6 -- Treatment recommendation for one (disease, severity) pair.
cd src
../.venv/Scripts/python.exe treatment.py --disease black_leaf_spot --severity moderate
```

Say: *"Treatment is a rule-based lookup, not a model, and that is deliberate.
Advice has to be auditable and correctable by a human expert, there is no
dataset of treatment outcomes to train on, and when a product registration
changes someone edits one JSON entry instead of retraining."*

If the panel asks about the doses: *"They are deliberately unfilled. Each one is
marked unverified until I have sourced it from the product label and the
Department of Agriculture registered list. The code returns a referral message
instead of a number, so an unverified rate cannot reach a grower."*

```bash
# 7 -- Prove the classifier cannot name a disease it cannot advise on.
cd src
../.venv/Scripts/python.exe treatment.py --check
```

Say: *"This cross-checks the knowledge base against the model's own
`class_names.json`. If the classifier could ever predict a disease the knowledge
base has no entry for, this fails loudly — so the system can never confidently
name a disease it has nothing to say about."*

---

## 1b. Labelling severity — two ways

**Fast way (recommended).** Shows each photograph and takes one keystroke per
grade. Every keystroke saves immediately, so it is safe to stop any time and
re-run to continue.

```bash
cd tools
../.venv/Scripts/python.exe label_severity.py
```

    1 = mild (under 10%)   2 = moderate (10-40%)   3 = severe (over 40%)
    <- previous   -> skip   u undo   q quit

Rows come up **train first**, because those are the ones that train the model.
If you run out of time having done only the train rows, you still have a
trainable severity model.

**Excel way.** Open `data/severity_labels.csv`, type grades into the `severity`
column, and **save as CSV — not .xlsx**. Excel will warn about "features not
compatible with CSV"; choose *Keep current format*. Sort by the `split` column
and do `train` first. This works fine, but you have to open each photograph in
a separate window yourself, which is where the time goes.

Either way, check progress with:

```bash
../.venv/Scripts/python.exe make_labels_template.py --progress
```

---

## 2. If a command fails in the viva

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'PIL'` | venv not activated | Use the full `.venv/Scripts/python.exe` path |
| `ERROR: input folder not found` | wrong working directory | `cd` into `tools/` or `src/` as the command shows |
| `ERROR: no manifest_*.csv found` | pipeline not run | Say so honestly; show `data/leakage_report.txt` instead |
| PowerShell execution policy error | activation script blocked | Use Git Bash, or the full interpreter path |

Every script also has built-in help:

```bash
../.venv/Scripts/python.exe check_leakage.py --help
```

**Safety net:** the recorded outputs are already saved in the repository, so
even if a live run fails you can open the file and talk through it:

- `data/leakage_report.txt`
- `models/evaluation_report_test.txt` (after training)
- `models/confusion_matrix_test.png`

---

## 3. Safe augmentation demo (one image, nothing overwritten)

```bash
cd tools
mkdir -p demo_in demo_out
cp ../data/processed/phyllosticta_leaf_spot/Phyllosticta_LS_0001.jpg demo_in/
../.venv/Scripts/python.exe augment_dataset.py augment \
    --input demo_in --output demo_out \
    --disease phyllosticta_leaf_spot --max-side 512
ls demo_out            # 54 files + a manifest
```

Open `demo_out` in a file explorer with large thumbnails and you can point at
the six rotations and the eight colour variants. Delete `demo_in` and
`demo_out` afterwards.

---

## 4. Rebuilding the dataset from scratch

Only `data/raw/` is irreplaceable. Everything else regenerates from it, and
the seed of 42 makes the result identical every time.

```bash
cd tools
PY=../.venv/Scripts/python.exe

$PY check_exif.py

$PY augment_dataset.py rename --input ../data/raw/black_leaf_spot \
    --output ../data/processed/black_leaf_spot --prefix Black_LS
$PY augment_dataset.py rename --input ../data/raw/phyllosticta_leaf_spot \
    --output ../data/processed/phyllosticta_leaf_spot --prefix Phyllosticta_LS
$PY augment_dataset.py rename --input ../data/raw/healthy \
    --output ../data/processed/healthy --prefix Healthy

cd ../src && ../.venv/Scripts/python.exe split_dataset.py

cd ../tools
for c in black_leaf_spot phyllosticta_leaf_spot healthy; do
  $PY augment_dataset.py augment --input ../data/split/train/$c \
      --output ../data/split_augmented/train/$c \
      --disease $c --labels ../data/severity_labels.csv
done

cd ..
cp -r data/split/validation data/split_augmented/
cp -r data/split/test data/split_augmented/

cd tools && $PY check_leakage.py --report ../data/leakage_report.txt
```

> **Warning.** Rebuilding after you have started hand-labelling is safe only
> because filenames are stable: `raw/Black_LS_0007.jpg` always becomes
> `processed/Black_LS_0007.jpg`. If you ever add or remove a file in `raw/`,
> the numbering shifts and your severity labels would point at the wrong
> images. Add new images with the next unused number, never by renumbering.

---

## 5. Training (Google Colab)

Local CPU training takes hours per run. Use Colab's free T4.

1. Zip the **processed originals only** — 135 MB, not the 3.8 GB augmented set:

   ```bash
   cd data && tar -czf processed.tar.gz processed/
   ```

2. Upload to Colab and unzip to `/content/`, **not** to the mounted Drive
   folder. Per-file latency on the Drive mount starves the GPU and turns a
   90-second epoch into 15 minutes.

3. In Colab, run `split_dataset.py` then `augment_dataset.py` there. Both are
   seed-42 deterministic, so you get the same split as locally.

4. Train, checkpointing to Drive so a dropped session costs one epoch:

   ```bash
   python train.py --data /content/split_augmented \
                   --out /content/drive/MyDrive/orchid_models
   ```

5. Check `tf.__version__` on Colab against your local version. A `.keras` file
   saved by a newer TensorFlow may not load on an older one — `train.py` also
   writes `disease_model.weights.h5` as a fallback.

6. Download `disease_model.keras`, `class_names.json` and
   `training_metadata.json` into `models/`, then run `evaluate.py` locally.

### Comparing architectures

`compare_models.py` answers "why this model?" with measurements. It trains five
architectures under identical conditions and reports macro-F1 alongside size and
inference latency.

```bash
python compare_models.py --quick    # proves it runs; numbers NOT reportable
python compare_models.py            # the real comparison -- do this on Colab
```

It scores on **validation**, never test. Selecting an architecture by test score
is tuning on the test set and would make your final number optimistic.

Local CPU timing, measured on this machine: roughly **7 minutes per epoch** on
the full 28,782-image training set at batch size 32. A full five-architecture
comparison is therefore an overnight job locally and about an hour on a Colab
T4. Use Colab.

**Before a long run, always smoke-test first:**

```bash
python train.py --smoke-test
```

One epoch on a few batches. It proves the code runs end to end and writes a
model file, so a typo cannot waste an hour of GPU time. The metrics from a
smoke test are meaningless — that is expected.
