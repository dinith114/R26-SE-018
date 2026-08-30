# Hybrid Pollination & Compatibility Analysis – ML Model

**Component 4** | IT22065230 – Wickramasinghe D.P

## Overview

This module predicts hybrid pollination compatibility between Vanda orchid
parent plants from photographs.

---

## Review response: removing the user from the diagnosis

The 50% review raised:

> *"is it necessary to get user inputs, like disease, with the uploaded image
> to predict the pollination? need to think of how to get the prediction"*

The comment was correct, and measurement confirmed it was worse than it looked.

### What was actually happening

With the split done **by plant** rather than by image (see *Data leakage*
below), on 357 images from 28 plants:

| Model input | Random split (old) | Grouped by plant (honest) |
|---|---|---|
| Image + user traits | 1.000 | 0.654 |
| Image only | 0.885 | **0.314** |
| User traits only | 0.857 | **0.736** |
| Majority-class baseline | — | 0.639 |

A **depth-3 decision tree on the four user dropdowns alone reproduces 90% of
the labels**, and `disease_visible` on its own scores 0.877. The image
contributed nothing measurable — the system was returning the user's own
answer to them.

### The change

Every trait is now **measured from the image first**. User input became an
optional *correction* to a stated estimate rather than a required precondition.
`src/trait_resolution.py` implements the rule:

```
1. measured  - a provider read it from the image confidently enough to act
2. user      - the grower supplied or corrected the value
3. unknown   - neither; the app is told which traits to ask about
```

The system always states what it believes and how sure it is *before* the user
answers. Disagreements are recorded as retraining data.

---

## Measured finding: disease cannot be read from whole-plant photos

Disease was tackled first because it is the highest-weight input. The result is
a **negative result**, and it drives the design:

| Method | Plant-level result |
|---|---|
| Best single CV measurement | AUC 0.70 *(best-of-40 on 28 plants — selection bias)* |
| Multivariate, leave-one-plant-out | **AUC 0.51, accuracy 0.54** |
| Majority-class baseline | accuracy 0.64 |

Reproduce with `python src/probe_disease_features.py` and
`python src/validate_disease_provider.py`.

**Why it fails** — all four are properties of the input, not fixable by tuning:

1. **Resolution.** Lesions are millimetres; frames cover a whole plant from
   1–2 m, so a lesion spans 1–3 px.
2. **Label noise.** `disease_visible` conflates pathology with senescence.
   Plant `id13` is annotated diseased but shows *withered spent flowers*.
3. **Sample size.** 28 plants cannot validate any method.
4. **Confounded background.** Each plant was photographed in one location, so
   background correlates with plant identity.

**Consequence.** Disease assessment requires a **leaf close-up**, routed to
Component 1's model. The local heuristic is capped at low confidence and
declares itself screening-only, so on whole-plant frames it asks for a close-up
instead of asserting an answer. Suppressing that request would fake a
capability the measurements do not support.

---

## Disease provider interface

Component 1's model is not finished. Rather than block on it — or hard-code
"no disease", which would make the demo dishonest — `src/disease_provider.py`
defines the contract plus a working fallback.

| Provider | Use |
|---|---|
| `HeuristicDiseaseProvider` | Local OpenCV screening. Runs today. Low confidence by design. |
| `RemoteDiseaseProvider` | Calls Component 1's `/api/v1/disease/detect`. Falls back to the heuristic if the service is down. |
| `NullDiseaseProvider` | Reports nothing — for ablation experiments. |

Select with the `ORCHID_DISEASE_PROVIDER` environment variable
(`heuristic` | `remote` | `null`). Swapping in the teammate's model is a config
change; no fusion, API or app code moves.

**Contract to agree with Component 1** — expected response from `/detect`:

```json
{
  "disease_detected": true,
  "disease_name": "Fusarium wilt",
  "severity": 0.8,
  "confidence": 0.91
}
```

Deviations degrade to a low-confidence reading rather than crashing.

---

## Data leakage in the original evaluation

`preprocess.py` split randomly across 357 images drawn from only **28 plants**,
so photo #7 of a plant trained the model and photo #8 of the *same plant*
tested it. The reported 100% test accuracy measured memorisation of individual
plants, not skill.

All evaluation in this component must group by `sample_id`
(`StratifiedGroupKFold` / `LeaveOneGroupOut`). **This is not yet fixed in
`preprocess.py`** — see Status below.

---

## Modules

| File | Purpose |
|---|---|
| `segmentation.py` | Isolates the subject plant. Vegetation mask + focus-seeded GrabCut. |
| `disease_provider.py` | Disease signal contract and the three providers. |
| `trait_resolution.py` | Measure-first / ask-only-if-needed resolution layer. |
| `probe_disease_features.py` | Diagnostic: ranks candidate disease measurements by plant-level AUC. |
| `validate_disease_provider.py` | Leave-one-plant-out validation of the disease signal. |
| `cross_notation.py` | Parses orchid tag names; preserves pod-first direction. |
| `compatibility.py` | **Level 2** — directional Parent A × B evidence-tier engine. |
| `inventory_images.py` | Reports what a tagged-photo collection can support. |
| `feature_extraction.py` | Global colour/shape/texture features. **Unmasked — see Status.** |
| `preprocess.py`, `train.py`, `evaluate.py`, `predict.py` | Original pipeline. |

### Why segmentation was needed

Feature extraction previously averaged over the whole frame. In this dataset
the background is *other green plants*, teal shade netting, reddish laterite
gravel and concrete — so those averages largely described the background. This
is a major reason image-only accuracy was 0.314.

Known limit: on wide shots containing several plants, no algorithm can infer
which plant is the subject, because the photographer did not frame one. The fix
is a capture protocol (one plant, centred) or letting the user tap the plant in
the app — *pointing* is a legitimate user input, unlike *diagnosing*.

---

## Status

Done:
- [x] Plant segmentation with subject selection
- [x] Disease provider interface + heuristic fallback + remote client
- [x] Honest leave-one-plant-out validation of the disease signal
- [x] Trait resolution layer (measure first, ask only when uncertain)
- [x] API and mobile client accept image-only assessment
- [x] **Level 2: Parent A x Parent B compatibility** - registry knowledge base,
      cross-notation parser, directional evidence-tier engine
- [x] Tagged-image inventory tool (`inventory_images.py`)

- [x] **Leakage fixed** — `StratifiedGroupKFold` by plant; scaling inside folds
- [x] **leaf_condition and plant_strength models trained** (transfer learning)
- [x] Maturity / breeding-readiness assessment for young plants
- [x] Suitability-vs-trait consistency check

Outstanding:
- [ ] ~~Fix the leakage in `preprocess.py`~~ DONE. Old item: — switch to `StratifiedGroupKFold`
      on `sample_id` and re-report every metric
- [ ] Mask `feature_extraction.py` features to the segmented plant
- [ ] Image-derived `leaf_condition` (most learnable of the three remaining)
- [ ] Image-derived `plant_strength` from leaf count and structure
      (note `leaf_count` is `"many"` on 100% of rows — a dead column)
- [ ] Flower head: presence gate → **"Not in bloom — cannot pollinate now"** as
      a distinct state, plus condition from the 308 currently unused flower
      images
- [ ] Trait inheritance from tagged photographs (blocked on labelled image count)
- [ ] Expose Level 2 through the API and mobile app

---

## Level 2 — Parent A × Parent B compatibility

Implemented in `compatibility.py`, exposed at `POST /api/v1/pollination/compatibility`
and in the app's **Cross** tab.

Grounded in a documented breeder interview (`docs/research/`) and 27 RHS-registered
crosses. Output is an **evidence tier** plus the precedents behind it:

| Tier | Meaning |
|---|---|
| `registered` | This exact pairing appears in the register |
| `genus_proven` | The genus combination is registered (a nothogenus exists) |
| `undemonstrated` | No registered precedent found |
| `blocked` | Level 1 assessed a parent as Not Suitable |

**No success percentage is produced, deliberately.** The register records only
crosses that succeeded, so it has no denominator. The source compilation claimed
intergeneric crosses were "moderate-high success"; the Peradeniya breeder said
"most intergeneric crosses don't work". Both are honest — the register sees only
survivors. Any percentage would be survivorship bias presented as measurement.

Direction is preserved throughout: the pod parent is named first, and the
engine reports separately when a pairing is registered only in reverse.

---

## Second measured finding: flower detection needs close-ups too

The same lesson as disease, from independent evidence.

Flower detection was built to gate pollination ("no flower → cannot pollinate
now") and to measure offspring traits. On whole-plant frames it is unreliable,
and the reason is measurable rather than a tuning failure:

```
backlit pink bloom        hue ~14   saturation ~33
sky seen between leaves   hue ~109  saturation ~44
```

The real flower is **less saturated than the background it must be separated
from**, so no saturation threshold splits them. Bright gaps of greenhouse roof
between leaves are compact and fully enclosed by foliage, so neither a border
test nor a compactness test rejects them. An early configuration reported
blooms on 81% of plants with 60% of them "white" — those were sky.

`flower_analysis.py` is therefore tuned for **precision over recall**: 32% of
plants yield a measurement, and washed-out blooms are missed on purpose. A
false "in bloom" is the more damaging error, because it lets the app recommend
a cross on a plant with no pollen to give.

Two further honesty notes:
- **Pattern classification is unusable.** It returned `spotted` for all 15
  measured plants, so it is not discriminating. The column is flagged in
  `measured_flower_traits.csv` and must not be used as a feature.
- Skin-colour exclusion cannot be used to remove the hand holding a name tag:
  pink petals share the YCrCb chroma region of skin, and doing so removed 80%
  of a real bloom. Only large skin regions reaching in from the frame edge are
  excluded.

---

## Fifth measured finding: bloom detection only works on close-ups

Found by a user test: a seedling photographed in its pot, carrying no flower at
all, was reported **"flower present, 90% confidence"**. The frame held a bright
blue plastic tool at the edge and brown coconut husk in the pot - both vivid,
both non-green, both mistaken for petals.

Tightening this forced a sweep of the coverage threshold, and the sweep answered
a bigger question than the bug. Measured on 150 bloom close-ups, 86 whole-plant
frames where the annotator recorded a bloom, and 150 whole-plant frames with
none:

| min coverage | close-up recall | whole-plant recall | false blooms |
|---|---|---|---|
| 0.004 (old) | 80% | 7% | **16%** |
| 0.010 | 77% | 7% | 9% |
| 0.020 | 71% | 3% | 3% |
| **0.040** | **62%** | 1% | **0%** |
| 0.080 | 43% | 0% | 0% |

**Whole-plant recall never exceeds 7% at any threshold.** Detecting a bloom in a
whole-plant photograph does not work - the flower is a small part of a busy,
colourful frame - so the lower thresholds were not buying recall, they were only
buying false alarms. 0.040 gives up that 7% and takes the 0%.

This is the same shape as the disease finding: the trait is real, but the
whole-plant frame is the wrong instrument for it. Both are answered by asking
for a close-up rather than by guessing.

What the grower now sees for a plant with no bloom:

> No flower detected in this image. Pollination needs an open flower, so a cross
> cannot be made from this photo. Growth stage looks like Near Mature. Possibly
> flowering within the next season or two. Photograph it again when flowers
> appear.

A false "in bloom" would let the app advise a cross that is physically
impossible. A false "no flower" only asks for another photograph. The thresholds
are set for that asymmetry throughout.


## Knowledge base

| File | Contents |
|---|---|
| `registered_crosses.csv` | 27 RHS-registered crosses with direction |
| `nothogenera.csv` | Intergeneric hybrid genus names in the Vanda Alliance |
| `parent_traits.csv` | Trait contributions of 8 documented species |
| `grex_parentage.csv` | Parentage looked up for tags that omit it |
| `measured_flower_traits.csv` | Flower colours measured from project photographs |

`grex_parentage.csv` carries a `verified` column: only 4 of 18 grex names were
confirmed by fetching the source page. **Spot-check any row you cite against
the RHS register before submission** — it is the naming authority.

Deliberately excluded: the "Failed" rows from the supplied compatibility matrix
(`Diseased + Any → Failed` etc.). Those are generic rules written to look like
observations. Training on them would mean re-learning what someone typed.

---

## Trained trait models

The two traits the app used to demand as dropdowns are now predicted from the
image. Both use masked features and grouped cross-validation by plant.

| Trait | Accuracy | F1 | Baseline | Features |
|---|---|---|---|---|
| `plant_strength` | **0.698** | **0.679** | 0.546 | frozen ResNet18 embeddings |
| `leaf_condition` | **0.557** | **0.546** | 0.501 | frozen ResNet18 embeddings |

Transfer learning mattered. Hand-crafted colour and contour statistics scored
0.482 on `plant_strength` — *below* its 0.546 baseline. Frozen ImageNet
features reached 0.698. Whatever a breeder means by "weak" is apparently not
captured by colour and contour statistics.

`leaf_condition` sits close to its baseline — 0.557 against 0.501. That margin
is thin, and the app says so rather than hiding it: every leaf reading is shown
with its confidence and the model's own accuracy beside it.

The network is **frozen**, not fine-tuned: with 28 distinct plants, training a
CNN end-to-end would memorise them, which is the failure that produced the
original 100%.

Honest limits, both flagged in `trait_predictor.py`:
- The `weak` class has only 3–4 training plants. A `weak` prediction has its
  confidence halved because that class is not reliably learned.
- Confidence is bounded by cross-validated accuracy, so a 0.9 softmax from a
  56%-accurate model reports ~0.50, not 0.9.

## All models were refitted in the deployment environment

Every figure in this file comes from models fitted with the exact versions the
server pins, **not** the versions on the development machine:

| | development | deployment |
|---|---|---|
| Python | 3.14 | 3.9 |
| numpy | 2.4.2 | **1.26.4** |
| scikit-learn | 1.8.0 | **1.5.0** |
| xgboost | 3.2.0 | **2.1.1** |

This was forced by a deployment failure, and the failure had two layers.

**`No module named 'xgboost'`** — the suitability model is an `XGBClassifier`
and loading a pickle needs the library that wrote it, but `xgboost` was never
added to `backend/requirements.txt`. Now pinned at 2.1.1, not 3.x, because 3.x
requires numpy>=2 and this project pins numpy 1.26.4 for its saved models.

**Underneath that, a worse one.** All six models were numpy>=2 pickles. numpy
2.0 renamed `numpy.core` to `numpy._core`, so those pickles raise
`ModuleNotFoundError` on numpy 1.26 — they could never have loaded on the
server, xgboost or no xgboost. Bumping the server's numpy was not an option:
the pin exists for other components' saved models.

Refitting in the pinned environment moved the numbers, and the shifts are
larger than "same data, same seed" suggests:

| Model | before | after |
|---|---|---|
| Suitability accuracy | 0.734 | **0.717** |
| `plant_strength` accuracy | 0.683 | **0.698** |
| `leaf_condition` accuracy | 0.633 | **0.557** |

`leaf_condition` also changed its winning configuration, from Random Forest on
combined features to Extra Trees on CNN features alone. These are the figures
that describe the models that actually run.

It also exposed a bug that only appears on the pinned version:

    ValueError: Invalid classes inferred from unique values of `y`.
                Expected: [0 1], got [1 2]

With two Moderate plants, a grouped CV fold's training split can contain none
of them. xgboost 3.x quietly remapped the labels; 2.1.1 refuses. `LabelSafeXGB`
in `train.py` encodes labels per fit so the same code runs on both. The
deployment fit is unwrapped back to a plain `XGBClassifier` before saving —
a pickle carrying a class defined in the training script would fail to load
anywhere `train.py` is not importable.

## Suitability model

| Metric | Score |
|---|---|
| Accuracy | 0.717 |
| Weighted F1 | 0.715 |
| Balanced accuracy | 0.578 |
| Majority baseline | 0.639 |

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Not Suitable | 0.80 | **0.98** | 0.88 | 85 |
| Suitable | 0.83 | 0.76 | 0.79 | 228 |
| Moderate | 0.00 | 0.00 | 0.00 | 44 |

`Moderate` scores **0.00** on precision, recall and F1 — there are only 2
Moderate plants, so the class cannot be learned. Report this rather than hiding
behind the weighted average.

Because the suitability and trait models are trained separately, they can
disagree. `_trait_conflict` in the service detects a `Suitable` verdict sitting
next to measured `weak` traits, surfaces the contradiction to the user and
halves the reported confidence.

---

## Input validation: refusing photographs that are not orchids

Found by testing the app on a phone: a photograph **of a laptop screen** was
assessed as **Suitable, 98.7% confidence**.

This is not a bug in the suitability model. That model has three classes —
Suitable, Moderate, Not Suitable — and forces every input onto one of them. It
was only ever shown orchids, so it has no way to answer "this is not a plant".
The missing answer is supplied by a separate gate in `orchid_gate.py`, which
every upload passes through before the model sees it.

**Fitted on positives only.** The obvious design is a two-class orchid /
not-orchid classifier, which needs a negative set. Any negative set assembled
quickly differs from this project's photographs in camera, resolution and
lighting, so the classifier learns *that* difference — a shortcut — and would
still pass a laptop photo taken on the same phone as the orchids. This is the
same failure already recorded below for the cutout flower model. The gate is
therefore fitted on the project's own 1190 photographs and nothing else;
downloaded images are used only to measure it.

**An ImageNet class list was measured and rejected.** ResNet18's own 1000-way
head classifies these Vanda plants as **"sea anemone", p=0.89** — the strap
leaves read as tentacles. Plant classes barely appear, so a hand-picked list of
"plant" labels would have refused the real orchids. The 512-d embedding beneath
the head is used instead.

**Distance-to-centre failed; nearest neighbours worked.** Measured on the same
grouped splits:

| Scoring rule | Real orchids refused | Non-orchids refused |
|---|---|---|
| Mahalanobis to centroid, raw | 62.9% | 100% |
| Mahalanobis to centroid, L2-normalised | 75.7% | 100% |
| k-NN, k=1, cosine | 98.7% | 100% |
| k-NN, k=5, cosine | 1.3% | 100% |
| **k-NN, k=10, cosine** | **1.1%** | **100%** |

A single centroid fails because the photographs are not one blob: whole plants,
bloom close-ups and name-tag shots are three visually distinct populations and
the mean of the three sits in the empty space between them. k=1 fails for the
opposite reason — near-duplicate frames of the same plant sit almost on top of
each other, so training distances collapse toward zero and take the threshold
with them.

**Measured result.** The false-refusal rate comes from grouped 5-fold CV over
1190 images in 375 groups; everything else from a held-out set of 543 Wikimedia
Commons images never used in fitting.

| What was uploaded | n | Correctly handled |
|---|---|---|
| The project's own orchid photos | 1190 | **98.9%** accepted |
| Laptops, screens, cars, rooms, people, food, documents | 265 | **100%** refused |
| Ferns, moss, grass | 51 | 90% refused |
| Houseplants, succulents | 48 | 71% refused |
| Roses, tulips, sunflowers | 45 | **27% refused** |
| Unseen orchid photos (Vanda and other genera) | 88 | 70% accepted |

Overall ROC AUC 0.921; non-orchids refused 88.6%.

Stage 1 alone refuses every non-plant photograph tested, at every threshold
setting, which is exactly the reported failure. On its own it could **not** tell
an orchid bloom from a rose bloom: 73% of the flower photographs were accepted.
The cause is visible in the reference set — 300 of the 1190 photographs are
bloom close-ups, and in ResNet's feature space a rose close-up sits very near an
orchid close-up. That is what stage 2 below was added for.

Tightening the threshold does not fix it, which was measured rather than
assumed:

| keep fraction | own photos refused | non-plants refused | other flowers refused | unseen orchids accepted |
|---|---|---|---|---|
| 0.90 | 12.2% | 100% | 64% | 27% |
| 0.95 | 6.5% | 100% | 51% | 48% |
| 0.97 | 3.6% | 100% | 47% | 62% |
| **0.99** | **1.1%** | **100%** | 27% | **70%** |

Buying flower discrimination costs far more in genuine photographs refused than
it gains, so 0.99 stands. Separating orchid from rose is a different question
from "is this in the reference distribution", so it gets its own model rather
than a tuned threshold.

### Stage 2 — orchid or some other flower? (`flower_filter.py`)

Trained on the project's 1190 orchid photographs against **Oxford Flowers-102**
(8089 photographs, 100 non-orchid species). The dataset's own two orchid classes
— hard-leaved pocket orchid and moon orchid — are excluded from the negatives
rather than deleted, because teaching the filter to call an orchid "not an
orchid" would break the stage it sits behind.

`orchid_gate.py` is deliberately fitted on positives only, to avoid learning
"which camera took the photo" instead of the subject. Training this stage on
negatives reopens that risk, so **the reported score comes from a third source**:
training positives are Sri Lankan nursery phone photos, training negatives are
Oxford's, and the headline number is measured on Wikimedia Commons orchids
versus Wikimedia Commons roses and tulips. Both halves of that test set come
from the same place, so a model that had only learned capture style would score
at chance on it.

| Third-source test (Wikimedia only) | Result |
|---|---|
| Wikimedia orchids called orchid (n=88) | 88% |
| Wikimedia roses/tulips called orchid (n=45) | 29% |
| **ROC AUC** | **0.851** |
| Flowers-102 orchid classes, never trained on (n=100) | 46% called orchid |

**Stage 2 is not a gate and must never be used as one.** Asked about a car or a
laptop it answers "orchid" 100% of the time — it only ever learned to separate
orchids from *other flowers*, so anything that is not a flower falls on the
orchid side of that boundary. It is only sound because stage 1 has already
removed those images.

### The combined pipeline

This is the only measurement that describes the deployed system. False refusals
come from 5-fold grouped CV with **both** stages refitted inside every fold;
everything else from the 543-image held-out Wikimedia set.

| Uploaded | n | Result |
|---|---|---|
| Laptops, screens, desks, rooms, cars, people, food, documents | 311 | **100% refused** |
| Roses, tulips, sunflowers | 45 | **80% refused** (stage 1 alone: 27%) |
| Unseen orchid photographs | 88 | **80% accepted** |

| The project's own photographs | Refused |
|---|---|
| Whole plants | **0.0%** |
| Tagged plants | **0.0%** |
| Bloom close-ups | 6.7% |
| **Overall** | **1.7%** |

Stage 1's threshold was retuned from 0.99 to 0.995 once stage 2 existed. At 0.99
stage 1 was the only gate and had to refuse roses by itself; it never managed
that (27%), and the tightness cost real orchid photographs - including a
seedling in a plastic pot, which is precisely the case the maturity feature
exists for. Handing the flower question to stage 2 buys 14 points of
unseen-orchid acceptance for 7 points of flower refusal, and costs nothing on
non-plants:

| keep_fraction | own refused | non-plants | foliage | flowers | orchids accepted |
|---|---|---|---|---|---|
| 0.970 | 4.5% | 100% | 95% | 96% | 58% |
| **0.980** | **3.3%** | **100%** | **94%** | **93%** | **61%** |
| 0.990 | 2.1% | 100% | 86% | 91% | 65% |
| 0.995 | 1.6% | 100% | 77% | 87% | 75% |

The threshold was tightened to 0.98 after a non-orchid houseplant - an anthurium
photographed on a white background - came back "Suitable, 97.9%". Extending
stage 2 with foliage negatives was tried first and was not enough on its own:
cross-validated foliage refusal reached only 35.4%, because 191 foliage images
cannot outweigh 8089 flowers and 1190 orchids inside the fit. The stage-1
threshold turned out to be the effective lever, taking foliage refusal from 77%
to 94%.

It is a real trade, and it goes the other way from the earlier retune: unseen
orchid photographs drop from 75% to 61% accepted, and the project's own photos
refused rises from 1.6% to 3.3%. A grower asked to retake a photograph is a
nuisance; a fern returning "Suitable for pollination" is the system being wrong
about the one thing it exists to judge.

The remaining false-refusal cost falls almost entirely on bloom close-ups, which
is expected - stage 2 is a flower discriminator, and a lone bloom is the only
input where it has a hard call to make. Whole-plant photos, the app's main path,
are unaffected at 0.0%.

**Label corrections.** Two images returned by a Commons search for "Vanda
orchid" were a plastic souvenir magnet and a 19th-century botanical lithograph.
Neither is a photograph of a living plant. Both are documented in
`data/images/gate_validation/README.md` rather than moved silently.

**Known residual failures.** Two real Vanda photographs are still refused: a
studio macro on a pure black backdrop, and an extreme macro of the column alone.
Both are unlike anything in the reference set, which is entirely daylight
nursery photographs. The gate recognises orchids photographed the way the
growers here photograph them.

About a third of unseen orchid photographs from the web are also refused. That
is the deliberate trade: the alternative operating points either let roses
through or start refusing the growers' own plants. For the app's actual job -
screening photographs taken in this nursery - whole-plant refusals measure 0.0%.

A refused image returns **HTTP 422** with an explanation, never a suitability
verdict — the honest response, since nothing was assessed.


## Fourth measured finding: the model extrapolates, and sounds certain doing it

Asked what happens if a grower uploads an orchid photograph found on the
internet, the full deployed path was run over the 88 held-out Wikimedia orchid
photographs. 30 were refused by the gate. Of the 58 that got through:

| Verdict | Count |
|---|---|
| Suitable | **58 (100%)** |
| Moderate | 0 |
| Not Suitable | 0 |

Confidence: minimum 0.96, **median 0.99**, maximum 1.00.

The obvious reading - that the model has collapsed onto the majority class - is
wrong, and was checked before being assumed. Under grouped cross-validation on
this nursery's own plants it predicts a genuine spread and is *good* at the
class that matters:

| Class | Precision | Recall | Predicted |
|---|---|---|---|
| Not Suitable | 0.80 | **0.98** | 92 |
| Suitable | 0.83 | 0.76 | 215 |
| Moderate | 0.00 | 0.00 | 50 |

It recalls 83 of 85 Not Suitable images. So the model is not broken - it is
**extrapolating** onto photographs from outside the collection it was fitted to,
and reporting 0.99 confidence while doing it. A system whose honest balanced
accuracy is 0.58 should not print 0.99 on a photograph it has no basis to judge.

**The fix reuses a measurement already being taken.** The gate computes a
novelty distance for every upload. The 90th percentile of the training distances
separates the two populations usefully:

| | above p90 (0.208) |
|---|---|
| The project's own photographs | 10.0% |
| Internet orchids that passed the gate | **61.3%** |

An accepted photograph above that line is now marked `familiarity: "unusual"`.
It still receives a verdict - refusing it would throw away a real orchid - but
the recommendation opens by saying the verdict is an extrapolation, and the
confidence is multiplied by 0.6. Measured effect end to end:

    own nursery plant      Suitable  99.7%   familiarity typical
    web Vanda, unusual     Suitable  59.1%   familiarity unusual, warning shown

This does not make the verdict correct on foreign photographs. Nothing can:
those images carry no ground-truth suitability label, so accuracy on them is
unmeasurable in principle. What it does is stop the app from asserting a
confident answer where it has no evidence, which is the difference between a
limitation and a misleading claim.


## Third measured finding: the cutout dataset does not transfer

An extra 800 background-removed Vanda images were obtained. They are genuine
and distinct - verified, not augmentations (max pairwise correlation 0.727,
zero pairs above 0.85, zero exact duplicates).

`label_flowers.py` auto-proposed flower / no-flower labels from them (212 / 588),
which spot-checking confirmed as accurate, and `train_flower_model.py` trained a
classifier on frozen ResNet18 embeddings:

| Evaluation | Result |
|---|---|
| 5-fold CV on cutouts | **accuracy 0.999, F1 0.999, AUC 1.000** |
| Real photos, flowering | 11/11 correct |
| Real photos, **non-flowering** | **0/38 correct** |

The model answers **"flower" for every real nursery photograph**, at 1.00
confidence - including one showing a hand holding a name tag and one showing
only sky gaps between leaves.

Two lessons, both worth stating explicitly:

1. **A positives-only transfer test hides this completely.** The first version
   of that test scored 16/16 and looked like proof of transfer. A model that
   always says "flower" gets perfect recall. Testing both directions is what
   exposed it.

2. **0.999 accuracy was measuring the wrong thing twice over.** The labels were
   auto-generated by a colour rule, so the network was partly re-learning that
   rule; and the cutout domain is far simpler than a greenhouse.

`fit_domain_guard` now stores the training distribution, and inputs outside it
are flagged rather than scored. It catches 22 of the 38 failures - useful, not
sufficient.

**Conclusion.** These images are usable for cutout-style input, and as a
demonstration that transfer learning works on this task in principle. They do
not replace labelled photographs taken in the real growing environment.

---

## Target metrics

Report **grouped by plant**, always alongside the majority-class baseline
(0.639). A grouped result of ~0.70 that is explained honestly is worth more
than a 100% that collapses under one question.
