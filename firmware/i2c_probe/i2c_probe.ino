/* Find the BH1750, or prove it is not there.
 *
 * The node firmware probes I2C once, in setup(), on GPIO21/22 only. That makes
 * every diagnosis a reflash-or-reset cycle, and it cannot tell these apart:
 *
 *   - SDA and SCL swapped        (both lines still idle at 3.3 V, so a
 *                                 multimeter reads "correct" either way)
 *   - GPIO21 or GPIO22 damaged   (everything measures fine, bus never works)
 *   - sensor dead                (identical symptom to both of the above)
 *
 * This scans FOUR configurations in a loop - two pin pairs, each way round - so
 * one flash answers all three. Move the wires; the answer appears within two
 * seconds without a reset.
 *
 * A BH1750 answers at 0x23 with ADDR floating or low, and at 0x5C with ADDR
 * high. Both are reported: "found 0x5C" is a working sensor the node firmware
 * would still miss, because it only ever looks at the default address.
 */
#include <Wire.h>

struct Combo { int sda; int scl; const char* note; };

// 32 and 33 are the only free pins on this board: 4 is the DHT22, 34 the soil
// probe (input-only), 2 the LED and a strapping pin, and 25/26/27/14/13/16/17
// are the master's relay channels. 6-11 are the flash and 34-39 cannot drive.
const Combo COMBOS[] = {
  { 21, 22, "stock wiring" },
  { 22, 21, "stock, SWAPPED" },
  { 32, 33, "alt pins" },
  { 33, 32, "alt pins, SWAPPED" },
};
const int N_COMBOS = sizeof(COMBOS) / sizeof(COMBOS[0]);

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println("\n\n=== I2C PROBE ===");
  Serial.println("Plug SDA/SCL into 21/22 first. If nothing is found on any");
  Serial.println("line, move them to 32/33. Watch for a line that stops");
  Serial.println("saying 'nothing'.\n");
  Serial.println("BH1750 answers at 0x23 (ADDR low/floating) or 0x5C (ADDR high).");
  Serial.println("ADDR measured near 3.3 V means 0x5C, which the node firmware");
  Serial.println("does not look for.\n");
}

/* One pass over one pin pair. Returns how many devices answered.
 *
 * A fresh Wire.begin() per combo, and Wire.end() after, because leaving a bus
 * driven on the previous pair would let the pull-ups on one pair hold the other
 * high and report a phantom device.
 */
int scanOn(int sda, int scl) {
  Wire.begin(sda, scl, 100000UL);          // 100 kHz: slow and forgiving
  delay(30);

  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      if (found == 0) Serial.print(" ->");
      Serial.printf(" 0x%02X", addr);
      found++;
    }
  }
  Wire.end();
  return found;
}

void loop() {
  for (int i = 0; i < N_COMBOS; i++) {
    const Combo& c = COMBOS[i];
    Serial.printf("SDA=%-2d SCL=%-2d  %-18s", c.sda, c.scl, c.note);
    int n = scanOn(c.sda, c.scl);
    if (n == 0) Serial.print(" -> nothing");
    else if (n > 4) Serial.print("   (many hits = both lines floating, not real)");
    Serial.println();
  }
  Serial.println("---");
  delay(1500);
}
