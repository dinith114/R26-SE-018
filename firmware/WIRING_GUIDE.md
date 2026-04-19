# Hardware Wiring Guide
## NodeMCU ESP32 + DHT22 + BH1750 + Soil Moisture Sensor

![Wiring Diagram Reference](C:/Users/MSII/.gemini/antigravity/brain/4cd2827a-a1a3-4666-b702-c93067099bbe/artifacts/wiring_diagram.png)

> **Note:** The generated diagram is a reference. Follow the pin table below for exact connections.

---

## Step 1: Identify Your ESP32 Pins

Your NodeMCU ESP32 has pins labeled on the board. The key pins you need:

| ESP32 Pin | Label on Board | Purpose |
|---|---|---|
| **3.3V** | 3V3 | Power for all sensors |
| **GND** | GND | Ground (use multiple GND pins) |
| **GPIO 4** | D4 / G4 | DHT22 data |
| **GPIO 21** | D21 / G21 | I2C SDA (BH1750) |
| **GPIO 22** | D22 / G22 | I2C SCL (BH1750) |
| **GPIO 34** | D34 / G34 | Soil moisture analog input |

---

## Step 2: Wire Each Sensor

### Sensor 1: DHT22 (Temperature & Humidity)

The DHT22 has **3 or 4 pins** (if 4-pin module, the 3rd pin is unused):

```
DHT22 Pin     -->    ESP32
---------            -----
VCC (pin 1)   -->    3.3V
DATA (pin 2)  -->    GPIO 4
NC (pin 3)    -->    (not connected)
GND (pin 4)   -->    GND
```

> **IMPORTANT:** Add a **10K ohm pull-up resistor** between VCC and DATA.
> If your DHT22 is on a breakout board module (3 pins), the pull-up resistor is usually already included on the board.

### Sensor 2: BH1750 (Light Sensor - I2C)

The BH1750 has **5 pins**:

```
BH1750 Pin    -->    ESP32
----------           -----
VCC           -->    3.3V
GND           -->    GND
SDA           -->    GPIO 21
SCL           -->    GPIO 22
ADDR          -->    (leave unconnected or GND for default address 0x23)
```

### Sensor 3: Soil Moisture Sensor

The soil moisture module has **2 parts**: the probe and the circuit board.

```
Module Pin    -->    ESP32
----------           -----
VCC           -->    3.3V (or 5V if module requires it)
GND           -->    GND
AO (analog)   -->    GPIO 34
DO (digital)  -->    (not used)
```

> **Tip:** Only use the **AO** (analog output) pin, not DO. GPIO 34 is an ADC1 channel which works even when WiFi is active.

---

## Step 3: Breadboard Layout

```
Breadboard Layout (simplified top view):

    +---[ESP32 NodeMCU]---+
    |  3V3          GND   |
    |  GPIO4        GPIO34|
    |  GPIO21       GPIO22|
    +---------------------+
       |    |         |
       |    |         |
    [DHT22] |     [BH1750]
            |
    [Soil Moisture]

Power Rails:
  - Connect 3.3V to the (+) rail on breadboard
  - Connect GND to the (-) rail on breadboard
  - All sensor VCC pins connect to (+) rail
  - All sensor GND pins connect to (-) rail
```

### Wiring Checklist

- [ ] Place ESP32 on breadboard (straddle the center gap)
- [ ] Connect 3.3V pin to (+) power rail
- [ ] Connect GND pin to (-) power rail
- [ ] **DHT22:** VCC to (+), GND to (-), DATA to GPIO 4
- [ ] **DHT22:** 10K resistor between VCC and DATA (if not on module)
- [ ] **BH1750:** VCC to (+), GND to (-), SDA to GPIO 21, SCL to GPIO 22
- [ ] **Soil Moisture:** VCC to (+), GND to (-), AO to GPIO 34
- [ ] Double-check all connections before powering on

---

## Step 4: Install Arduino IDE & Libraries

### 4.1 Install Arduino IDE
1. Download from: https://www.arduino.cc/en/software
2. Install and open

### 4.2 Add ESP32 Board Support
1. Go to **File > Preferences**
2. In "Additional Board Manager URLs", paste:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Go to **Tools > Board > Board Manager**
4. Search "**esp32**" and install "**ESP32 by Espressif Systems**"

### 4.3 Install Required Libraries
Go to **Sketch > Include Library > Manage Libraries** and install:

| Library | Author | Search Term |
|---|---|---|
| DHT sensor library | Adafruit | "DHT sensor library" |
| Adafruit Unified Sensor | Adafruit | "Adafruit Unified Sensor" |
| BH1750 | Christopher Laws | "BH1750" |

### 4.4 Select Your Board
1. **Tools > Board > ESP32 Arduino > NodeMCU-32S** (or "ESP32 Dev Module")
2. **Tools > Port > COM?** (select your ESP32's COM port)
3. **Tools > Upload Speed > 115200**

---

## Step 5: Flash the Firmware

1. Open `firmware/sensor_data_logger/sensor_data_logger.ino` in Arduino IDE
2. Update WiFi credentials (lines 40-41):
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_NAME";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   ```
3. For **testing**, change the read interval to 10 seconds (line 48):
   ```cpp
   #define READ_INTERVAL_MS  10000  // 10 seconds for testing
   ```
4. Click **Upload** (right arrow button)
5. Open **Serial Monitor** (Tools > Serial Monitor, set baud to **115200**)

---

## Step 6: Verify Sensor Readings

You should see output like this in Serial Monitor:

```
============================================
  Smart Orchid Care - Sensor Data Logger
  Vanda Orchid Watering Prediction System
============================================

[OK] DHT22 initialized on GPIO 4
[OK] BH1750 initialized on I2C
[OK] Soil Moisture on GPIO 34
[SKIP] WiFi not configured - logging to Serial only

--- DATA LOG START ---
Reading#,Timestamp_ms,Temperature_C,Humidity_Pct,Light_lux,SoilMoisture_raw,SoilMoisture_pct,HoursSinceWater
1,10023,28.5,72.3,5420.0,2847,48.1,0.00
2,20045,28.6,71.9,5380.5,2851,47.9,0.00
3,30067,28.5,72.1,5415.2,2849,48.0,0.01
```

### Troubleshooting

| Problem | Solution |
|---|---|
| DHT22 shows -999 | Check wiring. Ensure DATA is on GPIO 4. Add 10K pull-up resistor. |
| BH1750 not found | Check SDA on GPIO 21, SCL on GPIO 22. Try swapping SDA/SCL. |
| Soil moisture always 0 or 4095 | Check AO pin on GPIO 34. Try GPIO 36 if 34 doesn't work. |
| COM port not showing | Install CP2102 or CH340 USB driver (depends on your ESP32 board). |
| Upload fails | Hold the **BOOT** button on ESP32 while uploading. |

### Serial Monitor Commands

Type these in the Serial Monitor input box:

| Command | Action |
|---|---|
| `R` or `READ` | Take an immediate sensor reading with formatted output |
| `W` or `WATER` | Record that you just watered the plant (resets timer) |
| `H` or `HELP` | Show available commands |

---

## Step 7: Calibrate Soil Moisture Sensor

This is important for accurate readings:

1. **Dry reading:** Hold the sensor in air, note the raw value in Serial Monitor
2. **Wet reading:** Dip the sensor in water, note the raw value
3. Update the firmware (lines 51-52):
   ```cpp
   #define SOIL_DRY_VALUE    <your_dry_value>    // e.g., 3800
   #define SOIL_WET_VALUE    <your_wet_value>     // e.g., 1500
   ```
4. Re-upload the firmware

### For Vanda Orchids (Exposed Roots)

Since Vanda orchids have **no soil**, position the sensor like this:
- Place the moisture sensor **near the root mass** (not buried in anything)
- It will measure the **humidity/moisture in the air around the roots**
- This acts as a **root-zone proxy** rather than soil moisture
- Alternatively, wrap the sensor loosely in sphagnum moss near roots

---

## What's Next After Hardware Works?

Once you see sensor readings in Serial Monitor:

1. **Change interval back to 5 min** (`#define READ_INTERVAL_MS 300000`)
2. **Add WiFi credentials** to send data to the cloud
3. **Place sensors near your Vanda orchid** and start collecting data
4. **Copy CSV data** from Serial Monitor into a file for ML training
