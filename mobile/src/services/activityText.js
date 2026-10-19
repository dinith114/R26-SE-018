/**
 * What the live status strip says about one pour, and how often to ask again.
 *
 * Pure: no React, no network. The server (GET /activity) says what state each
 * pour is in; this turns that into the words and the bar, counting the seconds
 * down locally between polls from the controller's own figure.
 */

export const ACTIVE = new Set(['running', 'waiting', 'sending']);
export const POLL_ACTIVE_MS = 4000;
export const POLL_IDLE_MS = 30000;

/** Ask again soon while something is moving, rarely otherwise. */
export function pollMs(items) {
  return (items || []).some((i) => ACTIVE.has(i && i.state)) ? POLL_ACTIVE_MS : POLL_IDLE_MS;
}

/** The pours that touch this house, or this one section of it. */
export function forPlace(items, houseId, sectionId) {
  return (items || []).filter((i) => i
    && (!houseId || i.houseId === houseId)
    && (!sectionId || (i.sectionIds || []).includes(sectionId)));
}

/* On a section's own screen the section is obvious, so only a whole-house run
   is worth naming there; elsewhere the house and the section(s) are. */
function where(item, sectionId) {
  const names = item.sectionNames || item.sectionIds || [];
  const many = names.length > 1 ? `${names.length} sections, one run` : '';
  if (sectionId) return many;
  return [item.houseName, many || names[0]].filter(Boolean).join(' · ');
}

function ago(sec) {
  if (sec == null) return '';
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  return `${m} min ago`;
}

/**
 * { title, sub, tone, icon, progress (0..1 or null), remaining, canStop }
 *
 * `elapsed` is seconds since the server answered, so a running countdown keeps
 * moving between polls without the phone inventing when the pour started.
 */
export function describe(item, { elapsed = 0, sectionId = null, nowSec = null } = {}) {
  const tray = item.action === 'tray';
  const who = item.by === 'auto' ? 'automatic' : item.by === 'fallback' ? 'without the cloud' : 'started by hand';
  const place = where(item, sectionId);
  const icon = tray ? 'layers-outline' : 'water-outline';
  const dur = Number(item.durationSec) || 0;

  if (item.state === 'running') {
    const left = item.remainingSec == null ? null : Math.max(0, Math.round(item.remainingSec - elapsed));
    return {
      title: `${tray ? 'Filling the tray' : 'Watering'}${place ? ` · ${place}` : ''}`,
      sub: `${left == null ? 'running' : `${left} s left`} · ${who}`,
      tone: 'info', icon, remaining: left, canStop: true,
      progress: left == null || !dur ? null : Math.min(1, Math.max(0, (dur - left) / dur)),
    };
  }
  if (item.state === 'waiting' || item.state === 'sending') {
    return {
      title: `${item.state === 'sending' ? 'Sending to the controller' : 'Waiting for the controller'}${place ? ` · ${place}` : ''}`,
      sub: `${dur} s ${tray ? 'tray fill' : 'watering'} · ${who}`,
      tone: 'info', icon: 'time-outline', remaining: null, canStop: false, progress: null,
    };
  }
  const since = nowSec != null && item.endedAtSec ? nowSec - item.endedAtSec + elapsed : null;
  if (item.state === 'done') {
    return {
      title: `${tray ? 'Tray filled' : 'Watered'}${place ? ` · ${place}` : ''}`,
      sub: `${item.ranSec != null ? item.ranSec : dur} s · finished ${ago(since)}`.trim(),
      tone: 'success', icon: 'checkmark-circle-outline', remaining: null, canStop: false, progress: null,
    };
  }
  if (item.state === 'stopped') {
    return {
      title: `Stopped early${place ? ` · ${place}` : ''}`,
      sub: `ran ${item.ranSec || 0} of ${dur} s`,
      tone: 'warning', icon: 'stop-circle-outline', remaining: null, canStop: false, progress: null,
    };
  }
  if (item.state === 'refused') {
    return {
      title: `Not ${tray ? 'filled' : 'watered'}${place ? ` · ${place}` : ''}`,
      sub: `the controller refused it${item.outcome ? ` (${item.outcome})` : ''}`,
      tone: 'danger', icon: 'close-circle-outline', remaining: null, canStop: false, progress: null,
    };
  }
  return {
    title: `No answer from the controller${place ? ` · ${place}` : ''}`,
    sub: 'check its power and Wi-Fi',
    tone: 'warning', icon: 'help-circle-outline', remaining: null, canStop: false, progress: null,
  };
}
