# Hardware Wiring Guide
## NodeMCU ESP32 + DHT22 + BH1750 (+ relay board on the master)

This is the short version for `firmware/sensor_node_validate` (validation-2.7).
The full, illustrated guide is generated from the firmware's own pin map:
`Desktop/orchid_project/Wiring_Guide/Orchid_Sensor_Node_Wiring.pdf`
(rebuild with `Wiring_Guide/source/build_wiring.py`).

There is **no soil or tray probe**. A capacitive probe on D34 reported the
humidity tray's water level until 10 Oct 2026; it was removed because the
grower sets how long a tray fill runs in the app and the models decide when.
D34 is unused and needs nothing connected to it.

---

## Pins

| ESP32 pin | Board label | Connects to |
|---|---|---|
| 3V3 | 3V3 | VCC of the DHT22 and the BH1750 (never VIN: VIN is 5 V) |
| GND | GND | GND of both sensors |
| GPIO 4 | D4 | DHT22 DATA |
| GPIO 21 | D21 | BH1750 SDA |
| GPIO 22 | D22 | BH1750 SCL |
| GPIO 25 | D25 | Master only: relay IN1, watering pump |
| GPIO 26 | D26 | Master only: relay IN2, humidity-tray pump |
| GPIO 27 | D27 | Master only: relay IN3, reserved for a fertilizer doser (not built) |

The BH1750's ADDR pin stays unconnected (address 0x23). The relay board is
**active low**: the firmware drives every relay pin to OFF before making it an
output, so nothing switches on at boot.

## Sensor node

1. DHT22: VCC to 3V3, DATA to D4, GND to GND. The red breakout has its own
   pull-up; none is needed.
2. BH1750 (GY-302): VCC to 3V3, GND to GND, SDA to D21, SCL to D22.
3. Power from USB (a power bank on the farm).

## Master controller

The same board, plus a 4-channel relay module: IN1 to D25 (watering pump),
IN2 to D26 (tray pump), relay VCC to VIN (5 V), GND to GND. Both pumps run
from their own 12 V supply: + to each relay's COM, each NO to its pump's +,
both pumps' - back to the supply. Put a diode (for example a 1N4007) across
each pump's two wires, stripe to +.

## Flashing

```
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/sensor_node_validate
arduino-cli upload  -p COMx --fqbn esp32:esp32:esp32 firmware/sensor_node_validate
```

Add `--build-property "build.extra_flags=-DQUIET_NODE=1"` for a recording-only
node (reads every 60 s, never runs pumps). Delete `build/*_flashed.bin` before
uploading: arduino-cli otherwise diffs against it and can skip writing the new
application.

## Checking it works

On the serial monitor (115200 baud) each reading prints as

```
[READ] 31.4C  78.2%  1520 lux  vpd=0.987
```

`-999` for a sensor means it did not answer: check that sensor's wires. A
board with no BH1750 reports light as -999 and is still a working
temperature-and-humidity node.
