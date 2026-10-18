"""
run_experiments.py -- every training experiment the PP2 panel asked for, in one run.

The panel said the model's accuracy was not improved and was checked with one
metric only. This script answers both: each experiment changes ONE thing from
the reference recipe and is scored on the VALIDATION photographs, so every
choice in the recipe has a measured value. The TEST photographs are not
touched until a winner has been chosen, and then only once (--final-test).

Two properties matter for Colab
-------------------------------
RESUMABLE  Each experiment is written to --out (Google Drive) when it
           finishes. Rerunning skips every experiment already there, so a
           disconnect costs only the experiment that was running.
CACHED     Each training set is decoded and resized ONCE into a local cache
           file. Decoding 28,782 photographs of about 1024 pixels was what made
           an epoch take around two minutes; after the first epoch every later
           epoch, and every later experiment, reads the cache instead.

The experiments, in run order (most important first)
----------------------------------------------------
  DEP   the deployed disease model, scored on validation: where we start
  SDEP  the deployed severity model, scored on validation
  R     the deployed recipe, rerun with every epoch scored. One run answers:
          D1  after 2 epochs, the setting the panel saw
          D2  after 5 and 10 epochs, and where training stopped by itself
          D6  fine-tuning 0 layers vs 30 layers
          D7  keeping the best-F1 epoch instead of the lowest-loss one
  D9    test-time augmentation: average 8 flipped / rotated views of each photo
  SO    severity, original split: frozen (S1), then fine-tuned (S2)
  SB    severity, balanced split (split_severity.py): frozen (S3), fine-tuned (S4)
  D5    no class weights
  D4    no 54x augmentation: the 533 originals, repeated 54 times per epoch so
        every epoch still has the same number of training steps
  D6    fine-tune 60 layers instead of 30, continuing from R's frozen stage
  D8    EfficientNetB0 instead of MobileNetV2, fine-tuned the same way
  D3    stage-1 learning rate 0.0001 and 0.01 (R used 0.001), frozen stage only

Usage
-----
  python run_experiments.py --list
  python run_experiments.py --smoke-test       # proves every path runs; NOT results
  python run_experiments.py                    # everything not yet done
  python run_experiments.py --only R D9
  python run_experiments.py --redo D4          # throw one away and run it again
  python run_experiments.py --report           # table, charts and summary
  python run_experiments.py --final-test D7    # the ONE test-set evaluation
"""

import argparse
import csv
import gc
import hashlib
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = COMPONENT_ROOT / "data"
DEFAULT_OUT = COMPONENT_ROOT / "results" / "experiments"
DEFAULT_DEPLOYED = COMPONENT_ROOT / "models"

IMG_SIZE = (224, 224)
SEED = 42
SEVERITY_CLASSES = ["mild", "moderate", "severe"]
AUGMENT_FACTOR = 54
SHUFFLE_BUFFER = 2048
SMOKE_TRAIN_FILES = 48

# The recipe of the deployed models (training_metadata.json and
# severity_training_metadata.json). Every experiment starts from this and
# changes one entry.
DISEASE_RECIPE = {
    "backbone": "mobilenetv2", "augmented": True, "class_weights": True,
    "epochs": 25, "lr": 1e-3,
    "fine_tune": True, "fine_tune_epochs": 12, "fine_tune_lr": 1e-5,
    "fine_tune_layers": 30,
    "dropout": 0.3, "patience": 5, "batch_size": 32,
}
SEVERITY_RECIPE = dict(DISEASE_RECIPE, epochs=12, fine_tune_epochs=10)

# Row selectors: which epoch of a run a table row describes.
#   best_loss    lowest validation loss over both stages (the recipe's own rule)
#   stage1_best  lowest validation loss while the base was frozen
#   stage2_best  lowest validation loss while fine-tuning
#   best_f1      highest validation macro F1 over both stages
#   epoch:N      the model after N epochs of stage 1
EXPERIMENTS = [
    {"id": "DEP", "task": "disease", "kind": "existing", "model": "disease_model.keras",
     "question": "Where we start: the disease model the app uses today.",
     "rows": [("DEP", None, "Deployed disease model (29 Aug)", None)]},
    {"id": "SDEP", "task": "severity", "split": "original", "kind": "existing",
     "model": "severity_model.keras",
     "question": "Where we start: the severity model the app uses today.",
     "rows": [("SDEP", None, "Deployed severity model (29 Aug)", None)]},
    {"id": "R", "task": "disease", "kind": "train", "changes": {},
     "question": "The deployed recipe, rerun under the same conditions as every "
                 "other experiment, with the validation score of every epoch kept.",
     "rows": [("R", "best_loss", "Reference recipe, rerun", None),
              ("D1", "epoch:2", "After 2 epochs (the PP2 setting)", "R"),
              ("D2-5", "epoch:5", "After 5 epochs", "R"),
              ("D2-10", "epoch:10", "After 10 epochs", "R"),
              ("D6-0", "stage1_best", "Fine-tune 0 layers (frozen base)", "R"),
              ("D6-30", "stage2_best", "Fine-tune top 30 layers", "R"),
              ("D7", "best_f1", "Keep the best-F1 epoch, not the lowest-loss one", "R")]},
    {"id": "D9", "task": "disease", "kind": "tta", "needs": ["R", "DEP"],
     "question": "Does averaging 8 flipped and rotated views of each photograph "
                 "help, with no retraining?",
     "rows": [("D9-R", "R", "Reference + test-time augmentation", "R"),
              ("D9-DEP", "DEP", "Deployed + test-time augmentation", "DEP")]},
    {"id": "SO", "task": "severity", "split": "original", "kind": "train", "changes": {},
     "question": "Severity on the original split: does fine-tuning help a model "
                 "that was only ever trained frozen?",
     "rows": [("S1", "stage1_best", "Severity, frozen (rerun of deployed recipe)", "SDEP"),
              ("S2", "stage2_best", "Severity, fine-tuned top 30 layers", "S1")]},
    {"id": "SB", "task": "severity", "split": "balanced", "kind": "train", "changes": {},
     "question": "Severity on the balanced split, where all three parts have the "
                 "same grade mix.",
     "rows": [("S3", "stage1_best", "Severity, frozen, balanced split", None),
              ("S4", "stage2_best", "Severity, fine-tuned, balanced split", "S3")]},
    {"id": "D5", "task": "disease", "kind": "train", "changes": {"class_weights": False},
     "question": "Did class weights help the smallest class, Black Leaf Spot?",
     "rows": [("D5", "best_loss", "No class weights", "R")]},
    {"id": "D4", "task": "disease", "kind": "train", "changes": {"augmented": False},
     "question": "Did the 54 augmented copies of each photograph help?",
     "rows": [("D4", "best_loss", "No 54x augmentation", "R")]},
    {"id": "D6", "task": "disease", "kind": "train", "changes": {"fine_tune_layers": 60},
     "continue_from": "R",
     "question": "Does adapting more of the network to orchids help?",
     "rows": [("D6-60", "stage2_best", "Fine-tune top 60 layers", "R")]},
    {"id": "D8", "task": "disease", "kind": "train", "changes": {"backbone": "efficientnetb0"},
     "question": "Would EfficientNetB0 beat MobileNetV2 when both are fine-tuned? "
                 "(The August comparison had no fine-tuning.)",
     "rows": [("D8", "best_loss", "EfficientNetB0 backbone", "R")]},
    {"id": "D3a", "task": "disease", "kind": "train",
     "changes": {"lr": 1e-4, "fine_tune": False},
     "question": "Is the stage-1 learning rate right? (too slow)",
     "rows": [("D3-0.0001", "stage1_best", "Stage-1 learning rate 0.0001", "D6-0")]},
    {"id": "D3b", "task": "disease", "kind": "train",
     "changes": {"lr": 1e-2, "fine_tune": False},
     "question": "Is the stage-1 learning rate right? (too fast)",
     "rows": [("D3-0.01", "stage1_best", "Stage-1 learning rate 0.01", "D6-0")]},
]
EXP_BY_ID = {e["id"]: e for e in EXPERIMENTS}


def log(msg=""):
    print(msg, flush=True)
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


LOG_PATH = None


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

class Data:
    """Where every split lives, and how its labels are read."""

    def __init__(self, root, balanced_dir, labels_path):
        self.root = Path(root)
        self.balanced = Path(balanced_dir)
        self.labels_path = Path(labels_path)
        self._grades = None

    @property
    def grades(self):
        if self._grades is None:
            from train_severity import load_severity_labels
            self._grades, _ = load_severity_labels(self.labels_path)
        return self._grades

    def disease_classes(self):
        root = self.root / "split_augmented" / "train"
        if not root.is_dir():
            sys.exit("ERROR: {} not found. Run split_dataset.py and the "
                     "augmentation step first.".format(root))
        return sorted(d.name for d in root.iterdir() if d.is_dir())

    def severity_dir(self, split):
        return self.root / "split_augmented" if split == "original" else self.balanced

    def train_set(self, task, split, augmented):
        """(paths, labels, class_names) for training."""
        if task == "disease":
            classes = self.disease_classes()
            root = self.root / ("split_augmented" if augmented else "split") / "train"
            paths, labels = [], []
            for i, c in enumerate(classes):
                for p in sorted((root / c).glob("*.jpg")):
                    paths.append(p)
                    labels.append(i)
            return paths, labels, classes
        from train_severity import collect_split
        d = self.severity_dir(split) / "train"
        if not d.is_dir():
            sys.exit("ERROR: {} not found. For the balanced split run "
                     "split_severity.py, then augment its train folders.".format(d))
        paths, labels, _ = collect_split(d, self.grades)
        return paths, labels, list(SEVERITY_CLASSES)

    def eval_set(self, task, split, part, classes):
        """(paths, labels) of unmodified originals, sorted as evaluate*.py sort them."""
        if task == "disease":
            from evaluate import collect_files
            return collect_files(self.root / "split_augmented" / part, classes)
        from evaluate_severity import collect
        return collect(self.severity_dir(split) / part, self.grades)


def training_sources(paths):
    """The original photograph behind every training file, from the manifests."""
    from train_severity import source_stem_from_name
    by_folder = {}
    for p in paths:
        by_folder.setdefault(p.parent, []).append(p)
    sources = set()
    for folder, files in by_folder.items():
        mapping = {}
        for m in folder.glob("manifest_*.csv"):
            with open(m, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    mapping[row["image_id"]] = Path(row["source_image"]).stem
        for p in files:
            sources.add(mapping.get(p.stem) or source_stem_from_name(p.stem))
    return sources


def assert_no_leakage(train_paths, held_out):
    """Refuse to train if any held-out photograph produced a training file."""
    sources = training_sources(train_paths)
    for name, paths in held_out.items():
        clash = sources & {p.stem for p in paths}
        if clash:
            sys.exit("ERROR: LEAKAGE -- {} {} photograph(s) also feed training, "
                     "e.g. {}".format(len(clash), name, sorted(clash)[:5]))
    return len(sources)


def load_eval_images(paths):
    """Exactly evaluate.py's loading: decode, bilinear resize, raw 0-255 floats."""
    import tensorflow as tf
    out = np.zeros((len(paths),) + IMG_SIZE + (3,), np.float32)
    for i, p in enumerate(paths):
        img = tf.io.decode_jpeg(tf.io.read_file(str(p)), channels=3)
        out[i] = tf.image.resize(img, IMG_SIZE, method="bilinear").numpy()
    return out


def _clear_partial_cache(cache):
    """A run that died mid-epoch leaves a half-written cache and a lock file.
    The index file is written last, so without it the cache is incomplete."""
    if not any(cache.parent.glob(cache.name + "*.index")):
        for f in cache.parent.glob(cache.name + "*"):
            f.unlink()


def train_dataset(paths, labels, n_classes, batch_size, cache_dir, repeat=1):
    """
    Shuffled once with a fixed seed, decoded once into a cache, then lightly
    reshuffled every epoch -- the same pattern as image_dataset_from_directory,
    which train.py uses. Images are cached as whole-number pixels, a difference
    of under half a grey level from decoding afresh every epoch.
    """
    import tensorflow as tf
    order = np.random.RandomState(SEED).permutation(len(paths))
    p = [str(paths[i]) for i in order]
    y = [int(labels[i]) for i in order]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "train_{}".format(hashlib.md5("\n".join(p).encode()).hexdigest()[:12])
    _clear_partial_cache(cache)

    def decode(path, label):
        img = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
        img = tf.image.resize(img, IMG_SIZE, method="bilinear")
        return tf.cast(tf.clip_by_value(tf.round(img), 0, 255), tf.uint8), label

    def to_model(img, label):
        return tf.cast(img, tf.float32), tf.one_hot(label, n_classes)

    at = tf.data.AUTOTUNE
    ds = tf.data.Dataset.from_tensor_slices((p, y)).map(decode, num_parallel_calls=at)
    ds = ds.cache(str(cache))
    if repeat > 1:
        ds = ds.repeat(repeat)
    ds = ds.shuffle(min(len(p) * repeat, SHUFFLE_BUFFER), seed=SEED,
                    reshuffle_each_iteration=True)
    return ds.map(to_model, num_parallel_calls=at).batch(batch_size).prefetch(at)


def class_weights(labels, n_classes):
    """n_samples / (n_classes * count), the formula train.py and train_severity.py use."""
    counts = np.bincount(np.asarray(labels), minlength=n_classes)
    return {i: float(counts.sum() / (n_classes * counts[i])) if counts[i] else 1.0
            for i in range(n_classes)}


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def build(task, recipe, n_classes):
    """(model, base). MobileNetV2 comes from the deployed training scripts."""
    if recipe["backbone"] == "mobilenetv2":
        if task == "disease":
            from train import build_model
        else:
            from train_severity import build_model
        return build_model(n_classes, recipe["dropout"])

    import tensorflow as tf
    from tensorflow.keras import layers, Model
    if recipe["backbone"] != "efficientnetb0":
        sys.exit("ERROR: unknown backbone {}".format(recipe["backbone"]))
    inputs = layers.Input(shape=IMG_SIZE + (3,), name="image_0_255")
    x = layers.RandomFlip("horizontal", name="aug_flip")(inputs)
    x = layers.RandomTranslation(0.05, 0.05, name="aug_shift")(x)
    # EfficientNet scales its own input inside the network and expects raw
    # 0-255, so there is no Rescaling layer here, unlike MobileNetV2.
    base = tf.keras.applications.EfficientNetB0(
        input_shape=IMG_SIZE + (3,), include_top=False, weights="imagenet")
    base.trainable = False
    x = base(x, training=False)
    x = layers.GlobalAveragePooling2D(name="pool")(x)
    x = layers.Dropout(recipe["dropout"], name="dropout")(x)
    outputs = layers.Dense(n_classes, activation="softmax", name=task)(x)
    return Model(inputs, outputs, name="efficientnetb0_" + task), base


def unfreeze_top(base, n_layers):
    """Stage 2 exactly as train.py does it: top layers open, BatchNorm kept frozen."""
    import tensorflow as tf
    base.trainable = True
    for layer in base.layers[:-n_layers]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False


def tta_views(x):
    """The 8 symmetries of a square: 4 quarter turns, each also mirrored.
    Training already showed the model 90/180/270-degree turns and mirror
    images, so none of these views is unfamiliar to it."""
    for k in range(4):
        r = np.rot90(x, k, axes=(1, 2))
        yield np.ascontiguousarray(r)
        yield np.ascontiguousarray(r[:, :, ::-1, :])


def predict(model, x, tta=False):
    if not tta:
        return model.predict(x, batch_size=32, verbose=0)
    return np.mean([model.predict(v, batch_size=32, verbose=0) for v in tta_views(x)], axis=0)


def make_scorer(state, val_x, val_y, n_classes, weights_dir, patience, stage,
                es_best, epoch_offset):
    """
    Scores the validation photographs after every epoch and applies the
    recipe's rules itself, so they are explicit rather than hidden in Keras:

      early stopping   stop after `patience` epochs without a new lowest
                       validation loss; in stage 2 the bar is the best loss of
                       the whole run so far, as in the deployed training
      learning rate    halved after 2 epochs without improvement
                       (ReduceLROnPlateau's rule in train.py)
      best weights     saved for the best epoch of each stage, and for the
                       best macro-F1 epoch, so any of them can be tested later
    """
    import tensorflow as tf
    from sklearn.metrics import f1_score

    class Scorer(tf.keras.callbacks.Callback):
        def __init__(self):
            super().__init__()
            self.stage_best = np.inf
            self.es_best, self.es_wait = es_best, 0
            self.lr_best, self.lr_wait = np.inf, 0

        def on_epoch_end(self, epoch, logs=None):
            logs = logs or {}
            probs = self.model.predict(val_x, batch_size=32, verbose=0)
            pred = probs.argmax(axis=1)
            loss = float(np.mean(-np.log(np.clip(probs[np.arange(len(val_y)), val_y], 1e-7, 1.0))))
            acc = float((pred == val_y).mean())
            f1 = float(f1_score(val_y, pred, average="macro",
                                labels=list(range(n_classes)), zero_division=0))
            lr = float(self.model.optimizer.learning_rate.numpy())
            n = epoch_offset + len(state["epochs"]) + 1
            state["epochs"].append({
                "epoch": n, "stage": stage, "lr": lr,
                "loss": float(logs.get("loss", np.nan)),
                "accuracy": float(logs.get("accuracy", np.nan)),
                "val_loss": loss, "val_accuracy": acc, "val_macro_f1": f1})
            state["probs"].append(probs.astype(np.float32))

            marks = []
            if loss < self.stage_best:
                self.stage_best = loss
                state["stage_best"][str(stage)] = {"epoch": n, "val_loss": loss}
                self.model.save_weights(str(weights_dir / "stage{}_best.weights.h5".format(stage)))
                marks.append("best loss in stage {}".format(stage))
            if f1 > state["best_f1"]["val_macro_f1"] or (
                    f1 == state["best_f1"]["val_macro_f1"] and loss < state["best_f1"]["val_loss"]):
                state["best_f1"] = {"epoch": n, "val_macro_f1": f1, "val_loss": loss}
                self.model.save_weights(str(weights_dir / "best_f1.weights.h5"))
                marks.append("best F1")

            if loss < self.es_best:
                self.es_best, self.es_wait = loss, 0
            else:
                self.es_wait += 1
                if self.es_wait >= patience:
                    self.model.stop_training = True
                    marks.append("early stop")
            if loss < self.lr_best - 1e-4:
                self.lr_best, self.lr_wait = loss, 0
            else:
                self.lr_wait += 1
                if self.lr_wait >= max(2, patience // 2):
                    self.model.optimizer.learning_rate = lr * 0.5
                    self.lr_wait = 0
                    marks.append("lr halved")
            log("    epoch {:>3} stage {}  val loss {:.4f}  acc {:.4f}  macro F1 {:.4f}  lr {:.0e}{}".format(
                n, stage, loss, acc, f1, lr, "   <- " + ", ".join(marks) if marks else ""))

    return Scorer()


# ---------------------------------------------------------------------------
# running one experiment
# ---------------------------------------------------------------------------

def environment():
    import tensorflow as tf
    gpus = tf.config.list_physical_devices("GPU")
    return {"tensorflow": tf.__version__,
            "gpu": [g.name for g in gpus] or "none (CPU)"}


def select_epoch(state, selector, n_stage1):
    """Translate a row selector into (epoch number, weights file name or None)."""
    epochs = state["epochs"]
    if selector == "best_loss":
        best = min(epochs, key=lambda e: e["val_loss"])
        return best["epoch"], "stage{}_best.weights.h5".format(best["stage"])
    if selector in ("stage1_best", "stage2_best"):
        b = state["stage_best"].get(selector[5])
        return (b["epoch"], "{}.weights.h5".format(selector)) if b else (None, None)
    if selector == "best_f1":
        return state["best_f1"]["epoch"], "best_f1.weights.h5"
    if selector.startswith("epoch:"):
        n = int(selector.split(":")[1])
        return (n, None) if n <= n_stage1 else (None, None)
    raise ValueError(selector)


def write_rows(exp, work, rows_out, probs_by_epoch, state, n_stage1):
    """One probability file per table row, read later by --report and --final-test."""
    (work / "rows").mkdir(exist_ok=True)
    first_epoch = state["epochs"][0]["epoch"] if state["epochs"] else 1
    for row_id, selector, label, reference in exp["rows"]:
        epoch, weights = select_epoch(state, selector, n_stage1)
        if epoch is None:
            log("  (row {} skipped: the run never reached that point)".format(row_id))
            continue
        np.save(work / "rows" / (row_id + ".npy"), probs_by_epoch[epoch - first_epoch])
        rows_out.append({"row": row_id, "label": label, "reference": reference,
                         "epoch": epoch, "selector": selector, "tta": False,
                         "weights": "{}/weights/{}".format(exp["id"], weights) if weights else None})


def run_train(exp, data, args, work):
    import tensorflow as tf
    task, split = exp["task"], exp.get("split", "original")
    recipe = dict(SEVERITY_RECIPE if task == "severity" else DISEASE_RECIPE)
    recipe.update(exp.get("changes", {}))

    paths, labels, classes = data.train_set(task, split, recipe["augmented"])
    val_paths, val_y = data.eval_set(task, split, "validation", classes)
    test_paths, _ = data.eval_set(task, split, "test", classes)
    n_sources = assert_no_leakage(paths, {"validation": val_paths, "test": test_paths})
    log("  training files {:,} from {} original photographs; validation {}".format(
        len(paths), n_sources, len(val_paths)))
    log("  leakage check: no validation or test photograph feeds training  OK")

    repeat = 1 if recipe["augmented"] else AUGMENT_FACTOR
    if args.smoke_test:
        keep = np.random.RandomState(SEED).permutation(len(paths))[:SMOKE_TRAIN_FILES]
        paths = [paths[i] for i in sorted(keep)]
        labels = [labels[i] for i in sorted(keep)]
        recipe.update(epochs=1, fine_tune_epochs=1, batch_size=16)
        repeat = min(repeat, 2)

    n = len(classes)
    cw = class_weights(labels, n) if recipe["class_weights"] else None
    ds = train_dataset(paths, labels, n, recipe["batch_size"],
                       Path(args.cache_dir) / ("smoke" if args.smoke_test else "full"), repeat)
    val_x, val_y = load_eval_images(val_paths), np.asarray(val_y)

    model, base = build(task, recipe, n)
    weights_dir = work / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    state = {"epochs": [], "probs": [], "stage_best": {},
             "best_f1": {"epoch": None, "val_macro_f1": -1.0, "val_loss": np.inf}}
    loss_fn = "categorical_crossentropy"
    t0 = time.time()

    parent = exp.get("continue_from")
    if parent:
        presult = read_result(args.out, parent)
        start = Path(args.out) / parent / "weights" / "stage1_best.weights.h5"
        es_best = presult["stage_best"]["1"]["val_loss"]
        # Numbered after ALL of the parent's frozen epochs, as its own stage 2
        # was, so both fine-tuning runs share one epoch axis.
        n_stage1, offset = 0, presult["stage1_epochs"]
        log("  continuing from {}'s best frozen epoch ({}), val loss {:.4f}".format(
            parent, presult["stage_best"]["1"]["epoch"], es_best))
    else:
        log("  STAGE 1 -- frozen base, lr {}".format(recipe["lr"]))
        model.compile(optimizer=tf.keras.optimizers.Adam(recipe["lr"]),
                      loss=loss_fn, metrics=["accuracy"])
        model.fit(ds, epochs=recipe["epochs"], class_weight=cw, verbose=2, shuffle=False,
                  callbacks=[make_scorer(state, val_x, val_y, n, weights_dir,
                                         recipe["patience"], 1, np.inf, 0)])
        n_stage1, offset = len(state["epochs"]), 0
        es_best = state["stage_best"]["1"]["val_loss"]
        start = weights_dir / "stage1_best.weights.h5"

    if recipe["fine_tune"]:
        # Stage 2 starts from the best frozen epoch, as EarlyStopping's
        # restore_best_weights made it do in train.py.
        model.load_weights(str(start))
        unfreeze_top(base, recipe["fine_tune_layers"])
        log("  STAGE 2 -- top {} layers, lr {}".format(
            recipe["fine_tune_layers"], recipe["fine_tune_lr"]))
        model.compile(optimizer=tf.keras.optimizers.Adam(recipe["fine_tune_lr"]),
                      loss=loss_fn, metrics=["accuracy"])
        model.fit(ds, epochs=recipe["fine_tune_epochs"], class_weight=cw, verbose=2,
                  shuffle=False,
                  callbacks=[make_scorer(state, val_x, val_y, n, weights_dir,
                                         recipe["patience"], 2, es_best, offset)])

    rows = []
    write_rows(exp, work, rows, state["probs"], state, n_stage1)
    with open(work / "epochs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(state["epochs"][0].keys()))
        w.writeheader()
        w.writerows(state["epochs"])
    return {
        "recipe": recipe, "class_names": classes, "split": split,
        "train_files": len(paths), "train_originals": n_sources,
        "repeat_per_epoch": repeat,
        "class_weights": {classes[i]: round(w, 4) for i, w in cw.items()} if cw else None,
        "val_files": [p.name for p in val_paths], "val_labels": val_y.tolist(),
        "epochs": state["epochs"], "stage_best": state["stage_best"],
        "best_f1": state["best_f1"], "stage1_epochs": n_stage1,
        "seconds": round(time.time() - t0, 1), "rows": rows,
    }


def run_existing(exp, data, args, work):
    """Score a model that is already trained -- the deployed ones."""
    import tensorflow as tf
    task, split = exp["task"], exp.get("split", "original")
    classes = data.disease_classes() if task == "disease" else list(SEVERITY_CLASSES)
    names_file = "class_names.json" if task == "disease" else "severity_class_names.json"
    names_path = Path(args.deployed) / names_file
    if names_path.exists() and json.loads(names_path.read_text()) != classes:
        sys.exit("ERROR: {} does not match the class folders {}".format(names_path, classes))
    val_paths, val_y = data.eval_set(task, split, "validation", classes)
    model = tf.keras.models.load_model(Path(args.deployed) / exp["model"], compile=False)
    (work / "rows").mkdir(parents=True, exist_ok=True)
    np.save(work / "rows" / (exp["id"] + ".npy"), predict(model, load_eval_images(val_paths)))
    row_id, _, label, reference = exp["rows"][0]
    return {"recipe": None, "class_names": classes, "split": split,
            "model_file": exp["model"],
            "val_files": [p.name for p in val_paths], "val_labels": list(map(int, val_y)),
            "rows": [{"row": row_id, "label": label, "reference": reference,
                      "epoch": None, "selector": None, "tta": False, "weights": None,
                      "model_file": exp["model"]}]}


def run_tta(exp, data, args, work):
    import tensorflow as tf
    classes = data.disease_classes()
    val_paths, val_y = data.eval_set("disease", "original", "validation", classes)
    val_x = load_eval_images(val_paths)
    (work / "rows").mkdir(parents=True, exist_ok=True)
    rows = []
    for row_id, source, label, reference in exp["rows"]:
        src_row = find_row(args.out, source)
        model = load_row_model(src_row, args)
        np.save(work / "rows" / (row_id + ".npy"), predict(model, val_x, tta=True))
        rows.append({"row": row_id, "label": label, "reference": reference,
                     "epoch": src_row.get("epoch"), "selector": "tta of " + source, "tta": True,
                     "weights": src_row.get("weights"), "model_file": src_row.get("model_file"),
                     "build_from": src_row["experiment"]})
        tf.keras.backend.clear_session()
    return {"recipe": None, "class_names": classes, "split": "original",
            "val_files": [p.name for p in val_paths], "val_labels": list(map(int, val_y)),
            "rows": rows}


def read_result(out, exp_id):
    p = Path(out) / exp_id / "result.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def find_row(out, row_id):
    for exp in EXPERIMENTS:
        r = read_result(out, exp["id"])
        for row in (r or {}).get("rows", []):
            if row["row"] == row_id:
                return dict(row, experiment=exp["id"], task=r["task"], split=r["split"],
                            class_names=r["class_names"], recipe=r.get("recipe"))
    sys.exit("ERROR: no finished experiment has a row called {}".format(row_id))


def load_row_model(row, args):
    """Rebuild the network a row describes and load its saved weights."""
    import tensorflow as tf
    if row.get("model_file"):
        return tf.keras.models.load_model(Path(args.deployed) / row["model_file"], compile=False)
    if not row.get("weights"):
        sys.exit("ERROR: row {} has no saved weights (it is a snapshot used for "
                 "the epoch curve only).".format(row["row"]))
    owner = read_result(args.out, row.get("build_from") or row["experiment"])
    model, _ = build(owner["task"], owner["recipe"], len(owner["class_names"]))
    model.load_weights(str(Path(args.out) / row["weights"]))
    return model


def run_one(exp, data, args):
    out = Path(args.out)
    final = out / exp["id"]
    work = Path(tempfile.gettempdir()) / "orchid_work" / exp["id"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    import tensorflow as tf
    tf.keras.backend.clear_session()
    gc.collect()
    tf.keras.utils.set_random_seed(SEED)

    log("\n" + "=" * 72)
    log("  {}  {}".format(exp["id"], exp["question"]))
    if exp.get("changes"):
        log("  change from the recipe: {}".format(exp["changes"]))
    log("=" * 72)
    t0 = time.time()
    runner = {"train": run_train, "existing": run_existing, "tta": run_tta}[exp["kind"]]
    result = runner(exp, data, args, work)
    result.update({"id": exp["id"], "task": exp["task"], "kind": exp["kind"],
                   "question": exp["question"], "changes": exp.get("changes", {}),
                   "smoke_test": bool(args.smoke_test),
                   "finished_at": datetime.now().isoformat(timespec="seconds"),
                   "wall_seconds": round(time.time() - t0, 1)})
    result.update(environment())
    (work / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    # Copy to Drive only once complete, then rename: a half-copied folder is
    # never mistaken for a finished experiment.
    tmp = out / (exp["id"] + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(work, tmp)
    shutil.rmtree(final, ignore_errors=True)
    try:
        tmp.rename(final)
    except OSError:
        # Some mounted drives refuse to rename folders. Copy result.json last,
        # because its presence is what marks an experiment as finished.
        shutil.copytree(work, final, ignore=shutil.ignore_patterns("result.json"))
        shutil.copy2(work / "result.json", final / "result.json")
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    log("  saved {} in {:.1f} min".format(final, (time.time() - t0) / 60))
    for row in result["rows"]:
        y = np.asarray(result["val_labels"])
        p = np.load(final / "rows" / (row["row"] + ".npy")).argmax(axis=1)
        log("    {:<10} {:<48} val accuracy {:.4f}".format(row["row"], row["label"], (p == y).mean()))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def fast_macro_f1(t, p, k):
    cm = np.bincount(t * k + p, minlength=k * k).reshape(k, k)
    tp = np.diag(cm).astype(float)
    denom = 2 * tp + (cm.sum(axis=0) - tp) + (cm.sum(axis=1) - tp)
    return float(np.mean(np.where(denom > 0, 2 * tp / np.maximum(denom, 1), 0.0)))


def paired_difference(y, pa, pb, k, n_boot=2000):
    """
    95% range of macro F1(a) - macro F1(b), resampling the SAME photographs
    for both models. Pairing removes the luck of which photographs happen to
    be in the set, so it is far more sensitive than comparing two ranges.
    """
    rng = np.random.default_rng(SEED)
    n = len(y)
    diffs = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        diffs.append(fast_macro_f1(y[i], pa[i], k) - fast_macro_f1(y[i], pb[i], k))
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def verdict(lo, hi):
    if lo > 0:
        return "better, beyond noise"
    if hi < 0:
        return "worse, beyond noise"
    return "no clear difference"


ROW_ORDER = ["DEP", "D1", "D2-5", "D2-10", "R", "D3-0.0001", "D3-0.01", "D4", "D5",
             "D6-0", "D6-30", "D6-60", "D7", "D8", "D9-R", "D9-DEP",
             "SDEP", "S1", "S2", "S3", "S4"]


def collect_rows(out):
    rows, results = [], {}
    for exp in EXPERIMENTS:
        r = read_result(out, exp["id"])
        if not r:
            continue
        results[exp["id"]] = r
        y = np.asarray(r["val_labels"])
        for row in r["rows"]:
            probs = np.load(Path(out) / exp["id"] / "rows" / (row["row"] + ".npy"))
            rows.append(dict(row, experiment=exp["id"], task=r["task"], split=r["split"],
                             y=y, probs=probs, val_files=r["val_files"],
                             class_names=r["class_names"]))
    rows.sort(key=lambda r: ROW_ORDER.index(r["row"]) if r["row"] in ROW_ORDER else 99)
    return rows, results


def score_row(row):
    from extra_metrics import classification_extras, ordinal_extras
    from sklearn.metrics import f1_score
    y, probs = row["y"], row["probs"]
    pred = probs.argmax(axis=1)
    k = len(row["class_names"])
    m = {"accuracy": float((pred == y).mean()),
         "macro_f1": float(f1_score(y, pred, average="macro", labels=list(range(k)),
                                    zero_division=0)),
         "n": int(len(y))}
    if row["task"] == "disease":
        x = classification_extras(y, pred, probs, row["class_names"])
        m.update(balanced_accuracy=x["balanced_accuracy"], kappa=x["cohen_kappa"],
                 mcc=x["mcc"], roc_auc=x["roc_auc_macro"],
                 ece=x["expected_calibration_error"],
                 ci_accuracy=x["ci95_accuracy"], ci_macro_f1=x["ci95_macro_f1"],
                 recall_per_class={c: float(((pred == i) & (y == i)).sum() / max((y == i).sum(), 1))
                                   for i, c in enumerate(row["class_names"])})
    else:
        x = ordinal_extras(y, pred, probs)
        m.update(within_one=float((np.abs(pred - y) <= 1).mean()),
                 qwk=x["quadratic_weighted_kappa"], mean_grade_error=x["mean_grade_error"],
                 kappa=x["cohen_kappa"], balanced_accuracy=x["balanced_accuracy"],
                 ci_accuracy=x["ci95_exact_accuracy"], ci_within_one=x["ci95_within_one_grade"],
                 ci_qwk=x["ci95_quadratic_weighted_kappa"],
                 severe_called_mild=int(((y == 2) & (pred == 0)).sum()))
    return m


def scored_on(row):
    if row["task"] == "disease":
        return "validation ({} photos)".format(row["metrics"]["n"])
    return "validation, {} split ({} diseased)".format(row["split"], row["metrics"]["n"])


def build_report(args):
    out = Path(args.out)
    rows, results = collect_rows(out)
    if not rows:
        sys.exit("ERROR: no finished experiments in {}".format(out))
    smoke = any(r.get("smoke_test") for r in results.values())
    report_dir = out / "report"
    report_dir.mkdir(exist_ok=True)

    by_id = {}
    for row in rows:
        row["metrics"] = score_row(row)
        by_id[row["row"]] = row
    for row in rows:
        ref = by_id.get(row.get("reference"))
        row["delta"] = None
        if ref is not None:
            if ref["val_files"] != row["val_files"]:
                continue        # different photographs: no paired comparison
            k = len(row["class_names"])
            lo, hi = paired_difference(row["y"], row["probs"].argmax(1),
                                       ref["probs"].argmax(1), k)
            # R is always one of D6-0 / D6-30, and D7 often coincides with R:
            # the same epoch of the same run, so say so rather than "no difference".
            same = np.array_equal(row["probs"], ref["probs"])
            row["delta"] = {"vs": ref["row"],
                            "macro_f1": row["metrics"]["macro_f1"] - ref["metrics"]["macro_f1"],
                            "ci95": [lo, hi],
                            "verdict": "same model as " + ref["row"] if same else verdict(lo, hi)}

    banner = ("SMOKE TEST -- 1 epoch on 48 photographs. These numbers prove the code "
              "runs and mean NOTHING. Do not report them.") if smoke else None

    # --- table ---------------------------------------------------------------
    lines = ["# Experiment results", ""]
    if banner:
        lines += ["**" + banner + "**", ""]
    lines += ["Every score is on VALIDATION photographs. The test photographs were not "
              "used. 95% ranges come from 2,000 resamples of the photographs; a "
              "difference is called beyond noise only when the paired 95% range of the "
              "difference excludes zero.", ""]
    for task, title in (("disease", "Disease classifier"), ("severity", "Severity classifier")):
        part = [r for r in rows if r["task"] == task]
        if not part:
            continue
        lines += ["## " + title, ""]
        if task == "disease":
            lines += ["| ID | What changed | Accuracy | Macro F1 (95% range) | Change vs | Difference (95% range) | Verdict | Epoch |",
                      "|---|---|---|---|---|---|---|---|"]
        else:
            lines += ["| ID | What changed | Scored on | Exact | Within one grade | Macro F1 | QWK | Change vs | Difference in macro F1 (95% range) | Verdict |",
                      "|---|---|---|---|---|---|---|---|---|---|"]
        for r in part:
            m, d = r["metrics"], r["delta"]
            dtxt = ("{:+.3f} ({:+.3f} to {:+.3f})".format(d["macro_f1"], *d["ci95"]), d["vs"],
                    d["verdict"]) if d else ("", "", "")
            if task == "disease":
                lines.append("| {} | {} | {:.3f} | {:.3f} ({:.3f}-{:.3f}) | {} | {} | {} | {} |".format(
                    r["row"], r["label"], m["accuracy"], m["macro_f1"], *m["ci_macro_f1"],
                    dtxt[1], dtxt[0], dtxt[2], r.get("epoch") or ""))
            else:
                lines.append("| {} | {} | {} | {:.3f} | {:.3f} | {:.3f} | {:.3f} | {} | {} | {} |".format(
                    r["row"], r["label"], scored_on(r), m["accuracy"], m["within_one"],
                    m["macro_f1"], m["qwk"], dtxt[1], dtxt[0], dtxt[2]))
        lines.append("")

    lines += ["## Run details", "", "| Experiment | Training files | Epochs run | Minutes | TensorFlow | GPU |",
              "|---|---|---|---|---|---|"]
    for exp_id, r in results.items():
        lines.append("| {} | {} | {} | {:.1f} | {} | {} |".format(
            exp_id, r.get("train_files", ""), len(r.get("epochs", [])) or "",
            r.get("wall_seconds", 0) / 60, r.get("tensorflow"), r.get("gpu")))
    (report_dir / "experiments_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(report_dir / "experiments_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "task", "label", "scored_on", "accuracy", "macro_f1",
                    "macro_f1_ci_low", "macro_f1_ci_high", "within_one", "qwk",
                    "kappa", "mcc", "roc_auc", "reference", "diff_macro_f1",
                    "diff_ci_low", "diff_ci_high", "verdict", "epoch", "smoke_test"])
        for r in rows:
            m, d = r["metrics"], r["delta"] or {}
            ci = m.get("ci_macro_f1") or [None, None]
            w.writerow([r["row"], r["task"], r["label"], scored_on(r), m["accuracy"],
                        m["macro_f1"], ci[0], ci[1], m.get("within_one"), m.get("qwk"),
                        m.get("kappa"), m.get("mcc"), m.get("roc_auc"), d.get("vs"),
                        d.get("macro_f1"), (d.get("ci95") or [None, None])[0],
                        (d.get("ci95") or [None, None])[1], d.get("verdict"),
                        r.get("epoch"), smoke])

    summary = {"smoke_test": smoke, "built_at": datetime.now().isoformat(timespec="seconds"),
               "rows": [{k: v for k, v in r.items() if k not in ("y", "probs", "val_files")}
                        for r in rows]}
    (report_dir / "experiments_summary.json").write_text(
        json.dumps(summary, indent=2, default=float), encoding="utf-8")

    figures = make_figures(rows, results, report_dir, banner)
    text = plain_summary(rows, banner)
    (report_dir / "summary.txt").write_text(text, encoding="utf-8")
    log(text)
    log("\n  table   : {}".format(report_dir / "experiments_table.md"))
    for fig in figures:
        log("  figure  : {}".format(fig))


def plain_summary(rows, banner):
    by_id = {r["row"]: r for r in rows}
    out = []
    if banner:
        out += [banner, ""]
    out.append("WHAT EACH EXPERIMENT FOUND (validation photographs)")
    out.append("")
    for r in rows:
        m = r["metrics"]
        line = "{:<10} {}: macro F1 {:.3f}, accuracy {:.3f}".format(
            r["row"], r["label"], m["macro_f1"], m["accuracy"])
        if r["task"] == "severity":
            line += ", within one grade {:.3f}".format(m["within_one"])
        d = r["delta"]
        if d:
            line += ".  Against {} ({:.3f}): {:+.3f}, {}.".format(
                d["vs"], by_id[d["vs"]]["metrics"]["macro_f1"], d["macro_f1"], d["verdict"])
        out.append(line)
    # Only rows with a saved model can be tested later; epoch snapshots cannot.
    cands = [r for r in rows if r["task"] == "disease" and (r.get("weights") or r.get("model_file"))]
    if cands:
        best = max(cands, key=lambda r: (r["metrics"]["macro_f1"], r["metrics"]["accuracy"]))
        out += ["", "Highest validation macro F1 (disease): {} -- {} ({:.3f}).".format(
            best["row"], best["label"], best["metrics"]["macro_f1"])]
    sev = [r for r in rows if r["task"] == "severity" and (r.get("weights") or r.get("model_file"))]
    if sev:
        best = max(sev, key=lambda r: (r["metrics"]["macro_f1"], r["metrics"]["within_one"]))
        out.append("Highest validation macro F1 (severity): {} -- {} ({:.3f}), {}.".format(
            best["row"], best["label"], best["metrics"]["macro_f1"], scored_on(best)))
    out += ["",
            "With about a dozen comparisons, one can cross the noise line by luck.",
            "So a winner is confirmed on the TEST photographs exactly once:",
            "    python run_experiments.py --final-test <ID>",
            "Severity rows scored on different splits are different photographs and",
            "are not compared directly."]
    return "\n".join(out) + "\n"


def make_figures(rows, results, report_dir, banner):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []
    stamp = (lambda fig: fig.text(0.5, 0.5, "SMOKE TEST\nnot results", ha="center",
                                  va="center", fontsize=40, color="red", alpha=0.25,
                                  rotation=20)) if banner else (lambda fig: None)
    by_id = {r["row"]: r for r in rows}

    # 1. the epoch curve of the reference run (answers D1, D2, D6, D7)
    r = results.get("R")
    if r and r.get("epochs"):
        e = r["epochs"]
        x = [d["epoch"] for d in e]
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6.4), sharex=True)
        a1.plot(x, [d["loss"] for d in e], "o-", ms=3, label="training loss")
        a1.plot(x, [d["val_loss"] for d in e], "o-", ms=3, label="validation loss")
        a1.set_ylabel("loss")
        a2.plot(x, [d["val_accuracy"] for d in e], "o-", ms=3, label="validation accuracy")
        a2.plot(x, [d["val_macro_f1"] for d in e], "o-", ms=3, label="validation macro F1")
        a2.set_ylabel("score")
        a2.set_xlabel("epoch")
        if r.get("stage1_epochs") and r["stage1_epochs"] < len(e):
            for a in (a1, a2):
                a.axvline(r["stage1_epochs"] + 0.5, color="grey", ls="--", lw=1)
            a1.text(r["stage1_epochs"] + 0.7, a1.get_ylim()[1], "fine-tuning starts",
                    va="top", fontsize=8, color="grey")
        for rid, colour in (("R", "black"), ("D7", "tab:red"), ("D1", "tab:purple")):
            row = by_id.get(rid)
            if row and row.get("epoch"):
                val = next(d["val_macro_f1"] for d in e if d["epoch"] == row["epoch"])
                a2.plot(row["epoch"], val, "*", ms=13, color=colour,
                        label="{} ({})".format(rid, row["label"].split(" (")[0]))
        for a in (a1, a2):
            a.grid(alpha=0.3)
            a.legend(fontsize=8)
        a1.set_title("Disease model: validation scores after every epoch (reference recipe)",
                     fontsize=10)
        stamp(fig)
        fig.tight_layout()
        p = report_dir / "fig_epoch_curve.png"
        fig.savefig(p, dpi=200)
        plt.close(fig)
        made.append(p)

    # 2. every disease row with its 95% range
    dis = [row for row in rows if row["task"] == "disease"]
    if dis:
        fig, ax = plt.subplots(figsize=(8, 0.42 * len(dis) + 1.4))
        ys = np.arange(len(dis))[::-1]
        f1 = [row["metrics"]["macro_f1"] for row in dis]
        lo = [row["metrics"]["macro_f1"] - row["metrics"]["ci_macro_f1"][0] for row in dis]
        hi = [row["metrics"]["ci_macro_f1"][1] - row["metrics"]["macro_f1"] for row in dis]
        colours = ["tab:green" if (row["delta"] or {}).get("verdict", "").startswith("better")
                   else "tab:red" if (row["delta"] or {}).get("verdict", "").startswith("worse")
                   else "tab:blue" for row in dis]
        ax.barh(ys, f1, xerr=[lo, hi], color=colours, alpha=0.8, capsize=3)
        ax.set_yticks(ys)
        ax.set_yticklabels(["{}  {}".format(row["row"], row["label"]) for row in dis], fontsize=8)
        if "R" in by_id:
            ax.axvline(by_id["R"]["metrics"]["macro_f1"], color="black", ls="--", lw=1,
                       label="reference recipe (R)")
            ax.legend(fontsize=8, loc="lower right")
        ax.set_xlim(0, 1)
        ax.set_xlabel("validation macro F1 (bars: 95% range)")
        ax.set_title("Disease experiments. Green/red: beyond noise vs its reference", fontsize=10)
        ax.grid(axis="x", alpha=0.3)
        stamp(fig)
        fig.tight_layout()
        p = report_dir / "fig_disease_experiments.png"
        fig.savefig(p, dpi=200)
        plt.close(fig)
        made.append(p)

    # 3. learning-rate curves (stage 1 only)
    curves = [(results[k], lab) for k, lab in (("D3a", "lr 0.0001"), ("R", "lr 0.001 (recipe)"),
                                                ("D3b", "lr 0.01")) if k in results]
    if len(curves) > 1:
        fig, ax = plt.subplots(figsize=(7, 4))
        for r, lab in curves:
            e = [d for d in r["epochs"] if d["stage"] == 1]
            ax.plot([d["epoch"] for d in e], [d["val_macro_f1"] for d in e], "o-", ms=3, label=lab)
        ax.set_xlabel("epoch (frozen base)")
        ax.set_ylabel("validation macro F1")
        ax.set_title("Stage-1 learning rate", fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        stamp(fig)
        fig.tight_layout()
        p = report_dir / "fig_learning_rates.png"
        fig.savefig(p, dpi=200)
        plt.close(fig)
        made.append(p)

    # 4. severity
    sev = [row for row in rows if row["task"] == "severity"]
    if sev:
        keys = [("accuracy", "exact grade"), ("within_one", "within one grade"),
                ("macro_f1", "macro F1"), ("qwk", "weighted kappa")]
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        width = 0.8 / len(keys)
        xs = np.arange(len(sev))
        for j, (k, lab) in enumerate(keys):
            ax.bar(xs + (j - 1.5) * width, [row["metrics"][k] for row in sev], width, label=lab)
        ax.set_xticks(xs)
        ax.set_xticklabels(["{}\n{}".format(row["row"], row["split"]) for row in sev], fontsize=8)
        # Kappa can fall below zero (worse than chance), so the axis must show it.
        lowest = min(row["metrics"][k] for row in sev for k, _ in keys)
        ax.set_ylim(min(0.0, lowest - 0.05), 1.0)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel("validation score")
        ax.set_title("Severity experiments (original and balanced splits are different photographs)",
                     fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.16))
        stamp(fig)
        fig.tight_layout()
        p = report_dir / "fig_severity_experiments.png"
        fig.savefig(p, dpi=200)
        plt.close(fig)
        made.append(p)
    return made


# ---------------------------------------------------------------------------
# the one test-set evaluation
# ---------------------------------------------------------------------------

def final_test(args, row_id):
    from extra_metrics import (classification_extras, describe_classification,
                               describe_ordinal, ordinal_extras)
    from sklearn.metrics import classification_report, f1_score
    data = Data(args.data_root, args.balanced_dir, args.labels)
    row = find_row(args.out, row_id)
    classes = row["class_names"]
    paths, y = data.eval_set(row["task"], row["split"], "test", classes)
    model = load_row_model(row, args)
    probs = predict(model, load_eval_images(paths), tta=row.get("tta", False))
    y, pred = np.asarray(y), probs.argmax(axis=1)

    log_path = Path(args.out) / "test_log.json"
    history = json.loads(log_path.read_text()) if log_path.exists() else []
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 70)
    out("  FINAL TEST -- {} ({})".format(row_id, row["label"]))
    out("  {} test photographs, {} split, never used for training or choosing".format(
        len(y), row["split"]))
    earlier = [h["row"] for h in history
               if h.get("task") == row["task"] and h["split"] == row["split"]]
    if earlier:
        out("  NOTE: this test set has been used {} time(s) before: {}".format(
            len(earlier), earlier))
    out("=" * 70)
    k = len(classes)
    macro = float(f1_score(y, pred, average="macro", labels=list(range(k)), zero_division=0))
    out("  accuracy {:.4f}   macro F1 {:.4f}".format(float((pred == y).mean()), macro))
    out(classification_report(y, pred, labels=list(range(k)), target_names=classes,
                              digits=4, zero_division=0))
    if row["task"] == "disease":
        extras = classification_extras(y, pred, probs, classes)
        describe_classification(extras, out)
    else:
        extras = ordinal_extras(y, pred, probs)
        out("  within one grade {:.4f}".format(float((np.abs(pred - y) <= 1).mean())))
        describe_ordinal(extras, out)
    history.append({"row": row_id, "label": row["label"], "task": row["task"],
                    "split": row["split"],
                    "tested_at": datetime.now().isoformat(timespec="seconds"),
                    "smoke_test": bool(args.smoke_test), "n": int(len(y)),
                    "accuracy": float((pred == y).mean()), "macro_f1": macro,
                    "beyond_accuracy": extras})
    log_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    (Path(args.out) / "final_test_{}.txt".format(row_id)).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print("\n  recorded in {}".format(log_path))


# ---------------------------------------------------------------------------

def main():
    global LOG_PATH
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--balanced-dir", default=None,
                    help="augmented balanced severity split "
                         "(default: <data-root>/split_severity_augmented)")
    ap.add_argument("--labels", default=None,
                    help="severity_labels.csv (default: <data-root>/severity_labels.csv)")
    ap.add_argument("--deployed", default=str(DEFAULT_DEPLOYED),
                    help="folder holding the deployed .keras models")
    ap.add_argument("--out", default=None, help="results folder (Drive on Colab)")
    ap.add_argument("--cache-dir", default=str(Path(tempfile.gettempdir()) / "orchid_cache"))
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--redo", nargs="+", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--final-test", default=None, metavar="ROW_ID")
    ap.add_argument("--smoke-test", action="store_true",
                    help="1 epoch on 48 photographs: proves the code runs, NOT results")
    args = ap.parse_args()

    root = Path(args.data_root)
    args.balanced_dir = args.balanced_dir or str(root / "split_severity_augmented")
    args.labels = args.labels or str(root / "severity_labels.csv")
    if args.out is None:
        args.out = str(Path(tempfile.gettempdir()) / "orchid_experiments_SMOKE_TEST"
                       if args.smoke_test else DEFAULT_OUT)
    out = Path(args.out)

    if args.list:
        for e in EXPERIMENTS:
            done = "done" if read_result(out, e["id"]) else "-"
            print("  {:<5} {:<5} {}".format(e["id"], done, e["question"]))
            for row_id, _, label, _ in e["rows"]:
                print("          {:<10} {}".format(row_id, label))
        return
    if args.report:
        LOG_PATH = None
        build_report(args)
        return
    if args.final_test:
        final_test(args, args.final_test)
        return

    out.mkdir(parents=True, exist_ok=True)
    LOG_PATH = out / "run_log.txt"
    for e in out.glob("*.partial"):
        shutil.rmtree(e, ignore_errors=True)

    import tensorflow as tf
    for g in tf.config.list_physical_devices("GPU"):
        tf.config.experimental.set_memory_growth(g, True)
    env = environment()
    log("\n" + "#" * 72)
    log("  run started {}   TensorFlow {}   GPU {}".format(
        datetime.now().isoformat(timespec="seconds"), env["tensorflow"], env["gpu"]))
    log("  results -> {}".format(out))
    if args.smoke_test:
        log("  SMOKE TEST: 1 epoch on {} photographs. Proves the code runs; the "
            "numbers mean nothing.".format(SMOKE_TRAIN_FILES))
    log("#" * 72)

    data = Data(root, args.balanced_dir, args.labels)
    wanted = args.only or [e["id"] for e in EXPERIMENTS]
    unknown = set(wanted + args.redo) - set(EXP_BY_ID)
    if unknown:
        sys.exit("ERROR: unknown experiment(s) {}. See --list.".format(sorted(unknown)))
    # Redoing an experiment also redoes every experiment built on its weights.
    redo = list(args.redo)
    for exp_id in redo:
        for e in EXPERIMENTS:
            if (exp_id in e.get("needs", []) or e.get("continue_from") == exp_id) \
                    and e["id"] not in redo and read_result(out, e["id"]):
                log("  {} is built on {}, so it is redone too".format(e["id"], exp_id))
                redo.append(e["id"])
    for exp_id in redo:
        shutil.rmtree(out / exp_id, ignore_errors=True)

    started = time.time()
    for exp in EXPERIMENTS:
        if exp["id"] not in wanted:
            continue
        done = read_result(out, exp["id"])
        if done:
            if done.get("smoke_test") != bool(args.smoke_test):
                sys.exit("ERROR: {} holds a {} result; refusing to mix smoke-test and "
                         "real results in one folder.".format(
                             out / exp["id"], "smoke-test" if done.get("smoke_test") else "real"))
            log("\n  {} already done ({}), skipping".format(exp["id"], done["finished_at"]))
            continue
        needs = list(exp.get("needs", [])) + ([exp["continue_from"]] if exp.get("continue_from") else [])
        missing = [n for n in needs if not read_result(out, n)]
        if missing:
            log("\n  {} waits for {} -- skipped this time".format(exp["id"], missing))
            continue
        run_one(exp, data, args)
    log("\n  all requested experiments finished in {:.1f} min".format((time.time() - started) / 60))
    log("  next: python run_experiments.py --report{}".format(
        " --smoke-test" if args.smoke_test else ""))


if __name__ == "__main__":
    main()
