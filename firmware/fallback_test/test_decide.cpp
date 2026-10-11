// PC test of the offline fallback's decision (sensor_node_validate/fallback_decide.h).
// Outside the sketch folder on purpose: Arduino would compile it into the firmware.
//
//   python -m ziglang c++ -std=c++17 test_decide.cpp -o test_decide.exe && test_decide.exe
//
// `long` is 32-bit here (Windows) exactly as on the ESP32, so epoch arithmetic
// that would overflow there overflows here too.
#include <cstdio>
#include "../sensor_node_validate/fallback_decide.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

// 11 Oct 2026 00:00 at UTC+5:30, as the backend computes dayStartSec
static const long DAY = 1791657000L;
static const long AFTER = 25 * 60, UNTIL = 120 * 60;
static long at(int h, int m) { return DAY + h * 3600L + m * 60L; }

int main() {
  bool y = false;
  FbEntry one[] = {{at(7, 10), 60, 1, 0}};

  // the engine's own window: nothing until 25 minutes after the planned minute
  CHECK(fbDecide(at(7, 10), DAY, AFTER, UNTIL, one, 1, &y) == -1);
  CHECK(fbDecide(at(7, 34), DAY, AFTER, UNTIL, one, 1, &y) == -1);
  CHECK(fbDecide(at(7, 35), DAY, AFTER, UNTIL, one, 1, &y) == 0 && !y);
  // ...and never more than two hours after it
  CHECK(fbDecide(at(9, 10), DAY, AFTER, UNTIL, one, 1, &y) == 0);
  CHECK(fbDecide(at(9, 11), DAY, AFTER, UNTIL, one, 1, &y) == -1);

  // watered today already, by the queue or the fallback: never again today
  FbEntry done[] = {{at(7, 10), 60, 1, at(6, 50)}};
  CHECK(fbDecide(at(7, 40), DAY, AFTER, UNTIL, done, 1, &y) == -1);
  // watered yesterday: today is still due
  FbEntry old[] = {{at(7, 10), 60, 1, at(7, 0) - 86400L}};
  CHECK(fbDecide(at(7, 40), DAY, AFTER, UNTIL, old, 1, &y) == 0);

  // today's plan never arrived: yesterday's, moved to today
  CHECK(fbDecide(at(7, 40) + 86400L, DAY, AFTER, UNTIL, one, 1, &y) == 0 && y);
  // ...but watered today by then: no
  FbEntry doneTomorrow[] = {{at(7, 10), 60, 1, at(6, 50) + 86400L}};
  CHECK(fbDecide(at(7, 40) + 86400L, DAY, AFTER, UNTIL, doneTomorrow, 1, &y) == -1);
  // a plan two days old is never used
  CHECK(fbDecide(at(7, 40) + 2 * 86400L, DAY, AFTER, UNTIL, one, 1, &y) == -1);
  // a plan from the future (clock behind) is not used
  CHECK(fbDecide(DAY - 60, DAY, AFTER, UNTIL, one, 1, &y) == -1);

  // bad rows are skipped, never poured
  FbEntry bad[] = {{at(7, 10), 60, 0, 0}, {at(7, 10), 60, 9, 0}, {at(7, 10), 0, 1, 0},
                   {0, 60, 1, 0}};
  CHECK(fbDecide(at(7, 40), DAY, AFTER, UNTIL, bad, 4, &y) == -1);
  // a misconfigured window, or no plan date, does nothing
  CHECK(fbDecide(at(7, 40), DAY, UNTIL, AFTER, one, 1, &y) == -1);
  CHECK(fbDecide(at(7, 40), 0, AFTER, UNTIL, one, 1, &y) == -1);

  // several sections: the first due is taken, then the next once it is done
  FbEntry two[] = {{at(6, 30), 60, 1, 0}, {at(6, 40), 50, 1, 0}};
  CHECK(fbDecide(at(7, 10), DAY, AFTER, UNTIL, two, 2, &y) == 0);
  two[0].lastRun = at(7, 10);
  CHECK(fbDecide(at(7, 11), DAY, AFTER, UNTIL, two, 2, &y) == 1);
  two[1].lastRun = at(7, 12);
  CHECK(fbDecide(at(7, 13), DAY, AFTER, UNTIL, two, 2, &y) == -1);

  std::printf(failures ? "%d FAILED\n" : "all passed\n", failures);
  return failures ? 1 : 0;
}
