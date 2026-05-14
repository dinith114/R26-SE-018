"""
Farm Sensor Placement Optimizer
Simulates light/heat gradients across a greenhouse floor grid,
clusters similar-condition cells into zones, and returns the
optimal sensor position (zone centroid) for each zone.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional
import math
import random

router = APIRouter()


# ─────────────────────────── Input schemas ────────────────────────────

class Window(BaseModel):
    wall: str = Field(..., description="north | south | east | west")
    position: float = Field(..., description="0.0–1.0 along wall length")
    width: float = Field(1.0, description="Opening width in metres")

class Obstacle(BaseModel):
    x: float
    y: float
    width: float
    height: float
    type: str = Field("shade", description="shade | wall | fan")

class PlantRow(BaseModel):
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    plant_count: int = 10

class FarmConfig(BaseModel):
    width: float = Field(..., description="Farm width in metres (east–west)")
    length: float = Field(..., description="Farm length in metres (north–south)")
    height: float = Field(3.0, description="Greenhouse height in metres")
    windows: List[Window] = []
    obstacles: List[Obstacle] = []
    plant_rows: List[PlantRow] = []
    target_zones: int = Field(4, ge=1, le=12, description="Desired number of sensor zones")
    grid_resolution: float = Field(0.5, description="Grid cell size in metres")
    hour_of_day: float = Field(10.0, description="Hour for light simulation (6–18)")


# ─────────────────────────── Output schemas ───────────────────────────

class SensorPosition(BaseModel):
    zone_id: int
    x: float
    y: float
    height: float
    zone_color: str
    cell_count: int
    avg_light_score: float
    coverage_pct: float

class ZoneCell(BaseModel):
    x: float
    y: float
    zone_id: int
    light_score: float

class AnalysisResult(BaseModel):
    zones: int
    total_area: float
    sensor_positions: List[SensorPosition]
    grid_cells: List[ZoneCell]
    plant_rows: List[PlantRow]
    farm_width: float
    farm_length: float
    farm_height: float
    coverage_summary: str


# ─────────────────────────── Zone colours ─────────────────────────────

ZONE_COLORS = [
    "#4CAF50", "#2196F3", "#FF9800", "#E91E63",
    "#9C27B0", "#00BCD4", "#FF5722", "#607D8B",
    "#CDDC39", "#F44336", "#3F51B5", "#009688",
]


# ─────────────────────────── Light simulation ─────────────────────────

def _sun_direction(hour: float):
    """
    Returns a (dx, dy) unit vector for the sun's horizontal direction
    in Sri Lanka (~7°N latitude).
    hour 6  → sun rises east  → light comes from east  (dx=-1, dy=0)
    hour 12 → sun is north    → light comes from north  (dx=0, dy=-1)
    hour 18 → sun sets west   → light comes from west   (dx=1, dy=0)
    """
    angle_rad = math.pi * (hour - 6) / 12        # 0 (east) → π (west)
    dx = -math.cos(angle_rad)
    dy = -math.sin(angle_rad)
    return dx, dy


def _compute_light_grid(config: FarmConfig) -> list:
    """
    Build a 2D grid where each cell has a light_score 0.0–1.0.

    Algorithm:
      For each grid cell, compute contribution from every window:
        1. Distance from cell to window opening
        2. Directional factor (is the sun shining through this window now?)
        3. Obstacle shadow (cells behind obstacles get reduced light)
    """
    cols = max(1, int(config.width  / config.grid_resolution))
    rows = max(1, int(config.length / config.grid_resolution))

    sun_dx, sun_dy = _sun_direction(config.hour_of_day)

    # Pre-build window world-coordinates
    window_points = []
    for w in config.windows:
        if w.wall == "north":
            wx = w.position * config.width
            wy = 0.0
            normal = (0, 1)
        elif w.wall == "south":
            wx = w.position * config.width
            wy = config.length
            normal = (0, -1)
        elif w.wall == "west":
            wx = 0.0
            wy = w.position * config.length
            normal = (1, 0)
        else:  # east
            wx = config.width
            wy = w.position * config.length
            normal = (-1, 0)
        window_points.append((wx, wy, normal, w.width))

    # If no windows defined assume open sides (uniform light)
    if not window_points:
        grid = []
        for r in range(rows):
            for c in range(cols):
                cx = (c + 0.5) * config.grid_resolution
                cy = (r + 0.5) * config.grid_resolution
                grid.append({"cx": cx, "cy": cy, "light": 0.6 + random.uniform(-0.05, 0.05)})
        return grid, cols, rows

    grid = []
    for r in range(rows):
        for c in range(cols):
            cx = (c + 0.5) * config.grid_resolution
            cy = (r + 0.5) * config.grid_resolution

            light_score = 0.0
            for (wx, wy, normal, w_width) in window_points:
                dist = math.sqrt((cx - wx) ** 2 + (cy - wy) ** 2) + 0.01
                # Directional factor: how aligned is sun→window normal?
                dot = sun_dx * normal[0] + sun_dy * normal[1]
                direction_factor = max(0.0, dot)
                # Distance decay
                base = direction_factor * w_width / (1 + 0.15 * dist)
                light_score += base

            # Shadow reduction from obstacles
            for obs in config.obstacles:
                if obs.type in ("shade", "wall"):
                    ox, oy = obs.x + obs.width / 2, obs.y + obs.height / 2
                    if abs(cx - ox) < obs.width and abs(cy - oy) < obs.height:
                        light_score *= 0.2   # inside obstacle → very dark
                    else:
                        # Simple shadow cast in sun direction
                        shadow_dist = (cx - ox) * (-sun_dx) + (cy - oy) * (-sun_dy)
                        perp = abs((cx - ox) * sun_dy - (cy - oy) * sun_dx)
                        if 0 < shadow_dist < 4.0 and perp < obs.width / 2:
                            light_score *= 0.5

            grid.append({"cx": cx, "cy": cy, "light": light_score})

    # Normalise to 0–1
    max_light = max((c["light"] for c in grid), default=1.0) or 1.0
    for cell in grid:
        cell["light"] = round(cell["light"] / max_light, 4)

    return grid, cols, rows


# ─────────────────────────── K-means clustering ───────────────────────

def _kmeans(grid: list, k: int, iterations: int = 30) -> list:
    """Simple K-means on (x, y, light) feature space."""
    if not grid:
        return []

    random.seed(42)
    centroids = random.sample(grid, min(k, len(grid)))
    centroids = [{"cx": c["cx"], "cy": c["cy"], "light": c["light"]} for c in centroids]

    assignments = [0] * len(grid)

    for _ in range(iterations):
        # Assign each cell to nearest centroid
        for i, cell in enumerate(grid):
            best, best_d = 0, float("inf")
            for j, cen in enumerate(centroids):
                d = (
                    ((cell["cx"] - cen["cx"]) / 10) ** 2 +
                    ((cell["cy"] - cen["cy"]) / 10) ** 2 +
                    (cell["light"] - cen["light"]) ** 2
                )
                if d < best_d:
                    best_d, best = d, j
            assignments[i] = best

        # Recompute centroids
        for j in range(k):
            members = [grid[i] for i, a in enumerate(assignments) if a == j]
            if members:
                centroids[j] = {
                    "cx":    sum(m["cx"]    for m in members) / len(members),
                    "cy":    sum(m["cy"]    for m in members) / len(members),
                    "light": sum(m["light"] for m in members) / len(members),
                }

    return assignments


# ─────────────────────────── Main endpoint ────────────────────────────

@router.post("/analyze", response_model=AnalysisResult)
async def analyze_farm(config: FarmConfig):
    """
    Analyze greenhouse layout and return optimal sensor placement zones.

    Steps:
      1. Simulate light gradient across a 2D floor grid
      2. K-means cluster cells by (x, y, light) into target_zones groups
      3. Place one sensor at each zone centroid
      4. Return zone map + sensor coordinates for 3D visualization
    """
    grid, cols, rows = _compute_light_grid(config)

    k = min(config.target_zones, len(grid))
    assignments = _kmeans(grid, k)

    total_cells = len(grid)
    total_area  = round(config.width * config.length, 2)

    # Build per-zone stats
    zone_cells_map = {j: [] for j in range(k)}
    for i, zone_id in enumerate(assignments):
        zone_cells_map[zone_id].append(grid[i])

    sensor_positions = []
    for zone_id, cells in zone_cells_map.items():
        if not cells:
            continue
        avg_x     = sum(c["cx"] for c in cells) / len(cells)
        avg_y     = sum(c["cy"] for c in cells) / len(cells)
        avg_light = sum(c["light"] for c in cells) / len(cells)
        cov_pct   = round(100 * len(cells) / total_cells, 1)

        sensor_positions.append(SensorPosition(
            zone_id       = zone_id,
            x             = round(avg_x, 2),
            y             = round(avg_y, 2),
            height        = round(config.height * 0.4, 2),   # place at 40% height (root level)
            zone_color    = ZONE_COLORS[zone_id % len(ZONE_COLORS)],
            cell_count    = len(cells),
            avg_light_score = round(avg_light, 3),
            coverage_pct  = cov_pct,
        ))

    # Grid cells for 3D coloring
    grid_cells = [
        ZoneCell(
            x=grid[i]["cx"],
            y=grid[i]["cy"],
            zone_id=assignments[i],
            light_score=grid[i]["light"],
        )
        for i in range(len(grid))
    ]

    return AnalysisResult(
        zones             = len(sensor_positions),
        total_area        = total_area,
        sensor_positions  = sensor_positions,
        grid_cells        = grid_cells,
        plant_rows        = config.plant_rows,
        farm_width        = config.width,
        farm_length       = config.length,
        farm_height       = config.height,
        coverage_summary  = (
            f"{len(sensor_positions)} sensor units cover {total_area}m² "
            f"({total_cells} grid cells at {config.grid_resolution}m resolution)"
        ),
    )
