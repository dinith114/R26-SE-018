#!/usr/bin/env node
/**
 * BUILD PREFLIGHT  —  node preflight.js
 *
 * Checks everything `npx expo run:android` needs, BEFORE you spend ten minutes
 * on a native build that fails at the end.
 *
 * Every check reports what it actually found, not what it expects to find.
 * Nothing here is assumed: each line is a real filesystem or command probe.
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

let fail = 0, warn = 0;
const ok   = (m, d = '') => console.log(`  PASS  ${m}${d ? '   ' + d : ''}`);
const bad  = (m, d = '') => { fail++; console.log(`  FAIL  ${m}${d ? '   ' + d : ''}`); };
const soft = (m, d = '') => { warn++; console.log(`  WARN  ${m}${d ? '   ' + d : ''}`); };

const sh = (cmd) => {
  try { return execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch { return null; }
};

console.log('='.repeat(68));
console.log('  BUILD PREFLIGHT  ·  npx expo run:android');
console.log('='.repeat(68) + '\n');

/* 1 ── Java */
const java = sh('java -version 2>&1') || sh('java --version');
java ? ok('Java installed', java.split('\n')[0]) : bad('Java NOT found');

/* 2 ── Android SDK: the env var AND the folder it points at */
const sdk = process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT;
if (!sdk) {
  bad('ANDROID_HOME / ANDROID_SDK_ROOT not set');
} else if (!fs.existsSync(sdk)) {
  // this was the exact failure before: variable set, folder absent
  bad('ANDROID_HOME points at a folder that does not exist', sdk);
} else {
  ok('Android SDK folder', sdk);
  const adb = path.join(sdk, 'platform-tools', process.platform === 'win32' ? 'adb.exe' : 'adb');
  fs.existsSync(adb) ? ok('platform-tools (adb)') : bad('platform-tools MISSING (install via SDK Manager)');

  for (const [dir, label] of [['build-tools', 'build-tools'], ['platforms', 'SDK platform']]) {
    const p = path.join(sdk, dir);
    const found = fs.existsSync(p) ? fs.readdirSync(p) : [];
    found.length ? ok(label, found.join(' ')) : bad(`${label} MISSING`);
  }

  /* 3 ── a phone actually plugged in */
  const devices = sh(`"${adb}" devices`);
  if (devices) {
    const list = devices.split('\n').slice(1).filter(l => l.trim() && !l.includes('offline'));
    list.length
      ? ok('device connected', list[0].split('\t')[0])
      : soft('no device detected — plug in the phone, enable USB debugging, accept the prompt');
  } else {
    soft('could not run adb');
  }
}

/* 4 ── the projectId push genuinely requires (verified in expo-notifications source) */
let cfg = {};
try { cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'app.json'), 'utf8')).expo || {}; }
catch { bad('app.json unreadable'); }

cfg.android?.package
  ? ok('android.package', cfg.android.package)
  : bad('android.package missing — native build cannot proceed');

const projectId = cfg.extra?.eas?.projectId;
projectId
  ? ok('EAS projectId', projectId)
  : bad('EAS projectId MISSING — run `npx eas init`. Without it getExpoPushTokenAsync '
      + 'throws ERR_NOTIFICATIONS_NO_EXPERIENCE_ID and the phone will never buzz');

const hasNotif = JSON.stringify(cfg.plugins || []).includes('expo-notifications');
hasNotif ? ok('expo-notifications plugin configured') : soft('expo-notifications plugin not in app.json');

/* 5 ── the packages themselves */
for (const p of ['expo-notifications', 'expo-device', 'expo-constants']) {
  fs.existsSync(path.join(__dirname, 'node_modules', p))
    ? ok(`${p} installed`)
    : bad(`${p} NOT installed`);
}

console.log('\n' + '='.repeat(68));
if (fail === 0 && warn === 0)      console.log('  READY — run:  npx expo run:android');
else if (fail === 0)               console.log(`  READY, with ${warn} warning(s) — the build will work; `
                                             + 'fix warnings for push to reach the phone');
else                               console.log(`  NOT READY — ${fail} blocker(s) above must be fixed first`);
console.log('='.repeat(68));
process.exit(fail ? 1 : 0);
