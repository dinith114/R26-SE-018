"""
Farm Planner v2 — Guided scan, trial placement, and optimization.

Flow:
  POST /new-session         → create session, get 8 scan positions
  POST /scan-photo          → upload each photo, get OpenCV analysis
  GET  /scan-summary/{id}   → aggregated dimension hints after all photos
  POST /confirm-model       → user confirms W/L/H, backend generates trial positions
  POST /trial-start/{id}/{pos} → user placed sensor at this position
  POST /trial-done/{id}/{pos}  → user finished collecting at this position
  GET  /trial-status/{id}   → live collection progress
  POST /analyze-trial/{id}  → correlation + coverage analysis → recommendations
  POST /pipeline-route      → Prim's MST irrigation pipe route
"""

import uuid
import math
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# ─── In-memory sessions ───────────────────────────────────────────────────────
# sessionId → session dict (sufficient for single-server demo deployment)
SESSIONS: Dict[str, dict] = {}

# ─── 8 scan positions ─────────────────────────────────────────────────────────
SCAN_POSITIONS = [
    {"id": 1, "label": "South wall centre",
     "stand": "Stand at the SOUTH wall, middle point.",
     "face":  "Face NORTH. Capture full width — floor to ceiling."},
    {"id": 2, "label": "SE corner",
     "stand": "Stand at the SOUTH-EAST corner.",
     "face":  "Face NORTH-WEST. Both walls should be in frame."},
    {"id": 3, "label": "East wall centre",
     "stand": "Stand at the EAST wall, middle point.",
     "face":  "Face WEST. Capture full length — floor to ceiling."},
    {"id": 4, "label": "NE corner",
     "stand": "Stand at the NORTH-EAST corner.",
     "face":  "Face SOUTH-WEST. Both walls should be in frame."},
    {"id": 5, "label": "North wall centre",
     "stand": "Stand at the NORTH wall, middle point.",
     "face":  "Face SOUTH. Capture full width — floor to ceiling."},
    {"id": 6, "label": "NW corner",
     "stand": "Stand at the NORTH-WEST corner.",
     "face":  "Face SOUTH-EAST. Both walls should be in frame."},
    {"id": 7, "label": "West wall centre",
     "stand": "Stand at the WEST wall, middle point.",
     "face":  "Face EAST. Capture full length — floor to ceiling."},
    {"id": 8, "label": "SW corner",
     "stand": "Stand at the SOUTH-WEST corner.",
     "face":  "Face NORTH-EAST. Both walls should be in frame."},
]


# ─── OpenCV photo analysis ────────────────────────────────────────────────────

def _analyze_photo(img_bytes: bytes, position: int) -> dict:
    nparr = np.frombuffer(img_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        return {"position": position, "quality": "error", "features": [], "error": "decode_failed"}

    img_h, img_w = img.shape[:2]
    gray    = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges   = cv2.Canny(blurred, 50, 150)

    min_line = max(50, img_w // 7)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                             threshold=60, minLineLength=min_line, maxLineGap=15)

    h_lines, v_lines = [], []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx, dy = x2 - x1, y2 - y1
            angle  = abs(math.degrees(math.atan2(dy, dx))) if dx != 0 else 90.0
            if angle < 20 or angle > 160:
                h_lines.append(line[0].tolist())
            elif 70 < angle < 110:
                v_lines.append(line[0].tolist())

    # Bright regions → windows / openings
    _, thresh = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    windows = [c for c in contours if cv2.contourArea(c) > img_w * img_h * 0.008]

    # Wall span estimates (0–1 ratio relative to image dimensions)
    h_ys = sorted({min(l[1], l[3]) for l in h_lines})
    v_xs = sorted({min(l[0], l[2]) for l in v_lines})

    wall_span_h = round((max(h_ys) - min(h_ys)) / img_h, 3) if len(h_ys) >= 2 else None
    wall_span_v = round((max(v_xs) - min(v_xs)) / img_w, 3) if len(v_xs) >= 2 else None

    features = []
    if len(h_lines) >= 2: features.append("walls_detected")
    if len(v_lines) >= 2: features.append("corners_detected")
    if len(windows) > 0:  features.append(f"{len(windows)}_openings")
    if wall_span_h:        features.append("height_estimable")
    if wall_span_v:        features.append("width_estimable")

    quality = "good" if len(features) >= 3 else ("ok" if len(features) >= 1 else "poor")

    return {
        "position":    position,
        "image_size":  [img_w, img_h],
        "h_lines":     len(h_lines),
        "v_lines":     len(v_lines),
        "openings":    len(windows),
        "wall_span_h": wall_span_h,
        "wall_span_v": wall_span_v,
        "features":    features,
        "quality":     quality,
    }


# ─── Trial position generator ─────────────────────────────────────────────────

def _trial_positions(width: float, length: float, height: float, n: int) -> list:
    cols = max(1, math.ceil(math.sqrt(n * width / length)))
    rows = max(1, math.ceil(n / cols))

    col_step = width  / (cols + 1)
    row_step = length / (rows + 1)

    positions, count = [], 1
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            if count > n:
                break
            positions.append({
                "id":           count,
                "x":            round(c * col_step, 2),
                "y":            round(r * row_step, 2),
                "height":       round(height * 0.4, 2),
                "label":        f"Position {count}",
                "status":       "pending",
                "start_time":   None,
                "end_time":     None,
                "reading_count": 0,
            })
            count += 1

    return positions[:n]


# ─── Plant layout helpers ─────────────────────────────────────────────────────

def _generate_plant_positions(width: float, length: float, rows: int, plants_per_row: int) -> list:
    """Generate evenly-spaced plant positions on the floor plan grid."""
    row_spacing   = length / (rows + 1)
    plant_spacing = width  / (plants_per_row + 1)
    positions, pid = [], 1
    for r in range(1, rows + 1):
        for p in range(1, plants_per_row + 1):
            positions.append({
                "id":  pid,
                "x":   round(p * plant_spacing, 2),
                "y":   round(r * row_spacing,   2),
                "row": r,
            })
            pid += 1
    return positions


def _recommend_sensors(plant_count: int, width: float, length: float) -> dict:
    """Zone-based sensor recommendation: 1 per 22 plants OR 1 per 20 m², whichever is higher."""
    area       = width * length
    by_plants  = math.ceil(plant_count / 22) if plant_count > 0 else 1
    by_area    = math.ceil(area / 20)
    recommended = max(by_plants, by_area, 1)
    zone_size   = math.ceil(plant_count / recommended) if recommended > 0 else plant_count
    return {
        "recommended_sensors": recommended,
        "by_plant_count":      by_plants,
        "by_area":             by_area,
        "zone_size":           zone_size,
        "reasoning": (
            f"{plant_count} plants across {area:.0f} m² → "
            f"{recommended} sensor zone(s), ~{zone_size} plants per sensor"
        ),
    }


def _detect_green_density(img_bytes: bytes) -> float:
    """Return fraction (0-1) of image pixels that are plant-green via HSV segmentation."""
    nparr = np.frombuffer(img_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([30, 40, 40]), np.array([90, 255, 200]))
    return round(float(np.count_nonzero(mask)) / (img.shape[0] * img.shape[1]), 3)


def _detect_plants(img_bytes: bytes, width: float, length: float) -> dict:
    """
    Detect individual orchid plants from a (preferably top-down) overview photo.

    Pipeline: HSV green segmentation -> morphological cleanup ->
    connected-component analysis. Each kept blob = one plant; its centroid is
    mapped proportionally onto the greenhouse floor (metres), and its mean
    saturation/brightness gives a rough health score.

    Honest limits: best on a clear overhead shot. Overlapping canopies can merge
    into one detection; heavy clutter can split one plant into several.
    """
    nparr = np.frombuffer(img_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return {"count": 0, "plants": [], "error": "decode_failed"}

    h, w = img.shape[:2]
    hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Broad orchid-leaf green range
    mask = cv2.inRange(hsv, np.array([28, 30, 30]), np.array([95, 255, 235]))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    img_area = float(h * w)
    min_area = img_area * 0.0008   # drop specks
    max_area = img_area * 0.30     # drop background-sized blobs

    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    plants = []
    for i in range(1, num):                       # skip background (0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area or area > max_area:
            continue
        cx, cy = centroids[i]
        comp   = labels == i
        mean_s = float(sat[comp].mean())
        mean_v = float(val[comp].mean())
        health = round(min(1.0, (mean_s / 255.0) * 0.6 + (mean_v / 255.0) * 0.4), 2)
        plants.append({
            "x":      round((cx / w) * width,  2),   # floor metres
            "y":      round((cy / h) * length, 2),
            "x_frac": round(cx / w, 3),
            "y_frac": round(cy / h, 3),
            "size":   round(area / img_area, 4),     # canopy size (frac of image)
            "health": health,
        })

    plants.sort(key=lambda p: (p["y"], p["x"]))
    for idx, p in enumerate(plants, 1):
        p["id"] = idx

    avg_health = round(sum(p["health"] for p in plants) / len(plants), 2) if plants else 0.0
    return {
        "count":       len(plants),
        "plants":      plants,
        "green_cover": round(float(np.count_nonzero(mask)) / img_area, 3),
        "avg_health":  avg_health,
        "image_size":  [w, h],
    }


# ─── Coverage gap finder ──────────────────────────────────────────────────────

def _uncovered_zones(width: float, length: float, positions: list, threshold: float = 4.0):
    gaps, step = [], 2.0
    x = step
    while x < width:
        y = step
        while y < length:
            nearest = min(
                (math.sqrt((p["x"] - x) ** 2 + (p["y"] - y) ** 2) for p in positions),
                default=float("inf"),
            )
            if nearest > threshold:
                gaps.append({"x": round(x, 1), "y": round(y, 1)})
            y += step
        x += step
    return gaps[:4]


# ─────────────────────────────── Endpoints ────────────────────────────────────

@router.post("/new-session")
async def new_session():
    sid = str(uuid.uuid4())[:8].upper()
    SESSIONS[sid] = {
        "session_id":          sid,
        "created_at":          datetime.now(timezone.utc).isoformat(),
        "photos":              {},
        "model":               None,
        "trial_positions":     [],
        "trial_duration_hours": 24,
        "status":              "scanning",
        "recommendations":     [],
        "final_positions":     [],
    }
    return {
        "session_id":    sid,
        "scan_positions": SCAN_POSITIONS,
        "total_positions": len(SCAN_POSITIONS),
    }


@router.post("/scan-photo")
async def scan_photo(
    file:       UploadFile = File(...),
    session_id: str = Form(...),
    position:   int = Form(...),
):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    contents = await file.read()
    analysis = _analyze_photo(contents, position)

    SESSIONS[session_id]["photos"][str(position)] = {
        "analysis":    analysis,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    captured = len(SESSIONS[session_id]["photos"])
    next_pos = SCAN_POSITIONS[position] if position < len(SCAN_POSITIONS) else None

    return {
        "position":       position,
        "analysis":       analysis,
        "total_captured": captured,
        "remaining":      max(0, 8 - captured),
        "scan_complete":  captured >= 8,
        "next_position":  next_pos,
    }


@router.get("/scan-summary/{session_id}")
async def scan_summary(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    photos = SESSIONS[session_id]["photos"]

    total_openings = sum(
        p["analysis"].get("openings", 0)
        for p in photos.values()
    )

    # Aggregate wall_span_v from wall-facing positions (1,3,5,7)
    spans = [
        photos[k]["analysis"]["wall_span_v"]
        for k in ["1", "3", "5", "7"]
        if k in photos and photos[k]["analysis"].get("wall_span_v")
    ]
    aspect_hint = round(sum(spans) / len(spans), 2) if spans else 0.5

    quality_ok  = sum(1 for p in photos.values() if p["analysis"]["quality"] in ("good", "ok"))

    return {
        "session_id":      session_id,
        "photos_captured": len(photos),
        "scan_complete":   len(photos) >= 8,
        "quality_ok":      quality_ok,
        "est_openings":    min(total_openings, 8),
        "aspect_hint":     aspect_hint,
        "note": (
            "OpenCV detected proportions from your photos. "
            "Enter the actual dimensions on the next screen — "
            "use a tape measure or step-count estimate."
        ),
    }


@router.post("/detect-plants/{session_id}")
async def detect_plants(
    session_id: str,
    file:   UploadFile = File(...),
    width:  float = Form(10.0),
    length: float = Form(20.0),
):
    """Detect orchid plants from an overview photo and map them onto the floor."""
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    contents = await file.read()
    result   = _detect_plants(contents, width, length)
    SESSIONS[session_id]["detected_plants"] = result

    count = result["count"]
    if count > 0:
        cols = max(1, round(math.sqrt(count * width / max(length, 0.1))))
        rows = max(1, math.ceil(count / cols))
    else:
        cols = rows = 0
    result["suggested_rows"]    = rows
    result["suggested_per_row"] = cols
    result["note"] = (
        "Plants detected from your photo using colour segmentation. "
        "For best accuracy use a top-down overview shot of the plant area. "
        "Overlapping leaves may be counted as one plant."
    )
    return result


@router.post("/confirm-model")
async def confirm_model(
    session_id:           str   = Form(...),
    width:                float = Form(...),
    length:               float = Form(...),
    height:               float = Form(3.0),
    target_zones:         int   = Form(4),
    trial_duration_hours: int   = Form(24),
    windows:              str   = Form("[]"),
    plant_rows:           int   = Form(5),
    plants_per_row:       int   = Form(10),
    detected_positions:   str   = Form("[]"),
):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    try:
        win_list = json.loads(windows)
    except Exception:
        win_list = []

    try:
        detected = json.loads(detected_positions)
    except Exception:
        detected = []

    if detected:
        # Real plant positions detected from a photo
        plant_positions = [{
            "id":     i + 1,
            "x":      p["x"],
            "y":      p["y"],
            "row":    p.get("row", 0),
            "health": p.get("health"),
            "size":   p.get("size"),
        } for i, p in enumerate(detected)]
        plant_count  = len(plant_positions)
        plant_source = "photo_detection"
    else:
        # Manual uniform grid from rows x plants-per-row
        plant_count     = plant_rows * plants_per_row
        plant_positions = _generate_plant_positions(width, length, plant_rows, plants_per_row)
        plant_source    = "manual_grid"

    sensor_rec      = _recommend_sensors(plant_count, width, length)

    # Use the higher of user zones and algorithm recommendation for trial
    effective_zones = max(target_zones, sensor_rec["recommended_sensors"])

    avg_health = None
    if detected:
        healths = [p.get("health") for p in detected if p.get("health") is not None]
        avg_health = round(sum(healths) / len(healths), 2) if healths else None

    model = {
        "width":                width,
        "length":               length,
        "height":               height,
        "windows":              win_list,
        "plant_rows":           plant_rows,
        "plants_per_row":       plants_per_row,
        "plant_count":          plant_count,
        "plant_positions":      plant_positions,
        "plant_source":         plant_source,
        "avg_health":           avg_health,
        "sensor_recommendation": sensor_rec,
        "confirmed_at":         datetime.now(timezone.utc).isoformat(),
    }
    hours_per = max(1, trial_duration_hours // max(effective_zones, 1))

    SESSIONS[session_id]["model"]                = model
    SESSIONS[session_id]["trial_duration_hours"] = trial_duration_hours
    SESSIONS[session_id]["status"]               = "trial_setup"

    positions = _trial_positions(width, length, height, effective_zones)
    SESSIONS[session_id]["trial_positions"] = positions

    return {
        "session_id":            session_id,
        "model":                 model,
        "trial_positions":       positions,
        "trial_duration_hours":  trial_duration_hours,
        "hours_per_position":    hours_per,
        "effective_zones":       effective_zones,
        "sensor_recommendation": sensor_rec,
        "instruction": (
            f"Place your sensor node at Position 1 first. "
            f"Leave it for ~{hours_per}h, then tap 'Done' and move to the next position. "
            f"({effective_zones} trial zones based on {plant_count} plants)"
        ),
    }


@router.post("/trial-start/{session_id}/{position_id}")
async def trial_start(session_id: str, position_id: int):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    session = SESSIONS[session_id]
    now     = datetime.now(timezone.utc).isoformat()

    for pos in session["trial_positions"]:
        if pos["status"] == "active":
            pos["status"]   = "done"
            pos["end_time"] = now

    for pos in session["trial_positions"]:
        if pos["id"] == position_id:
            pos["status"]     = "active"
            pos["start_time"] = now

    session["status"] = "trial_active"
    total    = len(session["trial_positions"])
    done     = sum(1 for p in session["trial_positions"] if p["status"] == "done")
    hours_pp = session["trial_duration_hours"] // total

    return {
        "session_id":      session_id,
        "active_position": position_id,
        "done":            done,
        "total":           total,
        "hours_here":      hours_pp,
        "message": f"Sensor placed at Position {position_id}. Leave it for ~{hours_pp}h.",
    }


@router.post("/trial-done/{session_id}/{position_id}")
async def trial_done(session_id: str, position_id: int, reading_count: int = 0):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    session = SESSIONS[session_id]
    now     = datetime.now(timezone.utc).isoformat()

    for pos in session["trial_positions"]:
        if pos["id"] == position_id:
            pos["status"]        = "done"
            pos["end_time"]      = now
            pos["reading_count"] = reading_count

    all_done = all(p["status"] == "done" for p in session["trial_positions"])
    if all_done:
        session["status"] = "trial_complete"

    next_pos = next((p for p in session["trial_positions"] if p["status"] == "pending"), None)

    return {
        "session_id": session_id,
        "all_done":   all_done,
        "next_position": next_pos,
    }


@router.get("/trial-status/{session_id}")
async def trial_status(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    session   = SESSIONS[session_id]
    positions = session["trial_positions"]
    done      = sum(1 for p in positions if p["status"] == "done")
    active    = next((p for p in positions if p["status"] == "active"), None)

    return {
        "session_id":   session_id,
        "status":       session["status"],
        "positions":    positions,
        "done":         done,
        "active":       active,
        "total":        len(positions),
        "pct_complete": round(100 * done / max(len(positions), 1)),
        "all_done":     done == len(positions),
    }


@router.post("/analyze-trial/{session_id}")
async def analyze_trial(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    session   = SESSIONS[session_id]
    model     = session.get("model")
    positions = session["trial_positions"]

    if not model:
        raise HTTPException(400, "Farm model not confirmed")

    recommendations = []
    final_positions = []

    for pos in positions:
        close = [
            p for p in positions
            if p["id"] != pos["id"]
            and math.sqrt((p["x"] - pos["x"]) ** 2 + (p["y"] - pos["y"]) ** 2) < 3.0
        ]
        if len(close) > 1:
            recommendations.append({
                "type":        "redundant",
                "position_id": pos["id"],
                "action":      "remove",
                "x":           pos["x"], "y": pos["y"],
                "message":
                    f"Position {pos['id']} is within 3 m of {len(close)} others — "
                    f"same microclimate. You can remove this sensor.",
            })
        else:
            recommendations.append({
                "type":        "keep",
                "position_id": pos["id"],
                "action":      "keep",
                "x":           pos["x"], "y": pos["y"],
                "message": f"Position {pos['id']} covers a unique zone — keep this sensor.",
            })
            final_positions.append(pos)

    for gap in _uncovered_zones(model["width"], model["length"], positions):
        recommendations.append({
            "type":        "gap",
            "position_id": None,
            "action":      "add",
            "x":           gap["x"], "y": gap["y"],
            "message":
                f"Area near ({gap['x']}m, {gap['y']}m) has no sensor within 4 m — "
                f"consider adding one here.",
        })

    session["status"]          = "complete"
    session["recommendations"] = recommendations
    session["final_positions"] = final_positions

    keep   = sum(1 for r in recommendations if r["action"] == "keep")
    remove = sum(1 for r in recommendations if r["action"] == "remove")
    add    = sum(1 for r in recommendations if r["action"] == "add")

    sensor_rec   = model.get("sensor_recommendation", {})
    plant_count  = model.get("plant_count", 0)
    final_count  = keep + add

    return {
        "session_id":            session_id,
        "recommendations":       recommendations,
        "final_positions":       final_positions,
        "plant_count":           plant_count,
        "final_sensor_count":    final_count,
        "sensor_recommendation": sensor_rec,
        "summary": (
            f"Keep {keep} · Remove {remove} · Add {add} sensor(s). "
            f"Final: {final_count} unit(s) for {plant_count} plants."
        ),
    }


@router.post("/pipeline-route")
async def pipeline_route(
    session_id:      str   = Form(...),
    water_source_x:  float = Form(0.0),
    water_source_y:  float = Form(0.0),
    plant_rows_json: str   = Form("[]"),
):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")

    model = SESSIONS[session_id].get("model")
    if not model:
        raise HTTPException(400, "Confirm farm model first")

    try:
        rows = json.loads(plant_rows_json)
    except Exception:
        rows = []

    # Build nodes: water source + plant row midpoints
    nodes = [{"id": 0, "x": water_source_x, "y": water_source_y, "label": "Water Source"}]
    w, l  = model["width"], model["length"]

    if rows:
        for i, row in enumerate(rows):
            mx = (row.get("start_x", 0) + row.get("end_x", w)) / 2
            my = (row.get("start_y", 0) + row.get("end_y", l)) / 2
            nodes.append({"id": i + 1, "x": round(mx, 2), "y": round(my, 2), "label": f"Row {i+1}"})
    else:
        # Default: 3 evenly spaced rows along farm centre
        for i in range(3):
            nodes.append({
                "id":    i + 1,
                "x":     round(w * (i + 1) / 4, 2),
                "y":     round(l / 2, 2),
                "label": f"Row {i + 1}",
            })

    def dist(a, b):
        return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)

    # Prim's MST
    in_tree = {nodes[0]["id"]}
    edges, total = [], 0.0

    while len(in_tree) < len(nodes):
        best, best_d = None, float("inf")
        for a in nodes:
            if a["id"] not in in_tree:
                continue
            for b in nodes:
                if b["id"] in in_tree:
                    continue
                d = dist(a, b)
                if d < best_d:
                    best_d, best = d, (a, b)
        if best:
            a, b = best
            in_tree.add(b["id"])
            total += best_d
            edges.append({
                "from":     {"id": a["id"], "x": a["x"], "y": a["y"], "label": a["label"]},
                "to":       {"id": b["id"], "x": b["x"], "y": b["y"], "label": b["label"]},
                "length_m": round(best_d, 2),
            })

    return {
        "session_id":          session_id,
        "nodes":               nodes,
        "pipe_segments":       edges,
        "total_length_m":      round(total, 2),
        "estimated_cost_lkr":  round(total * 150),
        "note": f"Minimum spanning tree route: {round(total, 1)} m of pipe total.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MICROCLIMATE ZONE DISCOVERY  —  "how many IoT devices does this house need?"
#
#  Principle: deploy ONE sensor device per microclimate zone. A zone = a set of
#  survey spots whose watering-relevant conditions are homogeneous enough that a
#  single sensor validly represents every plant in it. Unbalanced sun/environment
#  => more zones => more devices, so the watering ML never mispredicts for plants
#  in an unmeasured microclimate.
#
#  Method (data-driven):
#    1. Place the sensor pack at S survey spots (or move one between spots),
#       logging temperature / humidity / light / root-moisture over a daylight cycle.
#    2. Summarise each spot into watering-critical features.
#    3. Two spots are "the same zone" only if ALL per-feature differences are within
#       interpretable tolerances (default: 20% peak light, 2 C, 8% RH, 15% drying rate).
#    4. Single-linkage connected components over that similarity => zones.
#    5. Device count for the house = number of zones; place one device at each zone's
#       representative (medoid) spot.
# ═══════════════════════════════════════════════════════════════════════════════

# Default interpretable tolerances (tau) — two spots share a zone only if within ALL of these
DEFAULT_TOL = {
    "light_pct":    0.20,   # peak light differs by <= 20% of the brighter spot
    "temp_abs":     2.0,    # mean temperature differs by <= 2.0 C
    "humidity_abs": 8.0,    # mean humidity differs by <= 8.0 %RH
    "drying_pct":   0.15,   # drying rate differs by <= 15% (relative)
    "drying_abs":   0.5,    # ...or by <= 0.5 %/h absolutely (whichever is kinder,
                            #    so slow-drying shaded spots are not over-split)
}


def _summarize_spot(readings: list, features: Optional[dict] = None) -> dict:
    """Reduce a spot's reading series to watering-critical features.

    Returns: peak_light, light_range, mean_temp, mean_humidity, drying_rate (%/h).
    If `features` is supplied (pre-summarised), it is used directly.
    """
    if features:
        return {
            "peak_light":    float(features.get("peak_light", 0.0)),
            "light_range":   float(features.get("light_range", 0.0)),
            "mean_temp":     float(features.get("mean_temp", 0.0)),
            "mean_humidity": float(features.get("mean_humidity", 0.0)),
            "drying_rate":   float(features.get("drying_rate", 0.0)),
        }

    lights = [float(r.get("light")) for r in readings
              if r.get("light") is not None and float(r.get("light")) >= 0]   # drop -999 sentinel
    temps  = [float(r.get("temperature")) for r in readings if r.get("temperature") is not None]
    hums   = [float(r.get("humidity")) for r in readings if r.get("humidity") is not None]

    # Drying rate: mean of positive moisture drops per hour across consecutive readings
    series = []
    for i, r in enumerate(readings):
        m = r.get("rootMoisturePct", r.get("moisture"))
        if m is None:
            continue
        ts = r.get("timestamp")
        t_h = (float(ts) / 3600000.0) if ts is not None else float(i) * (5.0 / 60.0)  # assume 5-min spacing
        series.append((t_h, float(m)))
    series.sort(key=lambda p: p[0])
    drops = []
    for (t0, m0), (t1, m1) in zip(series, series[1:]):
        dt = t1 - t0
        if dt > 0 and m1 < m0:
            drops.append((m0 - m1) / dt)
    drying_rate = round(sum(drops) / len(drops), 3) if drops else 0.0

    return {
        "peak_light":    round(max(lights), 1) if lights else 0.0,
        "light_range":   round(max(lights) - min(lights), 1) if lights else 0.0,
        "mean_temp":     round(sum(temps) / len(temps), 2) if temps else 0.0,
        "mean_humidity": round(sum(hums) / len(hums), 2) if hums else 0.0,
        "drying_rate":   drying_rate,
    }


def _spots_similar(a: dict, b: dict, tol: dict) -> bool:
    """True if two spot summaries belong to the same microclimate zone (within ALL tolerances)."""
    light_hi = max(a["peak_light"], b["peak_light"], 1.0)
    if abs(a["peak_light"] - b["peak_light"]) / light_hi > tol["light_pct"]:
        return False
    if abs(a["mean_temp"] - b["mean_temp"]) > tol["temp_abs"]:
        return False
    if abs(a["mean_humidity"] - b["mean_humidity"]) > tol["humidity_abs"]:
        return False
    # Drying rate: a purely RELATIVE test is unstable near zero — two shaded
    # spots drying at 1.1 and 1.3 %/h differ by 15% relatively, but only
    # 0.2 %/h absolutely, which is horticulturally meaningless and would make
    # the farmer buy an extra device for no reason. So the spots are the same
    # zone if EITHER the relative OR the absolute difference is small.
    dry_diff = abs(a["drying_rate"] - b["drying_rate"])
    dry_hi   = max(a["drying_rate"], b["drying_rate"], 0.5)
    if dry_diff > tol["drying_abs"] and (dry_diff / dry_hi) > tol["drying_pct"]:
        return False
    return True


def _discover_zones(spots: list, tol: dict) -> list:
    """Single-linkage clustering of survey spots by microclimate similarity.

    spots: [{"spot_id","x","y","summary":{features}}]
    Returns a list of zones, each with members, representative (medoid) spot and spreads.
    """
    n = len(spots)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    for i in range(n):
        for j in range(i + 1, n):
            if _spots_similar(spots[i]["summary"], spots[j]["summary"], tol):
                union(i, j)

    # Group by root
    groups: Dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    zones = []
    for zid, idxs in enumerate(groups.values()):
        members = [spots[i] for i in idxs]
        # Zone mean feature vector
        keys = ["peak_light", "light_range", "mean_temp", "mean_humidity", "drying_rate"]
        mean = {k: sum(m["summary"][k] for m in members) / len(members) for k in keys}
        # Representative = member nearest the zone mean (normalised by mean magnitude)
        def dist_to_mean(m):
            return sum(((m["summary"][k] - mean[k]) / (abs(mean[k]) + 1.0)) ** 2 for k in keys)
        rep = min(members, key=dist_to_mean)
        spread = {k: round(max(m["summary"][k] for m in members) - min(m["summary"][k] for m in members), 2)
                  for k in keys}
        zones.append({
            "zone_id":        zid,
            "spot_ids":       [m.get("spot_id") for m in members],
            "member_count":   len(members),
            "representative": {"spot_id": rep.get("spot_id"), "x": rep.get("x", 0.0), "y": rep.get("y", 0.0)},
            "mean":           {k: round(v, 2) for k, v in mean.items()},
            "spread":         spread,
        })
    return zones


# ─── Request models ────────────────────────────────────────────────────────────

class SurveySpot(BaseModel):
    spot_id:  Optional[str] = None
    x:        float = 0.0
    y:        float = 0.0
    readings: List[dict] = Field(default_factory=list)
    features: Optional[Dict[str, float]] = None


class ZoneAnalyzeRequest(BaseModel):
    spots:       List[SurveySpot]
    tolerances:  Optional[Dict[str, float]] = None
    plant_count: Optional[int] = None
    house_name:  Optional[str] = None


@router.post("/zone-analyze")
async def zone_analyze(req: ZoneAnalyzeRequest):
    """Compute how many IoT sensor devices a house needs from survey spot-readings.

    Each survey spot may provide either a `readings` time-series or pre-summarised
    `features`. Returns the number of microclimate zones (= devices required), the
    zone map, and a representative placement spot per zone.
    """
    if not req.spots:
        raise HTTPException(400, "Provide at least one survey spot")

    tol = dict(DEFAULT_TOL)
    if req.tolerances:
        tol.update({k: float(v) for k, v in req.tolerances.items() if k in DEFAULT_TOL})

    spots = []
    for i, s in enumerate(req.spots):
        spots.append({
            "spot_id": s.spot_id or f"S{i + 1}",
            "x":       s.x,
            "y":       s.y,
            "summary": _summarize_spot(s.readings, s.features),
        })

    zones = _discover_zones(spots, tol)
    device_count = len(zones)

    plants_per_device = None
    if req.plant_count and device_count > 0:
        plants_per_device = math.ceil(req.plant_count / device_count)

    return {
        "house_name":         req.house_name,
        "surveyed_spots":     len(spots),
        "device_count":       device_count,
        "zones":              zones,
        "spot_summaries":     spots,
        "tolerances":         tol,
        "plants_per_device":  plants_per_device,
        "reasoning": (
            f"{len(spots)} survey spot(s) collapsed into {device_count} microclimate "
            f"zone(s) under the tolerances {tol}. Deploy {device_count} sensor "
            f"device(s) — one per zone, at each zone's representative spot — so every "
            f"plant is represented by a sensor in its own microclimate."
        ),
    }
