# Tenancy Cutover 2B — Firmware and Bench

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the sensor nodes and the browser bench to write under `/tenants/{TENANT_ID}/farm/...`, so they land where the backend now reads.

**Architecture:** `TENANT_ID` becomes a compile-time `#define` beside `HOUSE_ID` and `SECTION_ID`, and every `/farm/...` URL is built from one `FARM` constant instead of from `FB_HOST` directly — the firmware's version of the backend's chokepoint. `/devices/...` stays global and unprefixed, because a board belongs to no tenant until it is flashed with one; the announce simply starts declaring which tenant it was flashed for.

**Tech Stack:** Arduino / ESP32 core 3.3.11, `arduino-cli` bundled with the Arduino IDE, plain HTML+JS for the bench.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`

## Global Constraints

- **Nothing here is deployed on its own.** 2A (backend), 2B (this), 2C (mobile) and 2D (migration) go live together — the spec's cutover section has the ordered steps. A board flashed with `TENANT_ID` writes where only a 2A backend reads; a board not flashed writes where a 2A backend no longer looks. Either half alone takes the farm dark.
- **`/devices/...` must NOT be prefixed.** The registry is global by design: a board belongs to nobody until it is flashed. Prefixing it would hide every board from the app's own Link-a-node list.
- **The version string moves to `validation-2.0`.** It is how the backend and the bench tell a reflashed board from one still writing to the old tree, and during the cutover that distinction is the whole diagnostic.
- **`arduino-cli` is not on PATH.** It ships with the Arduino IDE at
  `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`.
- **Flash at `UploadSpeed=115200`.** The default 921600 fails part-way and leaves a partial image. This has happened on this project.
- **`compile --upload` in one command has failed mid-write here before and left a board silent.** Compile first, confirm it succeeded, then upload as a separate command.
- Commit messages: plain sentences, no `feat:`/`chore:`/`fix:` prefixes, ending with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## What actually has to change — measured, not estimated

```
/farm/... paths, all of which must gain the prefix        10
  master_queue.ino          6   acks, queue delete, running x2, stop, poll
  sensor_node_validate.ino  4   BASE and HIST, and their runtime rebuild

/devices/... paths, all of which must NOT change           8
  announce, heartbeat, ping ack, poll flags, scan x2, identify x2
```

The four in `sensor_node_validate.ino` are two pairs: the compile-time
initialisers at lines 323-324, and the rebuild at 331-332 that runs when the app
reassigns the board to a different section.

---

### Task 1: The firmware's own chokepoint

**Files:**
- Modify: `firmware/sensor_node_validate/sensor_node_validate.ino`
- Modify: `firmware/sensor_node_validate/master_queue.ino`

**Interfaces:**
- Produces: `#define TENANT_ID "t_..."` beside the other two ids, and a
  `String FARM` built once from `FB_HOST` and `TENANT_ID`. Every `/farm/...` URL
  in both files is built from `FARM`; nothing builds one from `FB_HOST` again.

- [ ] **Step 1: Add the constant and the base**

In `sensor_node_validate.ino`, in the `SET THESE` block at the top:

```cpp
// ═══════════ 1. SET THESE ═══════════
#define TENANT_ID  "t_REPLACE_ME"   // the farm this board belongs to
#define HOUSE_ID   "H1"
#define SECTION_ID "S1"          // must match a section that exists in the app
```

`TENANT_ID` goes FIRST, above the other two, because it is the outermost thing
about the board and because a reader scanning that block should meet it before
the ids it scopes.

Then, beside the existing `BASE` / `HIST` declarations near line 323:

```cpp
/* Every farm path this board writes hangs off ONE base, the firmware's version
   of the chokepoint the backend uses. Built once here so a path cannot be
   assembled from FB_HOST by hand and quietly miss the tenant - which is exactly
   how a board would end up writing to the old shared tree with nothing to show
   for it but readings nobody reads.

   /devices/... deliberately does NOT hang off this. That registry is global: a
   board belongs to no tenant until it is flashed with one, and the app's
   Link-a-node list has to see boards before they are anybody's. */
const String FARM = String(FB_HOST) + "/tenants/" TENANT_ID "/farm";
```

- [ ] **Step 2: Rewrite the four paths in the sketch**

```cpp
String BASE = FARM + "/houses/" HOUSE_ID "/sections/" SECTION_ID;
String HIST = FARM + "/history/" HOUSE_ID "/" SECTION_ID;
```

and in the reassignment rebuild:

```cpp
  BASE = FARM + "/houses/" + assignedHouse + "/sections/" + assignedSection;
  HIST = FARM + "/history/" + assignedHouse + "/" + assignedSection;
```

- [ ] **Step 3: Rewrite the six paths in `master_queue.ino`**

Every `String(FB_HOST) + "/farm/masters/" + macKey() + ...` becomes
`FARM + "/masters/" + macKey() + ...`. There are six: acks (line ~92), the queue
delete (~99), `running` twice (~115, ~125), `stop` (~140), and the queue poll
(~255). `FARM` is declared in the main sketch; Arduino concatenates the `.ino`
files in the same translation unit, so it is visible — but declare it before
first use in file order, which the main sketch already is.

- [ ] **Step 4: Declare the tenant in the announce, and bump the version**

In `announceDevice()`, add the tenant to the payload and move the version:

```cpp
  String body = "{\"mac\":\"" + macKey() +
                "\",\"ip\":\"" + WiFi.localIP().toString() +
                "\",\"rssi\":" + String(WiFi.RSSI()) +
                ",\"fw\":\"validation-2.0\"" +
                // Which farm this board was flashed for. The backend filters
                // the global registry on it, so an unflashed board carries no
                // tenant and stays claimable by anyone - which is right: it
                // belongs to nobody yet.
                ",\"tenantId\":\"" TENANT_ID "\"" +
```

The version bump matters beyond bookkeeping: during the cutover it is how
anybody can tell a reflashed board from one still writing to the old tree.

- [ ] **Step 5: Prove no farm path escaped**

Run, and expect NOTHING:

```bash
grep -n 'FB_HOST' firmware/sensor_node_validate/*.ino | grep '/farm'
```

Then confirm the devices paths did NOT change — expect eight:

```bash
grep -c 'FB_HOST) + "/devices/' firmware/sensor_node_validate/sensor_node_validate.ino
```

Put both outputs in your report. This is the check that matters: a single farm
path still built from `FB_HOST` writes to the old tree, the board looks healthy,
and the section it feeds is simply never planned.

- [ ] **Step 6: Compile — do NOT upload yet**

```
"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" \
  compile --fqbn esp32:esp32:esp32 firmware/sensor_node_validate
```

Expect success and a flash-usage line. Record it. Do not run `--upload` in the
same command: that combination has failed mid-write on this project and left a
board silent.

- [ ] **Step 7: Commit**

```bash
git add firmware/sensor_node_validate/
git commit -m "Flash the tenant into the board, so its readings land where the backend reads

Every farm path now hangs off one FARM base built from TENANT_ID, the firmware's
version of the chokepoint the backend got in 2A. Built once, so a path cannot be
assembled from FB_HOST by hand and quietly miss the tenant - a board doing that
looks perfectly healthy while the section it feeds is simply never planned.

/devices/... deliberately keeps writing to the global registry. A board belongs
to nobody until it is flashed with a tenant, and the app's Link-a-node list has
to see boards before they are anybody's. The announce just declares which farm
it was flashed for, and the backend filters on that.

validation-2.0 rather than a patch bump: during the cutover the version string
is how anyone tells a reflashed board from one still writing to the old tree.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The bench

**Files:**
- Modify: `R26-SE-018/NODE_SIMULATOR.html`

The bench exists to be indistinguishable from a real board. If it keeps writing
to `/farm/...` while the boards write to `/tenants/{t}/farm/...`, it stops
testing the app and starts testing nothing.

- [ ] **Step 1: Give it a tenant**

Add a tenant field to the header bar beside the house selector, persisted in
`localStorage` like the API key already is. Default it to empty and REFUSE to
write with no tenant set, with a log line saying so — the same rule the backend
enforces, for the same reason. A bench that silently fell back to `/farm/...`
would recreate the shared-tree bug in the one tool built to catch it.

- [ ] **Step 2: Prefix every farm path, and only those**

The bench's paths are listed in its own header comment. Every `/farm/...` gains
`/tenants/{tenant}`; `/devices/{MAC}` does not. Add the tenant to the announce
PATCH, matching the firmware.

- [ ] **Step 3: Bump `FW`**

```js
const FW = 'validation-2.0';   // must match the firmware, or the backend's
                               // legacy-window logic treats these differently
```

- [ ] **Step 4: Verify**

`node --check` the extracted script. Then, with a tenant set, confirm in the
traffic log that a reading goes to `/tenants/<t>/farm/houses/...` and the
announce still goes to `/devices/...`. Put both log lines in your report.

- [ ] **Step 5: Commit**

---

### Task 3: The reflash — a runbook, not a task to run now

**Files:**
- Create: `docs/CUTOVER_REFLASH.md`

Do NOT flash anything while writing this. The boards keep the farm alive on the
old tree until the whole cutover runs, and a board flashed early is a section
that goes dark for however long the rest takes.

- [ ] **Step 1: Write the runbook**

It must cover, for each board:

- its MAC, and which house and section it is compiled for — from
  `/devices.json` and the node-1 hardware memory
- the per-board edits before flashing: `TENANT_ID`, `HOUSE_ID`, `SECTION_ID`,
  Wi-Fi credentials, `PROBE_DRY` / `PROBE_WET` from that board's own `C`
  calibration, and `IS_MASTER` true on exactly one
- compile, confirm, then upload as separate commands, at
  `UploadSpeed=115200`
- what to see on the serial monitor before moving to the next board
- how to confirm from the app that the board is reporting under the new path

And the two things that make this recoverable:

- **Order.** The master last. It is the board that runs the pumps, so it is the
  one whose downtime matters most, and flashing it first would leave every
  routed pour dead while the others are still being done.
- **Rollback.** Keep the previous `.ino` and the previous binary. If the new
  path is wrong, a board reflashed with the old sketch rejoins the old tree —
  which is why 2D copies rather than moves the data.

- [ ] **Step 2: Commit the runbook**

---

## Definition of done for 2B

- `grep FB_HOST firmware/**/*.ino | grep /farm` returns nothing
- the eight `/devices/` paths are unchanged
- the sketch compiles clean at `esp32:esp32:esp32`
- the bench writes farm data under `/tenants/{t}/farm/...`, refuses to write
  with no tenant, and still announces to `/devices/`
- both report `validation-2.0`
- the reflash runbook exists and no board has been flashed

## Not in this plan

The mobile app (2C), the data migration and the cutover itself (2D), and closing
the Firebase rules (Stage 3). **No board is flashed until the cutover runs.**
