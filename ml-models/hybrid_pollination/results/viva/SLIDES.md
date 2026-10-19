# Viva slides — IT22065230, Component 1

Paste-ready. Every figure referenced here is in this folder and was regenerated
on the 30 August grouped-CV results. The May PNGs in `results/` are pre-leakage
and must not be used.

---

## SLIDE A — Data collection and validation

### The image corpus — 13,077 images across six roles

357 is the hand-annotated suitability subset, not the dataset. The component
was built and validated on:

| role | images | source |
|---|---|---|
| Suitability + traits, hand-annotated | **357** | photographed at the nursery, 28 Mar 2026 |
| Input-check reference set | **1,190** | project photographs |
| Input-check held-out validation | **543** | 455 non-orchid, 88 orchid — never used in fitting |
| Non-orchid plant negatives | **396** | ferns, houseplants, other flowers |
| Orchid-vs-other-flower stage | **8,189** | Flowers-102, public dataset |
| Reference-expansion ablation | **1,599** | public *Vanda* image sets |
| Labelled flower cut-outs | **803** | bloom detection |
| **Total** | **13,077** | |

Only the first row carries suitability labels, and only that row limits the
suitability model. The others gave the input check its reference set, its
negatives and its held-out test, and gave the bloom detector its labels.

### The annotated subset

| | |
|---|---|
| Site | One commercial orchid nursery, Sri Lanka |
| Date | 28 March 2026 |
| Photographs | 357 |
| **Plants** | **28** — the true sample size for suitability |
| Genus | *Vanda*, all 28 |
| Annotated per plant | leaf condition · plant strength · visible disease · flower condition · overall suitability |
| Rater | one |

### How it was validated

**Grouped by plant.** `StratifiedGroupKFold` on `sample_id`, so every
photograph of one plant stays on one side of the split. Without this, images of
the same plant appear in both training and test and the model is scored on
plants it has memorised.

**An earlier split was discarded.** A random image-level split reported 100 %
accuracy. That was leakage, it is recorded as such in `training_results.json`,
and every figure presented here comes from the grouped evaluation instead.

**Scored against a baseline.** 63.9 % is obtained by answering "Suitable" to
every plant. A model is only reported as working where it clears that line.

**Held-out set for the input check.** 543 images — 455 non-orchid, 88 orchid —
never used in fitting.

### The 1,599-image ablation, and why it is reported as a null result

The gate's reference set was expanded with 1,599 external *Vanda* photographs
to see whether false refusals could be reduced. At the default threshold they
appeared to fall from 34.1 % to 23.9 %.

Matched at equal non-orchid rejection, the gain disappeared — 35.2 % before,
35.2 % after — and separation did not improve (ROC AUC 0.921 → 0.916). The
apparent improvement was the decision boundary expanding, not better
representation. The expanded set was **not adopted**, and the result is
reported as measured.

### Stated limitations

- 28 plants, one site, one genus, one day
- Single rater, so no inter-rater agreement figure
- `Moderate` has 2 plants and cannot be validated
- Suitability labels were driven largely by visible disease, which is not
  measurable at whole-plant distance (see Slide B)

---

## SLIDE B — Evaluation results

> **Figures:** `01_model_comparison.png` · `02_confusion_matrix.png`
> `03_trait_models.png` · `04_input_check.png`

### Four models, one protocol

| model | accuracy | balanced | beats baseline |
|---|---|---|---|
| **XGBoost** | **71.7 %** | 57.8 % | yes |
| Logistic Regression | 69.8 % | 56.3 % | yes |
| Random Forest | 52.9 % | 40.4 % | no |
| SVM (RBF) | 47.9 % | 40.5 % | no |
| *majority baseline* | *63.9 %* | | |

### Confusion matrix — XGBoost, out-of-fold

| annotated ↓ / predicted → | Moderate | Not Suitable | Suitable |
|---|---|---|---|
| **Moderate** (44) | 0 | 9 | 35 |
| **Not Suitable** (85) | 1 | **83** | 1 |
| **Suitable** (228) | 43 | 12 | **173** |

| class | recall | precision | F1 |
|---|---|---|---|
| Not Suitable | **97.6 %** | 79.8 % | 87.8 % |
| Suitable | 75.9 % | 82.8 % | 79.2 % |
| Moderate | 0 % | 0 % | 0 % |

### The two errors do not cost the same

| | count | consequence |
|---|---|---|
| **False Suitable** — said Suitable, was Not Suitable | **1** | a weak plant carries a capsule for nine months; a season is lost |
| **False Not Suitable** — said Not Suitable, was Suitable | **12** | the grower looks at a second plant |

The model errs 12:1 toward refusing. For this task that is the correct
direction, and every safeguard in the component — the input check, the
measured-weak hold, the one-way veto — is built on the same asymmetry.

### Read from the photograph

| | measured | baseline |
|---|---|---|
| Plant strength | **69.8 %** | 54.6 % |
| Leaf condition | 55.7 % | 50.1 % |

### Input check — 543 held-out images

| | n | result |
|---|---|---|
| Everyday objects (cars, screens, documents, people) | 311 | **100 % refused** |
| Other plants that are not orchids | 144 | 74.3 % refused |
| **All non-orchid** | **455** | **91.9 % refused** |
| Real orchids | 88 | 65.9 % accepted |

ROC AUC **0.921**. On the nursery's own photographs — the distribution the app
serves — false refusal is **2.2 %** under grouped cross-validation.

---

## Running it live

    cd ml-models/hybrid_pollination
    python src/viva_metrics.py

Prints every table above and rewrites all four figures in about two seconds.
It reads the saved result files only; no model is loaded and nothing is
retrained, so it cannot fail for want of a GPU or a missing `.pkl`.

`--no-save` prints the tables without touching the figures.

### If asked to prove the numbers are not hand-typed

Run it in front of them. The script reads `results/training_results.json` and
`results/trait_training_results.json`, both written by the training run on
30 August, and `results/orchid_gate_validation.csv`, which is the per-image
record of the held-out set.

### Likely questions

**"Why is balanced accuracy so much lower than accuracy?"**
Accuracy is carried by the two common classes. Balanced accuracy is the mean of
the three per-class recalls, so the Moderate class — 2 plants, never predicted
correctly — pulls it down. Both are reported for that reason.

**"Why only 2 folds?"**
28 plants, and the smallest class has 2 of them. More folds would leave folds
with no Moderate plant at all.

**"Is 71.7 % good?"**
It is 7.8 points above answering "Suitable" to everything. The figure that
matters more for this task is the Not Suitable recall of 97.6 % at a cost of 12
false refusals — the model rarely misses a plant that should not be used.
