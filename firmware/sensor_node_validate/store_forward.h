/* Record layout for the store-and-forward buffer (store_forward.ino).
 *
 * WHY THIS IS A HEADER and not at the top of store_forward.ino: Arduino writes
 * a prototype for every function in every tab and puts them all at the top of
 * the merged sketch, ABOVE anything a later tab defines. A helper taking a
 * BufRec& would then be declared before BufRec exists and the sketch would not
 * compile. A header included from the main sketch is seen first.
 *
 * Fixed size and written as raw bytes, so the Nth reading sits at N*40 and a
 * record can be found without parsing anything before it. Values are stored
 * as the scaled integers the live reading was ROUNDED to (0.1 C, 0.1 %, 1 lux,
 * 0.001 kPa), so the JSON rebuilt at upload time carries exactly the numbers
 * the node would have sent live - a float round trip would turn 27.3 into
 * 27.29999924. -999 (the failed-sensor sentinel) survives the scaling exactly:
 * -9990 / 10.0 and -999000 / 1000.0 are both -999.0.
 */
#pragma once
#include <stdint.h>

struct BufRec {          // 40 bytes, no padding (checked below)
  uint64_t ms;           //  0  when the reading was taken: epoch ms, device clock
  uint32_t seq;          //  8  1, 2, 3 ... never reused. The upload pointer counts these
  uint32_t sect;         // 12  FNV-1a of "tenant/house/section" it was recorded FOR
  int32_t  lux;          // 16  rounded lux, or -999
  int32_t  vpd1000;      // 20  kPa x1000, or -999000
  int16_t  t10;          // 24  C x10, or -9990
  int16_t  rh10;         // 26  % x10, or -9990
  int16_t  soil10;       // 28  sampleMoisture % x10, or -9990
  int16_t  soilRaw;      // 30  ADC counts, as sent live
  uint8_t  flags;        // 32  bit0 = sensorFault
  uint8_t  ver;          // 33  layout version - a record from other firmware is refused
  uint16_t reserved;     // 34  zero
  uint32_t check;        // 36  FNV-1a of bytes 0..35
};
static_assert(sizeof(BufRec) == 40, "BufRec must stay 40 bytes: the file is indexed by N*40");

#define BUF_REC_VER 1
