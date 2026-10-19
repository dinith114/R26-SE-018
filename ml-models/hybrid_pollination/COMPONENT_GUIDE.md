# Component 1 — Hybrid Pollination and Compatibility Analysis

**IT22065230 · Wickramasinghe D.P**

A walkthrough of the whole component, assuming no prior knowledge. Every file
path is real and every number is from a saved result file.

---

## 1. What problem does this solve?

An orchid breeder wants to cross two plants: take pollen from one and put it on
the flower of another, so the second plant grows a seed pod.

Two things can go wrong before they start.

**The plant might not be fit.** A Vanda seed pod takes about **nine months** to
ripen. A weak or diseased plant asked to carry one for nine months usually
loses the pod, and the breeder loses a season.

**The two plants might not cross.** Orchids of different genera often cannot
produce seed together at all.

So the component answers two questions:

| | question | input |
|---|---|---|
| **Level 1** | Is *this* plant fit to breed from? | one photograph |
| **Level 2** | Do *these two* varieties cross? | two names |

---

## 2. Machine learning vs deep learning — the words

**Machine learning (ML)** — you describe the thing with numbers you chose
yourself, then a program learns which numbers matter. For a plant photo you
might measure "how green is it", "how big is the leaf outline", "how rough is
the texture". These are called **features**, and you write the code that
measures them.

**Deep learning (DL)** — a neural network looks at raw pixels and works out its
own features, over many layers. Nobody tells it to look at greenness. It needs
far more data to do this well.

**This component uses both, in different places:**

| where | type | why |
|---|---|---|
| Suitability model | **ML** (XGBoost) | 28 plants is far too few to train a neural network from scratch |
| Input check | **DL, borrowed** | a pre-trained ResNet18 describes the image; no new network is trained |
| Trait models | **DL, borrowed** | same ResNet18 description, then an ML classifier on top |

"Borrowed" is the important word. ResNet18 was trained by someone else on a
million photographs of everyday objects. This project **freezes** it — never
changes it — and only uses its description of each image. That is called
**transfer learning**, and it is how a 28-plant project can use a deep network
at all.

---

## 3. The four models compared, and why XGBoost won

All four were trained and tested identically, on the same data, with the same
split. Only the algorithm changed.

| model | what it is | accuracy | balanced |
|---|---|---|---|
| **XGBoost** | hundreds of small decision trees, each fixing the previous one's mistakes | **71.7 %** | 57.8 % |
| Logistic Regression | one straight-line boundary between classes | 69.8 % | 56.3 % |
| Random Forest | many decision trees voting, all trained independently | 52.9 % | 40.4 % |
| SVM (RBF) | finds the widest gap between classes, allowing curves | 47.9 % | 40.5 % |
| *majority baseline* | *answer "Suitable" every time, look at nothing* | *63.9 %* | |

**A decision tree** is a chain of yes/no questions: *is the green ratio above
0.4? → is the leaf outline bigger than 5000 pixels? → say Suitable.* One tree
is weak. XGBoost builds hundreds, where each new tree concentrates on the
examples the earlier ones got wrong, and they vote together.

**Why XGBoost was selected:** it scored highest, and it is the only one besides
Logistic Regression to beat the baseline at all. Random Forest and SVM score
*below* the baseline, meaning they are worse than answering "Suitable" to
everything.

**The baseline matters more than the winner.** 63.9 % is free — it is what you
get by never looking at the photograph. So XGBoost's real gain is **7.8
percentage points**, not 71.7.

- Code: `src/train.py`
- Results: `results/training_results.json`
- Models: `models/best_model.pkl` (the winner), plus `xgboost.pkl`,
  `random_forest.pkl`, `logistic_regression.pkl`, `svm_rbf.pkl`

---

## 4. Accuracy, precision, recall, F1 — worked on real numbers

Everything starts from a **confusion matrix**: rows are the truth, columns are
what the model said. This is the real `plant_strength` result over 357 images.

| truth ↓ / predicted → | moderate | strong | weak | total |
|---|---|---|---|---|
| **moderate** | **156** | 38 | 1 | 195 |
| **strong** | 47 | **91** | 0 | 138 |
| **weak** | 17 | 5 | **2** | 24 |

**Accuracy** — the diagonal over everything.
(156 + 91 + 2) ÷ 357 = **0.6975**

**Precision** — *when it says weak, how often is it right?* It said weak three
times (1 + 0 + 2) and was right twice. 2 ÷ 3 = **0.667**

**Recall** — *of the real weak plants, how many did it find?* There are 24, it
found 2. 2 ÷ 24 = **0.083**

**F1** — both combined into one number; it stays low if either is low.
2 × 0.667 × 0.083 ÷ (0.667 + 0.083) = **0.148**

**Balanced accuracy** — the average recall across all classes, so a rare class
counts as much as a common one.
(0.800 + 0.659 + 0.083) ÷ 3 = **0.5143**

**The lesson:** accuracy 0.70 and balanced accuracy 0.51 describe the *same
model*. Accuracy looks fine because the two common classes are handled well.
Balanced accuracy exposes that only 2 of 24 weak plants were caught.

---

## 5. How a photograph becomes a verdict

```
         photograph
              │
   ┌──────────▼──────────┐
   │ 1. INPUT CHECK      │  Is this an orchid at all?
   │    orchid_gate.py   │  refused → stops here (HTTP 422)
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │ 2. READ THE TRAITS  │  leaf condition · plant strength
   │ trait_resolution.py │  disease · flower
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │ 3. IMAGE FEATURES   │  62 numbers: colour, shape, texture
   │feature_extraction.py│
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │ 4. XGBoost          │  62 image + 4 traits = 66 features
   │   best_model.pkl    │  → Suitable / Moderate / Not Suitable
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │ 5. THE HOLD         │  measured weak or diseased
   │ _trait_conflict()   │  → held at Not Suitable
   └──────────┬──────────┘
          verdict
```

### Step 1 — the input check (`src/orchid_gate.py`)

The suitability model has three classes and no way to say "this is not a
plant". During testing a photograph of a **laptop screen** came back Suitable
at 98.7 %. So every upload is screened first.

**How it works.** ResNet18 turns each image into 512 numbers. The gate stores
those numbers for 1,190 known orchid photographs. A new image is turned into
its own 512 numbers, and the gate measures how far they sit from the nearest
known ones. Close → orchid. Far → refuse.

This is called **one-class novelty detection**: it learns what orchids look
like, never what non-orchids look like, so it can refuse things it has never
seen.

| held-out set, 543 images | result |
|---|---|
| Everyday objects (cars, screens, documents, people) — 311 | **100 % refused** |
| All non-orchid — 455 | **91.9 % refused** |
| Real orchids — 88 | 65.9 % accepted |
| ROC AUC | **0.921** |

**ROC AUC** means: pick one orchid and one non-orchid at random — 92 % of the
time the orchid scores as more orchid-like. 0.5 is a coin flip, 1.0 is perfect.

Model: `models/orchid_gate.pkl` · trained by `src/train_orchid_gate.py`

### Step 2 — reading the traits (`src/trait_resolution.py`)

Four traits, each measured from the image so the grower types nothing:

| trait | how | accuracy | baseline |
|---|---|---|---|
| plant strength | ResNet18 features → Extra Trees | **69.8 %** | 54.6 % |
| leaf condition | ResNet18 features → Extra Trees | 55.7 % | 50.1 % |
| disease | Component 2's model (needs TensorFlow) | 0.806 on leaf close-ups | |
| flower | colour and shape rules | 62 % on close-ups, **1 % on whole plants** | |

Models: `models/trait_plant_strength.pkl`, `models/trait_leaf_condition.pkl`
Trained by: `src/train_traits.py`

### Step 3 — image features (`src/feature_extraction.py`)

62 numbers describing the photograph:

| group | count | what |
|---|---|---|
| Colour | 12 | average and spread of red, green, blue, hue, saturation, brightness |
| Colour histograms | 24 | how pixels spread across colour bands |
| Shape | 6 | outline area, perimeter, roundness, solidity |
| Texture (Gabor) | 16 | response to edge patterns at 4 angles × 2 scales |
| Green / brown | 4 | ratio of healthy green to dead brown |

**There is no ResNet18 here.** The suitability model uses handcrafted features
only. ResNet18 appears in the gate and the trait models, not this step.

### Step 4 — the classifier

62 image features + 4 trait values = **66**. Scaled, then XGBoost.

`models/best_model.pkl` holds a two-step Pipeline: `StandardScaler` →
`XGBClassifier`. The scaler is inside the file so inference scales exactly as
training did.

### Step 5 — the hold (`backend/app/services/hybrid_pollination_service.py`)

If the photograph measured the plant **weak** or found **visible disease**, the
verdict is held at Not Suitable even when the classifier said Suitable.

**One way only.** A weak reading can stop a permissive verdict; a healthy
reading can never create one. The trait models are the weaker evidence, so they
may withhold a recommendation but not manufacture one.

**Why:** a wrong Suitable commits a weak plant to nine months carrying a
capsule. A wrong Not Suitable costs a second look at another plant. The errors
are not equal, so the system leans toward refusing.

---

## 6. The compatibility engine (Level 2)

Takes two **names**, not photographs. Nothing in this project identifies a
variety from a picture.

It reads the **genus** from each name — the `V.` in `V. coerulea` means Vanda —
and looks the pair up in a register of 27 RHS-recorded crosses.

| tier | meaning |
|---|---|
| `registered` | this exact cross exists (`V. coerulea × V. sanderiana = V. Rothschildiana`, 1931) |
| `genus_proven` | the genus combination is registered (Vanda × Aerides = *Aeridovanda*) |
| `undemonstrated` | no precedent found |
| `unknown_name` | a name was not recognised — cannot judge |
| `blocked` | a parent's condition rules it out |

**No success percentage is ever given.** The register records only crosses that
*worked* — nobody registers a cross that died. With no failures there is no
denominator, so no rate can be calculated from it. The app reports a *level of
evidence* instead.

Code: `src/compatibility.py` · `src/cross_notation.py`
Data: `data/knowledge/registered_crosses.csv`

---

## 7. The crossing logbook

This is the answer to what the register cannot do.

A grower records each attempt and the app tracks it through **8 stages** —
Pollinated → Pod set → Capsule developing → Capsule mature → Sown → Germinated
→ Seedlings → First bloom — with **5 ways to fail**, and reminders timed to the
plant (14 days, 45 days, 240 days).

Three rules make the numbers honest:

1. **Failures are recorded.** That is the whole point.
2. **"Lost track" is neither** success nor failure. It is *censored* data —
   counting an unfinished cross as a failure would make every figure wrong.
3. **No rate below 5 completed attempts.** Three records cannot support a
   percentage.

When you check a pair in the Cross tab, your own attempts appear **above** the
register, because for someone committing a plant for nine months, three of
their own results outrank a stranger's 1931 registration.

Code: `backend/app/services/cross_log_service.py`
Store: `backend/data/pollination_log/logbook.json`

---

## 8. Every file, and what it is for

### The models — `ml-models/hybrid_pollination/models/`

| file | size | what |
|---|---|---|
| `best_model.pkl` | 508 KB | **the suitability model** — StandardScaler → XGBClassifier |
| `preprocessors.pkl` | 4.7 KB | the scaler, trait encoders, label encoder, feature names |
| `orchid_gate.pkl` | 2.4 MB | the input check — 1,190 reference embeddings + threshold |
| `trait_plant_strength.pkl` | 1.8 MB | plant strength from the photo |
| `trait_leaf_condition.pkl` | 1.8 MB | leaf condition from the photo |
| `xgboost.pkl` · `random_forest.pkl` · `logistic_regression.pkl` · `svm_rbf.pkl` | | the four compared models, kept as evidence |
| `flower_presence.pkl` · `flower_filter.pkl` | | bloom detection |

### Training and analysis — `ml-models/hybrid_pollination/src/`

| file | lines | what |
|---|---|---|
| `train.py` | 417 | trains and compares the four suitability models |
| `preprocess.py` | 273 | builds the 66-feature matrix, encodes labels |
| `feature_extraction.py` | 292 | the 62 handcrafted image features |
| `cnn_features.py` | 153 | frozen ResNet18 → 512 numbers per image |
| `orchid_gate.py` | 444 | the input check |
| `train_orchid_gate.py` | 319 | fits it and validates on the held-out set |
| `trait_resolution.py` | 514 | decides each trait's value and where it came from |
| `trait_predictor.py` | 261 | runs the trait models |
| `train_traits.py` | 355 | trains them |
| `compatibility.py` | 829 | the register engine, tiers, alliance rules |
| `cross_notation.py` | 405 | parses orchid names, genus abbreviations, nothogenera |
| `disease_provider.py` | 579 | calls Component 2's disease model, falls back safely |
| `flower_analysis.py` | 474 | the bloom detector |
| `segmentation.py` | 336 | separates the plant from the background |
| `viva_metrics.py` | 288 | redraws the evaluation figures from saved results |
| `evaluate.py` | 242 | the evaluation run |
| `predict.py` | 202 | command-line prediction on one image |

### The server — `backend/`

| file | what |
|---|---|
| `app/api/routes/hybrid_pollination.py` | every endpoint — assess, compatibility, logbook, varieties |
| `app/services/hybrid_pollination_service.py` | loads the model, runs a prediction, applies the hold |
| `app/services/compatibility_service.py` | the Level 2 engine, plus the grower's own history |
| `app/services/cross_log_service.py` | the logbook: stages, outcomes, rates |
| `app/services/varieties_service.py` | the plant list |
| `app/models/schemas.py` | the shape of every request and response |
| `tests/test_suitability_veto.py` | 16 tests pinning the hold's behaviour |

### The app — `mobile/src/`

| file | what |
|---|---|
| `screens/HybridPollinationScreen.js` | the Assess tab and the tab bar |
| `components/CompatibilityTab.js` | the Cross tab — two steps, plants then varieties |
| `components/CrossLogTab.js` | the logbook |
| `services/api.js` | every call to the server |

### The data — `ml-models/hybrid_pollination/data/`

| file | what |
|---|---|
| `image_annotations_clean.csv` | **the labels** — 357 rows, 28 plants, your annotations |
| `images/plants/` | the 357 nursery photographs |
| `images/gate_validation/` | 543 held-out images for the input check |
| `knowledge/registered_crosses.csv` | the 27 RHS crosses |
| `gate_embeddings.npz` | the 1,190 reference embeddings |

### The results — `ml-models/hybrid_pollination/results/`

| file | what |
|---|---|
| `training_results.json` | the four models, 30 Aug, **the valid numbers** |
| `trait_training_results.json` | the trait models |
| `orchid_gate_validation.csv` | per-image record of the held-out set |
| `viva/` | **the figures to present** |
| `*.png` in the top folder | **11 May, pre-leakage — do not use** |

---

## 9. The three things to understand before the viva

**1. The sample size is 28, not 357.** 357 photographs of 28 plants. Every
evaluation groups by plant (`StratifiedGroupKFold`), so all photographs of one
plant stay on one side of the split. An earlier version split by image, scored
100 %, and that was **data leakage** — the model was tested on plants it had
memorised. It is recorded as such in `training_results.json`.

**2. The errors are not equal, and the model knows it.** Against the annotated
set: **1 false Suitable** against **12 false Not Suitable**. It errs 12:1
toward refusing. For this task that is the correct direction, and every
safeguard — the input check, the hold, the one-way rule — is built on it.

**3. Disease decides the labels, and a whole-plant photo cannot see it.**
Of 10 plants marked diseased, 9 were labelled Not Suitable; of 18 marked clean,
17 were Suitable. Disease accounts for 26 of 28 labels. But at whole-plant
distance a lesion spans 1–3 pixels: ROC AUC **0.522**, where 0.500 is a coin
flip, and a permutation test gives **p = 0.92**. It needs a leaf close-up,
where Component 2's model reaches **0.806**.

That third point is a *finding*, not a weakness. You measured your own
pipeline, found where it fails, proved why, and showed what closes it.

---

## 10. Running it yourself

```bash
# the evaluation figures and tables — reads saved results, trains nothing
cd ml-models/hybrid_pollination
python src/viva_metrics.py

# one prediction from the command line
python src/predict.py --image data/images/plants/20260328_101143_HDR.jpg

# retrain the suitability models (several minutes)
python src/train.py
```
