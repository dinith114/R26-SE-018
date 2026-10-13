# CLAUDE.md — AI Assistant Rules for R26-SE-018

This file gives Claude (and any AI assistant) full context about this project so every
conversation starts with accurate knowledge. Read this before touching any code.

---

## ⚠️ Current architecture (August 2026) — read this first

Three things changed that invalidate parts of the older text below.

### 1. There is now an automation ENGINE
`backend/app/api/routes/automation.py` runs a background loop (60 s tick, plain
asyncio, no new dependency). Before it existed, the models decided correctly but
**nothing ever ran them** — the tray check and the watering plan were reachable
only through HTTP endpoints, and the only caller was a button in the app.

It supplies the two missing halves:
- **a clock** — plan at dawn, trays every 15 min, watering checked every minute
- **the watering link** — turns "06:07 for 104 s" into a real `waterCommand`.
  This existed *nowhere* before: `_plan_section` produced a plan and stopped.

### 2. ONE Auto switch, not three flags
`/farm/meta/autoMode` replaces `mode` / `trayEnabled` / `fertEnabled`, where
turning off watering silently disabled the tray too.

| | Behaviour |
|---|---|
| **Auto ON** | System waters, feeds and fills trays itself; farmer is told what happened |
| **Auto OFF** | System still watches and still decides, then **alarms** the farmer (Expo push) to act |

Auto OFF is *not* "the system does nothing" — only the hands change, not the brain.
Per-section `control.override` (`auto`/`manual`/absent) pins one section against
the farm switch.

### 3. Models are trained on REAL weather, from FIVE climate zones
420,768 real hourly records (ERA5 via Open-Meteo, 2017-2024) across Peradeniya,
Battaramulla, Anuradhapura, Jaffna and Galle → 1,402,560 section-hours,
58,436 section-days. Nuwara Eliya was downloaded but **excluded from training**:
Vanda do not grow at 4.8 °C, and including it dragged the percentile scale so low
that an ordinary lowland day scored as extreme.

This fixed the "always 06:00" problem. The synthetic climate assumed ~36 °C /
62 % RH so the stress scale saturated every day; real lowland Sri Lanka is far
milder and more humid. Watering now spreads **06:06 → 08:52** across conditions.

**Location independence.** The models never take location as a feature — only
temperature, humidity, light, VPD and exposure. Verified: 100 % of Battaramulla's
2023 conditions fall inside the trained range. Only the *stress calibration* was
ever site-specific, and it now spans five zones. Set `/farm/meta/latitude` and
`longitude` for any lowland Sri Lankan site; no retraining needed.

### 3b. The forecast uses a live weather service
The day-ahead model was blind to cloud (invisible at 05:00), capping hot-day
recall at 0.62. It now also consumes the **outdoor forecast** for the farm's
coordinates from Open-Meteo — free, no API key, fetched by the BACKEND, never by
a sensor. Peak-temperature error 1.03 → **0.44 °C**; hot-day F1 0.787 → **0.917**
(precision 0.979, recall 0.862). If the internet is down it falls back to
dawn-only and the farm keeps running.

*Train/serve skew, stated honestly:* training used ERA5 actuals as a stand-in for
the forecast, so live accuracy will be somewhat below these figures.

### 3c. Validation is out-of-time, not just random
| split | hour MAE | hour R² |
|---|---|---|
| random 80/20 | 8.5 min | 0.948 |
| **out-of-time** (train 13-22, test 23-24) | 8.5 min | **0.951** |
| **unseen** (test 2025-26, downloaded after training) | 8.5 min | **0.946** |

R² moves −0.004 on years never seen, so the model learned the relationship rather
than memorising days.

### 3d. Fertilizer is a RULE, not a learned model
Its F1 of 1.0 is not a machine-learning result: the label is a deterministic
function of the inputs (`days_since >= schedule_days[stage]`), so the classifier
reproduces a lookup table the code already holds. **Report it as an encoded
fertilisation schedule.** It is kept in classifier form so it can be retrained on
real observed feeding decisions once a season of records exists.

**Scope note for the report:** the *weather* is real; the outdoor→shade-house
conversion in `fetch_real_weather.to_shadehouse()` is modelled (+3.5 °C at full
sun, +7 % RH, 45 % light transmission) and still needs validating against the
real sensors.

### Also changed
- **History moved** to `/farm/history/{h}/{s}`, out of the section subtree.
  `/farm/houses.json` went 1,063 KB → 7.5 KB; `/overview` 4.1 s → 2.0 s;
  `/plan-all` 19.3 s → 5.0 s. **Re-flash any node from current firmware.**
- **New model:** day-ahead forecast (`forecast_v2.pkl`) predicts today's hourly
  temp/RH from the dawn reading, used to top up trays 1–4 h *before* predicted
  heat. Used only to act earlier, never to skip an action (recall ≈ 0.62).
- **Tray fill/no-fill is now the model's decision**, not a 60 % threshold. One
  hard ceiling remains at 80 % RH — the model mispredicts in that corner.

---

## Project Identity

| Field | Value |
|-------|-------|
| Project ID | R26-SE-018 |
| Title | AI-Powered Smart Orchid Care System |
| Component | 3 — Smart Watering & Automated Fertilization |
| Student | Vithanage P V P M · IT22062642 |
| Institution | SLIIT (Sri Lanka Institute of Information Technology) |
| Stack | React Native (Expo SDK 54) · FastAPI (Python 3.13) · Firebase RTDB · scikit-learn · TensorFlow |

---

## Repo Layout

```
R26-SE-018/
├── backend/
│   ├── app/
│   │   ├── main.py                          # FastAPI entry — all routers registered here
│   │   └── api/routes/
│   │       ├── smart_watering.py            # RF watering + CNN fusion + Firebase sync
│   │       ├── hybrid_pollination.py        # Teammate Component 4
│   │       ├── smart_care_v2.py             # v2 API — what the app actually uses
│   │       ├── automation.py                # the engine: 60 s tick, plan/tray/water
│   │       ├── spatial_service.py           # Phase 2 — kriging for unmonitored zones
│   │       ├── house_planner.py             # Phase 1 — sensor placement + validation
│   │       ├── disease_detection.py         # Stub — Component 1
│   │       └── growth_stage.py              # Stub — Component 2
│   └── requirements.txt
├── mobile/
│   ├── src/
│   │   ├── screens/
│   │   │   ├── SplashScreen.js              # Animated orchid bloom (all useNativeDriver:false)
│   │   │   ├── HomeScreen.js                # Dashboard — live Firebase + quick nav
│   │   │   ├── WateringScreen.js            # Irrigation + fertilizer tabs, ML banner
│   │   │   ├── HousePlannerScreen.js        # Plan a house: placement + table + create
│   │   │   ├── SectionDetailScreen.js       # Now / History / Setup for one section
│   │   │   ├── FarmSetupScreen.js           # Manual house + section creation
│   │   │   ├── DiseaseDetectionScreen.js
│   │   │   ├── GrowthStageScreen.js
│   │   │   ├── HybridPollinationScreen.js
│   │   │   ├── NotificationsScreen.js
│   │   │   └── SettingsScreen.js
│   │   ├── navigation/
│   │   │   └── AppNavigator.js              # Tabs + stack (all Farm screens registered)
│   │   ├── components/
│   │   │   ├── ScreenHeader.js
│   │   │   ├── SensorCard.js
│   │   │   └── PredictionBanner.js
│   │   ├── config/
│   │   │   ├── firebase.js                  # Firebase init
│   │   │   └── theme.js                     # COLORS, FONT, SPACE, RADIUS, SHADOW
│   │   └── services/api.js                  # BASE_URL — update IP when network changes
├── ml_pipeline/
│   ├── generate_synthetic_data.py
│   ├── ml_training_pipeline.py
│   ├── seed_firebase.py
│   ├── synthetic_orchid_data.csv
│   └── results/
│       ├── best_model.pkl                   # RF + DT bundle
│       └── visual_hydration_model.keras     # MobileNetV2 CNN
├── firmware/
│   └── (ESP32 / NodeMCU Arduino sketches)
├── CLAUDE.md                                # This file
└── FARM_PLANNER_V2_PLAN.md                  # Design doc for Farm Planner v2
```

---

## How to Run

### Backend
```powershell
# MUST use Python 3.13 full path — TensorFlow 2.20.0 only on 3.13
cd R26-SE-018\backend
C:\Users\MSII\AppData\Local\Programs\Python\Python313\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# --host 0.0.0.0 is REQUIRED for the phone to connect over Wi-Fi/hotspot
# Swagger UI: http://127.0.0.1:8000/docs
```

### Mobile App
```powershell
cd R26-SE-018\mobile
npx expo start --android
# Phone + PC must be on the same Wi-Fi network
# Check PC IP: ipconfig → Wi-Fi IPv4 address
# Update BASE_URL in every Farm screen AND src/services/api.js to match PC IP
```

### Backend address — ONE place
`src/config/backend.js`. It used to be copied into ten files, and moving the
laptop meant editing all ten; missing one produced a single screen failing
silently while everything else worked.

```javascript
const HOST = 'https://orchidfarm.duckdns.org';   // the Contabo VPS
```

The API key for write endpoints lives in `src/config/secret.js`, which is
**gitignored** — this repository is public, and the first key was published to
the world before that was noticed. See the hosting memory file.

### Windows Firewall (one-time, run as Admin)
```powershell
netsh advfirewall firewall add rule name="Uvicorn 8000" dir=in action=allow protocol=TCP localport=8000
```

---

## Firebase Schema

**v2 layout — farm → houses → sections.** A *section* is one microclimate zone
and has exactly one device.

```
/farm/
├── meta/                          { farmName, ownerName, version: 2 }
└── houses/{houseId}/              e.g. H1
    ├── meta/                      { name, type, plantCount, sectionCount }
    └── sections/{sectionId}/      e.g. S1  → deviceId "H1-S1"
        ├── meta/                  { name, label, growthStage, lightExposure }
        ├── latest/                { temperature, humidity, light, vpd,
        │                            sampleMoisture, timestamp }   ← device writes
        ├── plan/                  { waterTime, durationSec, secondSession,
        │                            secondTime, reason }          ← ML writes
        ├── tray/                  { status: ok|topup|fill|cooldown, fillSeconds,
        │                            hoursSinceFill, trayAtLimit, lastFillTs }
        ├── fertilizer/            { daysSince }
        └── control/               ← the device POLLS this
            ├── override           "auto" | "manual" | absent (absent = follow farm)
            ├── trayEnabled        bool  (per-section tray opt-out)
            ├── waterCommand/      { requested, durationSec, withFertilizer }
            └── trayCommand/       { requested, fillSeconds }
```

**Important:** `-999` in any reading means that sensor failed. The backend
clamps it (and any physically impossible value) to a training-range default
before inference — see `_clean()` in `smart_care_v2.py`.

**Time base:** all time reasoning (e.g. the tray cooldown) uses the **device
clock** — the `timestamp` in the reading — not the server clock. That keeps a
drifting device self-consistent and makes the farm simulator behave correctly
at any speed.

*Legacy v1 paths `/latest`, `/prediction`, `/history` still exist at the root
and are written by the old firmware, but nothing in the v2 app reads them.*

---

## API Routes

### Core (smart_watering.py)
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/` | Project info |
| GET  | `/health` | Health check |
| POST | `/api/v1/watering/predict` | RF + DT sensor prediction |
| POST | `/api/v1/watering/image-predict` | CNN visual + sensor fusion |
| GET  | `/api/v1/watering/sensor-status` | Latest Firebase reading |

### House Planner (house_planner.py)
Prefix `/api/v2/care/houses`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/plan` | Sensor placement for a house that does not exist yet. Body `{width, length, maxSensors}`. Returns positions **plus** the comparison table |

Replaced `farm_planner.py` and `farm_scan.py`, both deleted 29 Aug 2026. See
"House Planner" below for why.

### v2 — Smart Care (smart_care_v2.py)  ← **what the app actually uses**
Prefix `/api/v2/care`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/setup` | First-run wizard: farm → houses → sections |
| GET  | `/overview` | Everything the dashboard needs |
| POST | `/houses` · `/houses/{h}/sections` | Add later |
| PUT/DELETE | `/houses/{h}` · `/houses/{h}/sections/{s}` | Edit / remove |
| POST | `/plan-all` · `/houses/{h}/sections/{s}/plan` | Today's watering plan |
| POST | `/tray-check-all` · `/…/tray-check` | Humidity decision (**auto-issues the fill command in auto mode**) |
| POST | `/…/water` · `/…/tray-fill` | Manual control |
| PUT  | `/…/mode` | auto / manual, tray on-off |
| GET  | `/…/history?points=48` | Down-sampled series for charts |
| GET  | `/alerts` | Prioritised notifications (urgent → action → info) |
| GET  | `/model-info` | Metrics — for the About screen and the viva |

### Teammate (hybrid_pollination.py)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/pollination/assess` | Pollination suitability from image |

---

## House Planner — where the sensors go

Phase 1 of the placement work. Phase 2 (`spatial_service.py`) estimates the
sections that have no node **from** the ones that do; this decides where those
nodes should go in the first place, before any hardware exists.

### What replaced what, and why

`farm_planner.py` and `farm_scan.py` were deleted on 29 Aug 2026 along with six
screens. They were not merely unused — they could not work:

- **Sessions lived in an in-memory dict.** Any restart destroyed a survey in
  progress, and this backend is restarted on every deploy.
- **Neither file contained a single Firebase write.** The survey produced
  recommendations, then the farmer walked to a different screen and typed
  everything in again by hand. Nothing joined the two halves.
- **`analyze_trial()` never read the readings it collected.** It asked the
  farmer for 12–48 hours per position, stored only a COUNT of the values, and
  answered from distance arithmetic (`< 3 m` → redundant, gap `> 4 m` → add).
- Photos cannot give absolute scale, so dimensions were typed in anyway.

### The flow now — one screen, and the plan IS the creation

```
Home → "Plan House" → HousePlannerScreen
  1  House: name, width, length, type
  2  Sensor budget: the most you would consider
  3  POST /api/v2/care/houses/plan
       → comparison table, one row per sensor count, tap to choose
  4  2D top-down map of the chosen positions   (plain Views, no WebView)
  5  "Create house" → POST /houses, then PUT .../position per section
```

The positions shown are the positions written to each section's `meta.x` /
`meta.y`, which is exactly what `spatial_service.py` needs. There is no step in
between for a farmer to skip or mistype.

### How placement is chosen

A candidate grid at 0.5 m spacing, 0.6 m off the walls. A microclimate field is
GENERATED from the house geometry — depth from the open edge, distance from the
side walls, sun angle — under 120 conditions, **split 60/40 into fit and
held-out**. Sensors are chosen on the fit half and scored on conditions they
never saw; scoring on the same snapshots flatters every method and flatters the
most flexible one most.

Four methods compete, all returning indices into the same candidate grid:

| Method | How |
|---|---|
| **PySensors** | `SSPOR` + `SVD` basis, QR pivoting |
| **Kriging-variance greedy** | adds the point where kriging is least certain |
| **Regular grid** | evenly spread, snapped to candidates |
| **Random** | averaged over 5 draws, not one lucky one |

**Every method is scored by ORDINARY KRIGING**, imported from
`spatial_service`, because kriging is what runs in production. A placement
cannot look good here and disappoint at runtime. Using SSPOR's own POD
reconstruction to score SSPOR would flatter it against the baselines.

### The result — and the honest headline

**PySensors does not always win.** Measured on a 10 × 14 m house:

```
  n   pysensors  krig-greedy    grid   random     winner
  3       0.759        0.778   0.337    0.724     grid
  4       0.614        0.302   0.318    0.656     kriging_greedy
  5       0.351        0.270   0.254    0.412     grid
  6       0.239        0.251   0.246    0.312     pysensors
  7       0.309        0.251   0.241    0.285     grid
  8       0.227        0.233   0.237    0.267     pysensors
```

A plain grid beats it at 3, 5 and 7 sensors; it wins at 6 and 8. Its points
cluster near the hot sunny edge and leave the back of the house thin, which is
what a POD basis does on a field dominated by one strong gradient.

**So the endpoint returns the best method PER SENSOR COUNT.** Measuring four
methods and then using a fixed one would make the table decorative — it would
show the farmer that a grid was better and then place their sensors the worse
way.

### For the viva

The contribution is **not** "we used PySensors". It is:

> a placement selector that measures candidate methods against the estimator
> that actually runs in production, on weather they were not tuned against, and
> uses whichever wins.

That is stronger than asserting a method, and it survives the obvious question
("how do you know it is the best?") because the answer is a table.

**Stated honestly:** the field is generated, not measured, so this compares
METHODS and does not claim the field matches any particular house. If a real
house has structure a smooth exponential does not capture — post shadows, door
drafts, uneven netting — PySensors would likely fare better, since that is
precisely what a POD basis is for. Making the generator more realistic is the
obvious next step, and it would be a fairer test rather than a kinder one.

### Dependency trap

`python-sensors==0.4.1`, **not** `pysensors` and **not** 0.4.3.

- The PyPI name `pysensors` is an unrelated Linux `lm-sensors` binding that
  fails to build on Windows. The Brunton-lab package installs as
  `python-sensors` and imports as `pysensors`.
- From 0.4.2 it requires `numpy>=2.0`, which collides with the `numpy==1.26.4`
  this project pins for its saved models. That conflict broke CI and, on the
  development machine, left numpy half-uninstalled and took sklearn, pandas and
  PyKrige down with it.
- It is documented for Linux and macOS only, so `house_planner` degrades to its
  kriging-variance method and says so in the response rather than failing a
  request the farmer cannot act on.

## ML Models — v2 (CURRENT)

> **v2 replaced v1 in July 2026.** v1 asked *"should we water? yes/no"* from a
> per-plant root-moisture probe. That is impractical — you cannot probe every
> plant's roots — and the farmer confirmed daily watering is mandatory anyway,
> so a yes/no model answered the wrong question.
>
> **v2 asks: WHAT TIME today, and FOR HOW LONG** — plus a second loop that keeps
> humidity up with a water tray instead of soaking the roots.

Train with:
```bash
python ml_pipeline/fetch_real_weather.py     # 105,192 real hourly records (once)
python ml_pipeline/train_on_real_data.py     # watering + tray
python ml_pipeline/build_forecast_model.py   # day-ahead forecast
```
All models are trained on **real** ERA5 weather for Peradeniya (2013-2024),
not synthetic data. The old synthetic models are kept in
`ml_pipeline/results/backup_synthetic/`.

### Loop 1 — Watering time  (`results/watering_v2.pkl`)
Three models sharing one feature set, decided at **dawn** each day:

- **Features (10):** dawn_temp, dawn_humidity, dawn_light, **dawn_vpd**,
  yest_peak_temp, yest_mean_humidity, yest_mean_vpd, season_month,
  growth_stage_enc, light_exposure
- **Watering hour** — RandomForestRegressor, MAE ≈ **8.4 min**, R² **0.952**
- **Duration (sec)** — RandomForestRegressor, MAE ≈ **2.5 s**, R² **0.964**
- **Second session** — RandomForestClassifier, **F1 0.857**

**Rule: one watering per day.** A second session is allowed *only* in extreme
heat (peak ≥36 °C and RH <50%, or VPD ≥3.0) — supported by Vanda literature
which permits twice-daily watering in extreme heat. Morning window 6–9,
second session 16–18. **Never a midday soak** (root burn).

**Key finding: VPD dominates at 0.83 feature importance.** Vapour Pressure
Deficit is the physical drying power of the air; it matters far more than
temperature or humidity alone. Strong talking point for the viva.

### Loop 2 — Humidity tray  (`results/tray_v2.pkl`)
- **Features (5):** temperature, humidity, light, vpd, hour
- **Output:** valve-open seconds. MAE ≈ **0.34 s**
- **Target band: 60–80 % RH** (Vanda ideal)
- **6-hour cooldown:** a 3 cm tray cannot dry out faster than that, so low
  humidity sooner after a fill means the *air* is dry, not the tray. Refusing
  to refill avoids a wasteful overflow loop and flags `trayAtLimit`, which is
  what justifies the extra watering session.

### Fertilizer  (`results/fertilizer_v2.pkl`)
- Vanda are heavy feeders: **weekly** in growing season, every **2–3 weeks**
  when dormant, always at **¼–½ strength**, and **always delivered with water**
  (dry roots burn). 30-10-10 Active · 10-30-20 Flowering.
- **Dormant = never fed.** Enforced by a hard guard in the backend, not left to
  the model (a model bug was caught doing exactly this).
- F1 = 1.0 — documented as a deterministic expert rule, not pattern discovery.

### Visual — MobileNetV2 CNN  (`results/visual_hydration_model.keras`)
- Trained on **real orchid farm photos** (the only real-data model)
- Repurposed in v2 from "root hydration" to **plant condition / stress check**,
  which preserves the "Multi-Modal" claim in the project title.

### Deprecated (v1, still on disk)
`best_model.pkl`, `best_fertilization_model.pkl` — the old yes/no models, and
`app/api/routes/houses.py` (v1 multi-house API). Superseded by v2; kept only
so old results in the report remain reproducible.

---

## Firmware — building and flashing

**The sketch on the board is `firmware/sensor_node_validate/`**, not
`section_node_v2`. `section_node_v2` is the older design and is kept only for
reference — flashing it would lose the heartbeat, the provisioning portal, the
command-age guard and the master queue. Current version string:
`validation-1.7`.

**Flash this board at `UploadSpeed=115200`.** The default 921600 fails part-way
through and leaves a partial image:

```
arduino-cli upload -p COM9 --fqbn esp32:esp32:esp32:UploadSpeed=115200   firmware/sensor_node_validate
```

`arduino-cli` is not on PATH; the Arduino IDE bundles one at
`C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`.

`firmware/i2c_probe/` is a diagnostic sketch that scans two pin pairs both ways
round, once a second. It exists because a multimeter cannot tell a swapped
SDA/SCL from a correct one — both lines idle at 3.3 V either way — so it is the
only cheap way to separate "wires swapped" from "GPIO damaged" from "sensor
dead".

---

Older reference sketch: `firmware/section_node_v2/section_node_v2.ino` (442 lines).
**Verified compiling** against esp32 core 3.3.11 — all three configurations:

| Configuration | Flash | Result |
|---|---|---|
| master + always-on (shipping default) | 1,071,632 B — **81%** | OK |
| non-master (`IS_MASTER false`) | 1,070,604 B — 81% | OK |
| deep-sleep (`POWER_DEEP_SLEEP`) | 1,078,556 B — 82% | OK |

RAM: 50,072 B (15%). No warnings in the sketch with `--warnings all`.

```bash
# one-time setup
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32          # ~2 GB, takes a while
arduino-cli lib install "DHT sensor library" "Adafruit Unified Sensor" "BH1750" "ArduinoJson"

# compile
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/section_node_v2

# flash (check the port with: arduino-cli board list)
arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32 firmware/section_node_v2
```

**Per-device edits before flashing:** `HOUSE_ID`, `SECTION_ID`, `IS_MASTER`
(true on **one** node only — the one wired to the pump), Wi-Fi credentials, and
`PROBE_DRY`/`PROBE_WET` from the `C` calibration command.

> **ArduinoJson v7 note:** `StaticJsonDocument<N>` was **removed** in v7 — use
> plain `JsonDocument`, which sizes itself. Code written for v6 will not compile.

---

## Testing & Simulation Tools

| Tool | What it does |
|------|--------------|
| `FARM_SIMULATOR.html` | **Digital twin.** 3D greenhouse that behaves like real hardware: pushes readings to the real Firebase on the same paths the ESP32 uses, polls for commands and executes them, models tray evaporation and humidity physics. Found 3 real bugs on its first run. Open it in a browser with the backend running. |
| `ml_pipeline/test_failure_cases.py` | 17 failure tests: `-999` sensors, offline device, dormant plant, absurd values, cooldown loop. **All passing.** |
| `ml_pipeline/validate_device_calculator.py` | **Superseded.** Validated the "1 sensor per 22 plants or 20 m²" formula, which was removed on 29 Aug 2026 — sensor count now comes from the measured placement curve. Kept so older report figures stay reproducible. |
| `backend/scripts/simulate_spatial.py` | Leave-one-out validation of the kriging, 25 layouts per node count. Caught the variogram bug that made every estimate the anchor mean. |
| `backend/scripts/sim_farm.py` | A simulated house (`HSIM`) of pretend nodes writing to the real Firebase paths, so virtual sensing can be seen working without four physical boards. `--remove` deletes it. |
| `ml_pipeline/seed_farm_v2.py` | Seeds `/farm` with the 4 real sections + 24 h of history. |

Bugs these tools caught (worth citing in the report as engineering process):
1. **Auto mode decided but never acted** — trays were correctly diagnosed as
   empty and never refilled. Would have killed plants in the field.
2. **Cooldown used server time**, not device time — broke completely under the
   accelerated simulator and would drift on real hardware.
3. **Screens never refreshed** — data froze unless you re-navigated.
4. **Zone splitting over-triggered at low drying rates** — a 0.2 %/h difference
   between two shaded spots bought an extra device for nothing.

---

## Hardware

### Sensor Node — NodeMCU ESP32
| Component | Part | Pin |
|-----------|------|-----|
| MCU | NodeMCU ESP32 (MD0245) | — |
| Temp/Humidity | DHT22/AM2302 (MD0229) | GPIO4 |
| Light | BH1750FVI (MD0250) | SDA→GPIO21, SCL→GPIO22 |
| Root Moisture | Capacitive V1.2 (MD0247) | GPIO34 ADC |

**Read interval:** 10000ms dev → 300000ms production
**Firebase push:** every reading → `/latest` + `/history/{pushId}`

### Camera Node — ESP32-CAM OV2640
- Separate device from sensor node
- FT232RL programmer: TX→UOR, RX→UOT (must swap wires)

### Cost
| Item | LKR |
|------|-----|
| NodeMCU + sensors | ~2,350 |
| ESP32-CAM | ~2,480 |
| Accessories | ~720 |
| **Core unit total** | **~5,550** |
| Receipt 1 (05/04/2026) | 6,210 |
| Receipt 2 (09/05/2026) | 1,340 |
| **Grand total spent** | **7,550** |

---

## Navigation Structure

```
NavigationContainer
└── Stack.Navigator (headerShown: false)
    ├── MainTabs (Tab.Navigator — custom tab bar)
    │   ├── Care      → WateringScreen
    │   ├── Disease   → DiseaseDetectionScreen
    │   ├── Home      → HomeScreen  (FAB centre button)
    │   ├── Hybrid    → HybridPollinationScreen
    │   └── Growth    → GrowthStageScreen
    ├── Settings      → SettingsScreen
    ├── Notifications → NotificationsScreen
    ├── FarmDashboard → FarmDashboardScreen
    ├── SectionDetail → SectionDetailScreen
    ├── FarmSetup     → FarmSetupScreen
    ├── HousePlanner  → HousePlannerScreen
    ├── Run           → RunScreen
    └── Alarm         → AlarmScreen
```

Entry to the planner: HomeScreen quick nav card "Plan House" →
`navigation.navigate('HousePlanner')`. The old FarmPlanner / FarmQuick /
FarmScan / FarmModelConfirm / FarmTrial / FarmResults / DeviceCalculator
screens were deleted on 29 Aug 2026.

---

## Key Technical Decisions

### Why synthetic training data?
Real labeled IoT data requires months of continuous logging. Synthetic data calibrated from Vanda orchid cultivation guidelines. CNN trained on real farm photos. Firebase logs live readings → pipeline ready to retrain.

### Why useNativeDriver:false in SplashScreen?
Mixing native/non-native drivers on the same node crashes the app. SplashScreen animates `height` (layout — non-native only). All animations must stay non-native.

### Why Python 3.13 for backend?
TensorFlow 2.20.0 requires Python 3.13 on this machine. Always use:
`C:\Users\MSII\AppData\Local\Programs\Python\Python313\python.exe`

### Why there is no 3D any more
The old planner loaded Three.js through a WebView on three separate screens to
draw a box with poles in it. `HousePlannerScreen` draws the same information —
a top-down rectangle with numbered dots — with plain `View`s and absolute
positioning. No WebView, no CDN, no seconds of load time. If a 3D view is ever
genuinely needed, the WebView + CDN approach still works; it was simply never
worth it here.

### Why the photo scan was removed
Photographs cannot give absolute scale without a reference object, so the old
survey asked for eight photos, ran OpenCV over them for "aspect ratio hints",
and then asked the farmer to type the dimensions in anyway. The hints changed
nothing. The planner now asks for width and length directly.

### Why expo-camera over react-native-camera?
Expo SDK 54 — use `CameraView` and `useCameraPermissions` from `expo-camera`. The old `Camera` component API is deprecated. Do not use the old API.

---

## Pending Work

### Hardware
- [ ] ESP32-CAM firmware upload (swap FT232RL TX→UOR, RX→UOT wires first)
- [ ] NodeMCU reconnect (DHT22→GPIO4, BH1750 SDA→21/SCL→22 — came loose)
- [ ] Relay + water pump wiring (physical actuation pending)
- [ ] READ_INTERVAL_MS 10000 → 300000 for production

### Software
- [ ] `mobile_temp/` folder cleanup (untracked old files, safe to delete)
- [ ] **LUXFIX** — the four-part firmware fix for the BH1750 dying and staying
      dead (I2C bus recovery, boot retry, runtime re-probe, soil range check).
      See the `luxfix-i2c-recovery-plan` memory file; say `LUXFIX` to start it.
- [ ] Make the placement field generator realistic (post shadows, door drafts)
      so PySensors gets a fair test rather than a smooth single gradient

---

## Coding Conventions

- **Theme:** Always import from `src/config/theme.js` — never hardcode colors/spacing
- **Shadows:** Use `SHADOW.sm / .md / .lg / .fab` from theme
- **API calls:** Use `BASE_URL` at top of each file — same pattern everywhere
- **Animations:** Never mix `useNativeDriver:true` and `false` on the same animated node
- **Backend:** All new routes go in `backend/app/api/routes/` and registered in `main.py`
- **No comments:** Only when the WHY is non-obvious
- **Screens:** Self-contained with StyleSheet at bottom of file
- **Camera:** Always use `CameraView` + `useCameraPermissions` from expo-camera (SDK 54)
- **3D:** Use Three.js 0.128.0 via CDN in WebView — never import three as npm for RN

---

## Team Context

| Component | Owner |
|-----------|-------|
| 1 — Disease Detection | Different student |
| 2 — Growth Stage Classification | Different student |
| **3 — Smart Watering & Fertilization** | **This repo** |
| 4 — Hybrid Pollination | Shared (hybrid_pollination.py in this backend) |

Both Component 3 and 4 routers active in `main.py`. Do not disable either.

---

## Viva Key Points

1. **Data source:** Synthetic sensor data (calibrated from farm visits + Vanda guidelines) + real orchid photos for CNN + live Firebase readings
2. **Sensor placement answer:** a measured comparison, not a formula. Four
   methods (PySensors SSPOR, kriging-variance greedy, regular grid, random) are
   scored by reconstructing held-out weather with the same ordinary kriging that
   runs in production, and the winner at the chosen sensor count is used. The
   old "1 sensor per 22 plants or 20 m²" formula is gone — it had no measurement
   behind it. **PySensors does not always win**, and saying so is the point: the
   farmer sees the table and picks the count.
3. **Why Random Forest:** Handles missing/noisy sensor data better than hardcoded thresholds; retrainable on real data as Firebase history grows
4. **NPK:** N=leaf/stem growth (30-10-10 Active stage), P=root/flower development (10-30-20 Flowering), K=overall health/immunity
5. **Fusion:** RF sensor + CNN visual agree → WATER_NOW; disagree → inspect individually
6. **Hardware cost:** ~LKR 7,550 full setup; ~LKR 5,550 core sensor+camera unit
7. **Two placement phases that compose:** Phase 1 (`house_planner.py`) decides
   where nodes go before any hardware exists; Phase 2 (`spatial_service.py`)
   estimates the sections that never get one, by ordinary kriging from the
   sections that do. Phase 1 writes `meta.x` / `meta.y`, which is exactly the
   input Phase 2 needs — so a house planned in the app starts producing
   estimates the moment its nodes come online, with no further setup.
8. **A bug worth telling:** the kriging silently returned the plain MEAN of its
   anchors for every unmonitored zone — confident, with error bars, containing
   no information. A spherical variogram fitted a 3 m range where sensors sat
   5–10 m apart, so no anchor was "near enough" to any target. The code had a
   linear fallback, but only for an exception, and returning the mean is not an
   exception. Found by simulation, not by inspection.
