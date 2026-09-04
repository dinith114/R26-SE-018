/**
 * Who may do what. ONE statement of it, and not the one that matters.
 *
 * The server is the control: every action below is behind require_role, and a
 * viewer who somehow reaches an admin endpoint gets a 403 whatever this file
 * says. What this file does is stop the app OFFERING a button that would only
 * ever fail - which is a courtesy, not a security boundary. Do not let a check
 * against this map become the only thing between somebody and a pump.
 *
 * GENERATED FROM THE SERVER, not written by hand. Each entry was read off the
 * require_role dependency of the route that careV2.js calls for that action.
 * backend/tests/test_mobile_perms_match_server.py re-derives the whole map on
 * every CI run and fails if it and the server have drifted apart, so an added
 * route or a changed guard shows up as a red test rather than as a button that
 * 403s in somebody's hand.
 *
 * Roles are exactly these three strings, lowercase, as stamped into the
 * Firebase custom claims by the backend: admin, operator, viewer.
 */

export const ROLES = ['admin', 'operator', 'viewer'];

export const PERMS = {

  /* ---- admin only ---- */
  addHouse:            ['admin'],
  addSection:          ['admin'],
  analyzePlacement:    ['admin'],
  applyPlacement:      ['admin'],
  assignDevice:        ['admin'],
  deleteHouse:         ['admin'],
  deleteSection:       ['admin'],
  editHouse:           ['admin'],
  renameFarm:          ['admin'],
  renameHouse:         ['admin'],
  renameSection:       ['admin'],
  setAutoMode:         ['admin'],
  setDeviceInterval:   ['admin'],
  setFarmLocation:     ['admin'],
  setHouseDimensions:  ['admin'],
  setHouseMaster:      ['admin'],
  setLifecycle:        ['admin'],
  setMode:             ['admin'],
  setModeAll:          ['admin'],
  setNodeWifi:         ['admin'],
  setSectionDurations: ['admin'],
  setSectionOverride:  ['admin'],
  setSectionPosition:  ['admin'],
  setupFarm:           ['admin'],
  unassignDevice:      ['admin'],
  updateSection:       ['admin'],

  /* ---- admin and operator - the day-to-day actions ---- */
  ackAlarm:          ['admin', 'operator'],
  fertilizeSection:  ['admin', 'operator'],
  fillTray:          ['admin', 'operator'],
  identifyDevice:    ['admin', 'operator'],
  pingDevice:        ['admin', 'operator'],
  planAll:           ['admin', 'operator'],
  planSection:       ['admin', 'operator'],
  requestDeviceScan: ['admin', 'operator'],
  stopSection:       ['admin', 'operator'],
  trayCheck:         ['admin', 'operator'],
  trayCheckAll:      ['admin', 'operator'],
  waterSection:      ['admin', 'operator'],

  /* ---- anyone signed in ---- */
  getAlarms:            ['admin', 'operator', 'viewer'],
  getAlerts:            ['admin', 'operator', 'viewer'],
  getAutoMode:          ['admin', 'operator', 'viewer'],
  getCalibration:       ['admin', 'operator', 'viewer'],
  getCommandStatus:     ['admin', 'operator', 'viewer'],
  getDeviceScan:        ['admin', 'operator', 'viewer'],
  getDevices:           ['admin', 'operator', 'viewer'],
  getEngine:            ['admin', 'operator', 'viewer'],
  getHistory:           ['admin', 'operator', 'viewer'],
  getHouse:             ['admin', 'operator', 'viewer'],
  getModelInfo:         ['admin', 'operator', 'viewer'],
  getOverview:          ['admin', 'operator', 'viewer'],
  getPingResult:        ['admin', 'operator', 'viewer'],
  getSectionDevice:     ['admin', 'operator', 'viewer'],
  getSectionEvents:     ['admin', 'operator', 'viewer'],
  getUnassignedDevices: ['admin', 'operator', 'viewer'],
  registerPushToken:    ['admin', 'operator', 'viewer'],
};

/**
 * Defaults to admin-only for an unknown action, on purpose.
 *
 * An action nobody remembered to add here should be hidden from a viewer, not
 * shown to one. The failure of a missing entry is then a control an admin can
 * still reach and an operator cannot - visible, and reported - rather than a
 * viewer being offered something the server will refuse.
 */
export function can(role, action) {
  if (!role) return false;
  return (PERMS[action] || ['admin']).includes(role);
}
