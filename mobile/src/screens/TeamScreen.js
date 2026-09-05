/**
 * The people who can use this farm.
 *
 * Reachable from Settings, and the row that leads here is hidden for anyone who
 * is not an admin - but the screen guards itself as well, because an entry point
 * is easy to miss and a screen that guards itself cannot be reached the wrong
 * way.
 *
 * Two server rules are shown rather than reimplemented. The backend refuses to
 * remove or demote the last admin, and refuses self-deletion, and this screen
 * puts the server's own words on the screen instead of second-guessing them
 * locally. A local copy of a rule is a copy that drifts, and the failure would
 * be a farm nobody can administer.
 */
import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, RefreshControl, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../components/ScreenHeader';
import SelectSheet from '../components/SelectSheet';
import ConfirmSheet from '../components/ConfirmSheet';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useAuth } from '../config/auth';
import { ROLES } from '../config/perms';
import {
  getTeam, addTeamMember, setTeamRole, removeTeamMember,
} from '../services/careV2';

/* What each role means, in the farm's terms rather than the API's. Taken from
   what the server actually enforces - see config/perms.js. */
const ROLE_TEXT = {
  admin:    'Everything, including adding and removing people.',
  operator: 'Water, fill trays, answer alarms. Cannot change how the farm is set up.',
  viewer:   'Can see everything and change nothing.',
};

const ROLE_TONE = {
  admin: COLORS.primary,
  operator: COLORS.info,
  viewer: COLORS.textTertiary,
};

export default function TeamScreen({ navigation }) {
  const { email: myEmail } = useAuth();
  const [team,    setTeam]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,   setError]   = useState(null);

  const [adding,  setAdding]  = useState(false);
  const [form,    setForm]    = useState({ email: '', password: '', role: 'viewer' });
  const [saving,  setSaving]  = useState(false);
  const [rolePick, setRolePick] = useState(null);   // the member, or 'new'
  const [confirmDel, setConfirmDel] = useState(null);
  const [busyUid, setBusyUid] = useState(null);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const r = await getTeam();
      setTeam(r.users || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const submitNew = async () => {
    if (!form.email.trim() || form.password.length < 8) return;
    setSaving(true);
    try {
      await addTeamMember(form.email.trim(), form.password, form.role);
      setForm({ email: '', password: '', role: 'viewer' });
      setAdding(false);
      await load();
    } catch (e) {
      Alert.alert('Could not add that account', e.message);
    } finally {
      setSaving(false);
    }
  };

  const changeRole = async (member, role) => {
    if (role === member.role) return;
    setBusyUid(member.uid);
    try {
      await setTeamRole(member.uid, role);
      await load();
    } catch (e) {
      /* Includes "This is the only admin" - the server's rule, in the server's
         words. Duplicating that check here would give two answers to one
         question, and only one of them is the one that runs. */
      Alert.alert('Could not change that role', e.message);
    } finally {
      setBusyUid(null);
    }
  };

  const doRemove = async () => {
    const m = confirmDel;
    setConfirmDel(null);
    setBusyUid(m.uid);
    try {
      await removeTeamMember(m.uid);
      await load();
    } catch (e) {
      Alert.alert('Could not remove that account', e.message);
    } finally {
      setBusyUid(null);
    }
  };

  const canSubmit = form.email.trim().length > 3
                 && form.password.length >= 8 && !saving;

  return (
    <View style={s.container}>
      <ScreenHeader title="Team" subtitle="Who can use this farm"
        navigation={navigation} showBack showNotification={false} />

      <KeyboardAvoidingView style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={s.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing}
            onRefresh={() => load(true)} tintColor={COLORS.primary} />}>

          {loading ? (
            <ActivityIndicator style={{ marginTop: SPACE.xxl }} color={COLORS.primary} />
          ) : error ? (
            <View style={[s.card, SHADOW.sm]}>
              <Text style={s.err}>{error}</Text>
            </View>
          ) : (<>
            {(team || []).map((m) => {
              const isMe = m.email && myEmail && m.email === myEmail;
              const tone = ROLE_TONE[m.role] || COLORS.textTertiary;
              return (
                <View key={m.uid} style={[s.card, SHADOW.sm]}>
                  <View style={s.rowTop}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.email} numberOfLines={1}>
                        {m.email || m.uid}{isMe ? '  (you)' : ''}
                      </Text>
                      <Text style={[s.roleLine, { color: tone }]}>
                        {m.role}
                      </Text>
                    </View>
                    {busyUid === m.uid
                      ? <ActivityIndicator size="small" color={COLORS.primary} />
                      : null}
                  </View>
                  <Text style={s.roleDesc}>{ROLE_TEXT[m.role] || ''}</Text>

                  <View style={s.actions}>
                    <TouchableOpacity style={s.act}
                      onPress={() => setRolePick(m)} disabled={busyUid === m.uid}
                      accessibilityRole="button"
                      accessibilityLabel={`Change the role of ${m.email || m.uid}`}>
                      <Ionicons name="swap-horizontal-outline" size={15} color={COLORS.primary} />
                      <Text style={s.actTxt}>Change role</Text>
                    </TouchableOpacity>

                    {/* Removing yourself is refused by the server; not offering
                        it is kinder than explaining the refusal afterwards. */}
                    {!isMe && (
                      <TouchableOpacity style={s.actDel}
                        onPress={() => setConfirmDel(m)} disabled={busyUid === m.uid}
                        accessibilityRole="button"
                        accessibilityLabel={`Remove ${m.email || m.uid}`}>
                        <Ionicons name="person-remove-outline" size={15} color={COLORS.danger} />
                        <Text style={s.actDelTxt}>Remove</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              );
            })}

            {adding ? (
              <View style={[s.card, SHADOW.sm]}>
                <Text style={s.formTitle}>New account</Text>

                <Text style={s.label}>Email</Text>
                <TextInput style={s.input} value={form.email}
                  onChangeText={(v) => setForm({ ...form, email: v })}
                  autoCapitalize="none" autoCorrect={false}
                  keyboardType="email-address" placeholder="them@example.com"
                  placeholderTextColor={COLORS.textTertiary} editable={!saving} />

                <Text style={s.label}>First password</Text>
                <TextInput style={s.input} value={form.password}
                  onChangeText={(v) => setForm({ ...form, password: v })}
                  autoCapitalize="none" secureTextEntry
                  placeholder="At least 8 characters"
                  placeholderTextColor={COLORS.textTertiary} editable={!saving} />
                {/* Said plainly, because the alternative is somebody waiting for
                    an email that is never sent. */}
                <Text style={s.hint}>
                  No invitation email is sent. Tell them this password yourself,
                  and they can change it later.
                </Text>

                <Text style={s.label}>Can do</Text>
                <TouchableOpacity style={s.rolePick} onPress={() => setRolePick('new')}
                  accessibilityRole="button" accessibilityLabel="Choose what this account can do">
                  <Text style={[s.rolePickTxt, { color: ROLE_TONE[form.role] }]}>
                    {form.role}
                  </Text>
                  <Ionicons name="chevron-down" size={16} color={COLORS.textTertiary} />
                </TouchableOpacity>
                <Text style={s.hint}>{ROLE_TEXT[form.role]}</Text>

                <View style={s.formBtns}>
                  <TouchableOpacity style={s.cancel} onPress={() => setAdding(false)}
                    disabled={saving} accessibilityRole="button">
                    <Text style={s.cancelTxt}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={[s.save, !canSubmit && { opacity: 0.5 }]}
                    onPress={submitNew} disabled={!canSubmit} accessibilityRole="button">
                    {saving ? <ActivityIndicator size="small" color="#FFF" />
                            : <Text style={s.saveTxt}>Create</Text>}
                  </TouchableOpacity>
                </View>
              </View>
            ) : (
              <TouchableOpacity style={[s.addBtn, SHADOW.sm]} onPress={() => setAdding(true)}
                accessibilityRole="button" accessibilityLabel="Add someone to this farm">
                <Ionicons name="person-add-outline" size={18} color={COLORS.primary} />
                <Text style={s.addTxt}>Add someone</Text>
              </TouchableOpacity>
            )}
          </>)}

          <View style={{ height: 80 }} />
        </ScrollView>
      </KeyboardAvoidingView>

      <SelectSheet
        visible={rolePick != null}
        title={rolePick === 'new' ? 'What can this account do?' : 'Change role'}
        options={ROLES.map((r) => ({ key: r, label: r, sub: ROLE_TEXT[r] }))}
        value={rolePick === 'new' ? form.role : rolePick?.role}
        confirmOnSelect
        onCancel={() => setRolePick(null)}
        onConfirm={(role) => {
          const target = rolePick;
          setRolePick(null);
          if (target === 'new') setForm((f) => ({ ...f, role }));
          else if (target) confirmRoleChange(target, role);
        }} />

      <ConfirmSheet
        visible={confirmDel != null}
        title={`Remove ${confirmDel?.email || ''}?`}
        body={'They will lose access to this farm immediately and will be signed '
            + 'out. This does not delete any farm data.'}
        confirmLabel="Remove"
        destructive
        onCancel={() => setConfirmDel(null)}
        onConfirm={doRemove} />
    </View>
  );

  /* Declared after the return on purpose: it is only ever called from the sheet
     above, and hoisting keeps the render tree readable. */
  function confirmRoleChange(member, role) {
    Alert.alert(
      `Make ${member.email || 'this account'} ${role}?`,
      /* The server revokes their refresh tokens on a role change, so this is
         not a warning about what might happen - it is what will. */
      'They will be signed out and will need to sign in again.\n\n'
      + `${role}: ${ROLE_TEXT[role]}`,
      [{ text: 'Cancel', style: 'cancel' },
       { text: 'Change', onPress: () => changeRole(member, role) }],
    );
  }
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.lg, gap: SPACE.md },
  card: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
    padding: SPACE.lg, gap: SPACE.xs,
  },
  rowTop:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  email:    { fontSize: FONT.lg, fontWeight: '700', color: COLORS.text },
  roleLine: { fontSize: FONT.sm, fontWeight: '700', textTransform: 'uppercase',
              letterSpacing: 0.5, marginTop: 2 },
  roleDesc: { fontSize: FONT.md, color: COLORS.textSecondary, lineHeight: 19 },
  actions:  { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.md },
  act: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.xs,
    paddingVertical: SPACE.sm, paddingHorizontal: SPACE.md,
    borderRadius: RADIUS.md, backgroundColor: COLORS.primaryDim,
  },
  actTxt:   { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },
  actDel: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.xs,
    paddingVertical: SPACE.sm, paddingHorizontal: SPACE.md,
    borderRadius: RADIUS.md, backgroundColor: COLORS.dangerDim,
  },
  actDelTxt: { color: COLORS.danger, fontSize: FONT.md, fontWeight: '700' },

  addBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.lg, paddingVertical: SPACE.lg,
  },
  addTxt: { color: COLORS.primary, fontSize: FONT.lg, fontWeight: '700' },

  formTitle: { fontSize: FONT.lg, fontWeight: '700', color: COLORS.text,
               marginBottom: SPACE.sm },
  label: { fontSize: FONT.sm, fontWeight: '600', color: COLORS.textSecondary,
           marginTop: SPACE.sm, marginBottom: SPACE.xs },
  input: {
    backgroundColor: COLORS.bgInput, borderRadius: RADIUS.md,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
    fontSize: FONT.lg, color: COLORS.text,
  },
  hint: { fontSize: FONT.sm, color: COLORS.textTertiary, marginTop: SPACE.xs,
          lineHeight: 17 },
  rolePick: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: COLORS.bgInput, borderRadius: RADIUS.md,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
  },
  rolePickTxt: { fontSize: FONT.lg, fontWeight: '700', textTransform: 'capitalize' },
  formBtns: { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.lg },
  cancel: {
    flex: 1, alignItems: 'center', paddingVertical: SPACE.md,
    borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt,
  },
  cancelTxt: { color: COLORS.textSecondary, fontSize: FONT.lg, fontWeight: '700' },
  save: {
    flex: 1, alignItems: 'center', paddingVertical: SPACE.md,
    borderRadius: RADIUS.md, backgroundColor: COLORS.primary,
  },
  saveTxt: { color: COLORS.textInverse, fontSize: FONT.lg, fontWeight: '700' },
  err: { fontSize: FONT.md, color: COLORS.danger },
});
