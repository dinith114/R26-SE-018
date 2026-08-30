/**
 * Scoped confirmations.
 *
 * Overwatering is the failure mode this whole project exists to prevent, so a
 * dialog that triggers irrigation must always say exactly WHAT it will affect.
 * The old "Water the plants right now" dialog watered every section on the farm
 * while saying only "this waters the plants straight away".
 *
 * `confirmScoped` refuses to be vague: it takes the actual list of targets and
 * builds the sentence from it.
 */
import { Alert } from 'react-native';

/** "Section 1", "Section 1 and Section 2", "Section 1, Section 2 and 2 more" */
export function listNames(names = []) {
  const n = names.filter(Boolean);
  if (n.length === 0) return '';
  if (n.length === 1) return n[0];
  if (n.length === 2) return `${n[0]} and ${n[1]}`;
  if (n.length <= 4)  return `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`;
  return `${n.slice(0, 3).join(', ')} and ${n.length - 3} more`;
}

/** "3 sections in 2 houses" — the blast radius, in the farmer's words. */
export function describeScope(targets = []) {
  const houses = new Set(targets.map((t) => t.houseId));
  const sec = targets.length === 1 ? '1 section' : `all ${targets.length} sections`;
  if (houses.size <= 1) return sec;
  return `${sec} in ${houses.size} houses`;
}

/**
 * @param {object}   o
 * @param {string}   o.verb        e.g. 'Water' — used in the title and button
 * @param {array}    o.targets     sections this will affect (must be non-empty)
 * @param {string}   o.detail      one line about what physically happens
 * @param {string}   [o.caution]   shown in the dialog when the action is risky
 * @param {function} o.onConfirm
 */
export function confirmScoped({ verb, targets = [], detail, caution, onConfirm }) {
  if (targets.length === 0) {
    Alert.alert('Nothing to do', 'There are no sections set up yet.');
    return;
  }

  const scope = describeScope(targets);
  const names = listNames(targets.map((t) => t.meta?.name || t.sectionId));

  const body = [
    `This will ${verb.toLowerCase()} ${scope}:`,
    names,
    '',
    detail,
    caution ? `\n⚠️  ${caution}` : '',
  ].filter((x) => x !== null && x !== undefined).join('\n').trim();

  Alert.alert(
    `${verb} ${scope}?`,
    body,
    [
      { text: 'Cancel', style: 'cancel' },
      { text: `Yes, ${verb.toLowerCase()} ${scope}`, style: caution ? 'destructive' : 'default',
        onPress: onConfirm },
    ],
  );
}

export default confirmScoped;
