"""
label_severity.py -- fast keyboard labelling of severity grades.

Excel works for this, but it means opening each photograph separately in another
window, which is where the time goes. This shows the image and takes one
keystroke per grade.

    1  mild        under 10% of leaf area affected
    2  moderate    10% - 40%
    3  severe      over 40%

    <-  previous          ->  next (skip without labelling)
    u   undo last grade   q   quit

Every keystroke writes the CSV immediately, so closing the window, a crash, or a
power cut costs nothing. Re-running picks up where you stopped.

Rows are ordered train first, then validation, then test, because train labels
are the ones that actually teach the severity model. If you run out of time
having labelled only the train rows, you still have a trainable model.

Usage:
    python label_severity.py
    python label_severity.py --class phyllosticta_leaf_spot   # one class only
    python label_severity.py --relabel                        # revisit graded rows
"""

import argparse
import csv
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = COMPONENT_ROOT / "data" / "severity_labels.csv"
DEFAULT_IMAGES = COMPONENT_ROOT / "data" / "processed"

GRADES = {"1": "mild", "2": "moderate", "3": "severe"}
GRADE_HELP = {"mild": "under 10%", "moderate": "10-40%", "severe": "over 40%"}
VALID = set(GRADES.values())
HEALTHY = {"healthy"}
SPLIT_ORDER = {"train": 0, "validation": 1, "test": 2, "": 3}


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def save_rows(csv_path, rows, fields):
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(csv_path)          # atomic: a crash mid-write cannot corrupt it


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--images", default=str(DEFAULT_IMAGES))
    ap.add_argument("--class", dest="only_class", default=None)
    ap.add_argument("--split", default=None, choices=["train", "validation", "test"])
    ap.add_argument("--relabel", action="store_true",
                    help="include rows that already have a grade")
    ap.add_argument("--self-test", action="store_true",
                    help="build the window and load the first image, then exit "
                         "without showing anything -- proves it will work")
    args = ap.parse_args()

    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError as exc:
        sys.exit("ERROR: {}\nNeeds tkinter (bundled with Python) and Pillow.\n"
                 "If tkinter is missing, use Excel instead -- see HOW_TO_RUN.md."
                 .format(exc))

    csv_path = Path(args.csv).resolve()
    images_root = Path(args.images).resolve()
    if not csv_path.exists():
        sys.exit("ERROR: {} not found. Run make_labels_template.py first.".format(csv_path))

    rows, fields = load_rows(csv_path)

    backup = csv_path.with_name("severity_labels.before_labelling_{}.csv".format(
        datetime.now().strftime("%Y%m%d_%H%M%S")))
    shutil.copy2(csv_path, backup)

    # Which rows need work, train first.
    todo = []
    for i, r in enumerate(rows):
        if r.get("class") in HEALTHY:
            continue
        if args.only_class and r.get("class") != args.only_class:
            continue
        if args.split and r.get("split") != args.split:
            continue
        graded = (r.get("severity") or "").strip() in VALID
        if graded and not args.relabel:
            continue
        todo.append(i)
    todo.sort(key=lambda i: (SPLIT_ORDER.get(rows[i].get("split", ""), 3),
                             rows[i].get("image_id", "")))

    diseased = [r for r in rows if r.get("class") not in HEALTHY]
    already = sum(1 for r in diseased if (r.get("severity") or "").strip() in VALID)

    if not todo:
        print("\nNothing to label -- all {} diseased rows are graded.".format(len(diseased)))
        print("Use --relabel to revisit them.")
        return

    print("\n{} image(s) to grade ({} of {} already done)".format(
        len(todo), already, len(diseased)))
    print("backup saved: {}\n".format(backup.name))

    state = {"pos": 0, "history": []}

    root = tk.Tk()
    root.title("Severity labelling")
    root.geometry("1100x820")
    root.configure(bg="#1a1a1a")

    header = tk.Label(root, font=("Segoe UI", 13, "bold"),
                      bg="#1a1a1a", fg="#f0f0f0", pady=8)
    header.pack(fill="x")

    sub = tk.Label(root, font=("Consolas", 10), bg="#1a1a1a", fg="#9aa39c")
    sub.pack(fill="x")

    canvas = tk.Label(root, bg="#0f0f0f")
    canvas.pack(expand=True, fill="both", padx=12, pady=8)

    keys = tk.Label(
        root,
        text="   1 = mild (under 10%)      2 = moderate (10-40%)      3 = severe (over 40%)   ",
        font=("Segoe UI", 13, "bold"), bg="#2a2a2a", fg="#ffffff", pady=12)
    keys.pack(fill="x")

    footer = tk.Label(
        root,
        text="← previous     → skip     u undo     q quit     "
             "(every keystroke saves immediately)",
        font=("Segoe UI", 10), bg="#1a1a1a", fg="#7a857e", pady=6)
    footer.pack(fill="x")

    photo_ref = {"img": None}      # keep a reference or Tk garbage-collects it

    def show():
        if state["pos"] >= len(todo):
            header.config(text="Finished -- all {} images graded".format(len(todo)))
            sub.config(text="Close this window, then run:  "
                            "python make_labels_template.py --progress")
            canvas.config(image="", text="\n\nAll done.\n\nYou can close this window.",
                          font=("Segoe UI", 22), fg="#7FB48E")
            return

        row = rows[todo[state["pos"]]]
        path = images_root / row["class"] / row["filename"]

        done_now = sum(1 for r in diseased if (r.get("severity") or "").strip() in VALID)
        pct = 100.0 * done_now / len(diseased)
        header.config(text="{}   [{}]   {} / {} in this session   |   "
                           "{} of {} total ({:.0f}%)".format(
                               row["filename"], row["class"],
                               state["pos"] + 1, len(todo),
                               done_now, len(diseased), pct))

        current = (row.get("severity") or "").strip()
        mix = Counter((r.get("severity") or "").strip()
                      for r in diseased if (r.get("severity") or "").strip() in VALID)
        sub.config(text="split={:<11}  current grade={:<9}  so far: {}".format(
            row.get("split", "?"), current or "-", dict(mix) or "none"))

        try:
            im = Image.open(path)
            im.thumbnail((1040, 560), Image.LANCZOS)
            photo_ref["img"] = ImageTk.PhotoImage(im)
            canvas.config(image=photo_ref["img"], text="")
        except Exception as exc:                                  # noqa: BLE001
            canvas.config(image="", text="Could not open\n{}\n\n{}".format(path, exc),
                          font=("Consolas", 11), fg="#D9875F")

    def grade(value):
        if state["pos"] >= len(todo):
            return
        idx = todo[state["pos"]]
        state["history"].append((idx, rows[idx].get("severity", "")))
        rows[idx]["severity"] = value
        save_rows(csv_path, rows, fields)
        state["pos"] += 1
        show()

    def undo():
        if not state["history"]:
            return
        idx, previous = state["history"].pop()
        rows[idx]["severity"] = previous
        save_rows(csv_path, rows, fields)
        state["pos"] = max(0, state["pos"] - 1)
        show()

    def move(step):
        state["pos"] = max(0, min(len(todo), state["pos"] + step))
        show()

    def on_key(event):
        k = event.keysym
        if event.char in GRADES:
            grade(GRADES[event.char])
        elif k == "Right":
            move(1)
        elif k == "Left":
            move(-1)
        elif k in ("u", "U"):
            undo()
        elif k in ("q", "Q", "Escape"):
            root.destroy()

    root.bind("<Key>", on_key)

    if args.self_test:
        # Everything except the interactive loop: creates the window, renders
        # the first image, then tears down. Proves tkinter, Pillow, the CSV and
        # the image paths all work before you rely on this under time pressure.
        root.withdraw()
        show()
        root.update()
        ok = photo_ref["img"] is not None
        root.destroy()
        print("  window built      : OK")
        print("  first image loaded : {}".format("OK" if ok else "FAILED"))
        print("  rows queued        : {}".format(len(todo)))
        print("\nSelf-test {}. Run without --self-test to start labelling."
              .format("PASSED" if ok else "FAILED"))
        backup.unlink(missing_ok=True)
        sys.exit(0 if ok else 1)

    root.focus_force()
    show()
    root.mainloop()

    save_rows(csv_path, rows, fields)
    final = sum(1 for r in diseased if (r.get("severity") or "").strip() in VALID)
    mix = Counter((r.get("severity") or "").strip()
                  for r in diseased if (r.get("severity") or "").strip() in VALID)
    print("\nsaved: {}".format(csv_path))
    print("graded: {} of {} diseased images".format(final, len(diseased)))
    print("grade mix: {}".format(dict(mix)))
    print("\nNext: python make_labels_template.py --progress")


if __name__ == "__main__":
    main()
