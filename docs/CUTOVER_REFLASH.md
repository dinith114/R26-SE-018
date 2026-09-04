# Reflashing for the tenancy cutover

**Nothing here is done until the whole cutover runs.** The board keeps the farm
alive on the old `/farm/...` tree; flashed early, its section goes dark for
however long the rest of the cutover takes. This is the sheet you follow on the
day, not a task to work through now.

Read `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`
("The cutover itself") first. This document is step 4 of that list.

---

## How many boards there actually are: one

Measured from `/devices.json` on 4 September 2026, not assumed:

```
records                 26
with an assignment       8
PHYSICAL BOARDS          1
```

| MAC | What it is |
|---|---|
| `B0CBD87D254C` | **The only real board.** Assigned `H1/S8`, master for H1, both pumps on it |
| `1CC3AB…` ×24 | Virtual. `newMac()` in `NODE_SIMULATOR.html` mints every bench node with the `1CC3AB` prefix |
| `E2E000000001` | A leftover end-to-end test record |

So the reflash is **one board**. Earlier drafts of the plan assumed a fleet;
the registry says otherwise, and the difference matters: this is a ten-minute
job with one serial cable, not an afternoon.

The 24 virtual records are not reflashed — they are recreated by the bench with
a tenant, and the stale ones should be cleared with the bench's **Remove all**
first, so the app's Link-a-node list is not full of boards that stopped existing
half a day ago.

---

## Before you touch anything

- [ ] 2A (backend), 2B (firmware + bench) and 2C (mobile) are all merged
- [ ] 2D's migration has run and been verified — the new tree is serving
- [ ] `/farm/*` still exists. **2D copies, it does not move.** That copy is the
      rollback, and it is the only reason flashing is reversible
- [ ] It is **after 09:00 farm time**. The engine plans at 05:00 and waters
      06:00–09:00; a board offline inside that window misses the day
- [ ] Auto is **OFF**. The system keeps deciding and alarming, it stops acting,
      so nothing can fire while the board is out
- [ ] Keep the current `.ino` and its compiled binary. If the new path is wrong,
      the old sketch rejoins the old tree

---

## The board

`B0CBD87D254C` — NodeMCU ESP32 DevKit, 30-pin, CP2102. It is the master: both
pumps hang off it, watering on IN1/D25 (channel 1) and the tray on IN2/D26
(channel 2).

### Set these before compiling

In `firmware/sensor_node_validate/sensor_node_validate.ino`:

```cpp
#define TENANT_ID  "t_xxxxxxxxxxxx"   // from 2D's migration output
#define HOUSE_ID   "H1"
#define SECTION_ID "S8"
```

`TENANT_ID` is the id 2D minted for this farm. Copy it from the migration
output; do not retype it from memory, and do not invent one — a board flashed
with a tenant that does not exist writes into a tree nothing reads, which is
the exact failure this whole cutover is about.

Also confirm, without changing them:

- Wi-Fi SSID and password
- `PROBE_DRY` / `PROBE_WET` — this board's own values from its `C` calibration.
  They are per-probe. Flashing another board's numbers silently mis-reads the
  tray
- `IS_MASTER` true — on this board it must be, it is the only one

### Flash it

Two commands, never one. `compile --upload` has failed mid-write on this
project and left the board silent.

```bash
CLI="/c/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe"

"$CLI" compile --fqbn esp32:esp32:esp32 firmware/sensor_node_validate
```

Expect a flash-usage line around 85%. **Only if that succeeded:**

```bash
"$CLI" upload -p COM9 --fqbn esp32:esp32:esp32:UploadSpeed=115200 \
  firmware/sensor_node_validate
```

`UploadSpeed=115200` is not optional. The default 921600 fails part-way and
leaves a partial image — this has happened here.

`arduino-cli` is not on PATH; the Arduino IDE bundles the one above.

### What to see before you believe it

On the serial monitor at 115200:

- the boot banner reporting `validation-2.0` — that string is how you tell a
  reflashed board from one still on the old tree, and during the cutover it is
  the whole diagnostic
- `[WIFI]` joining and an IP
- a reading cycle with plausible temperature, humidity and lux, and
  `sensorFault: false`

Then in Firebase, the reading under the **new** path:

```
/tenants/{TENANT_ID}/farm/houses/H1/sections/S8/latest
```

and the device record still under the **global** registry, now carrying its
tenant:

```
/devices/B0CBD87D254C   →   fw "validation-2.0", tenantId "{TENANT_ID}"
```

If the reading appears under `/farm/houses/...` instead, the board was flashed
from a sketch that did not have the change. Stop and check the version string.

### Then, in the app

- [ ] the section shows a live reading, not "No reading yet"
- [ ] freshness is `live`, not `nonode`
- [ ] **Water Now for 5 seconds, and confirm the node acks it.** This is the
      only step that proves the whole path end to end: app → backend → the
      tenant-scoped queue → this board → the relay → water. Everything before
      it is inference

Nothing about the pumps has been run since the two-pump change, so this is also
the first physical confirmation that watering is on channel 1 and the tray on
channel 2. Watch which pump starts.

---

## The bench

Not a reflash, but it has to happen or the app's node list stays full of ghosts.

- [ ] Open `NODE_SIMULATOR.html`, **Remove all** — this deletes the records, not
      just the local list. 17 of the 24 virtual boards are stale
- [ ] Type the tenant id into the header field. The bench refuses every farm
      request without one, reads included
- [ ] Add boards and confirm a reading lands under
      `/tenants/{TENANT_ID}/farm/houses/...` in the traffic log

---

## If it goes wrong

- **The board is silent after upload.** A partial image. Re-run `upload` alone
  at 115200; a second plain upload has recovered this before.
- **Readings land in the old tree.** The sketch was not the changed one. Check
  the version string, recompile, re-upload.
- **Readings land nowhere.** `TENANT_ID` does not match the tenant 2D created.
  Compare against the migration output character by character.
- **Give up and go back.** Reflash the previous `.ino`, and the board rejoins
  `/farm/...`, which is still there because 2D copied. Then decide in daylight.

---

## Afterwards

Only once the board has reported under the new path, a plan has generated, and a
manual Water Now has been confirmed by an ack:

- [ ] Auto back ON
- [ ] `/farm/*` deleted — **not on the same day.** It is the rollback until you
      are sure, and there is no reason to be in a hurry about it
