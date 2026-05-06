# IoT - Device Firmware & Edge Scripts

## Structure

```
iot/
├── raspberry_pi/     # Raspberry Pi camera + image processing scripts
│   ├── capture.py    # Image capture script
│   └── upload.py     # Upload images to Firebase/cloud
│
└── esp32/            # ESP32 sensor firmware
    └── sensor_reader/ # Arduino/PlatformIO project
```

## Hardware

| Device | Purpose |
|--------|---------|
| Raspberry Pi Zero 2W | Edge image processing, camera control |
| Raspberry Pi Camera Module | Captures orchid flower images |
| ESP32 Microcontroller | Reads DHT22 sensor data, sends to cloud via WiFi |
| DHT22 Sensor | Temperature & humidity monitoring |
