/**
 * App preferences: metres or feet.
 *
 * lengthUnit ('m' | 'ft') is how house sizes and section positions are typed
 * and shown. The server always keeps metres (services/lengthUnits.js). Added 17
 * Oct 2026: the farm measured its house in feet.
 *
 * There was also a Simple / Expert switch here, choosing between a simplified
 * farm screen and the full one. Removed 19 Oct 2026 at the grower's request:
 * the full farm screen is the only one. A phone that had stored the old
 * 'orchid.expertMode' key keeps it harmlessly; nothing reads it.
 */
import React, { createContext, useContext, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const UNIT_KEY = 'orchid.lengthUnit';
const PrefsContext = createContext({
  lengthUnit: 'm', setLengthUnit: () => {}, ready: false,
});

export function PrefsProvider({ children }) {
  const [lengthUnit, setUnitState] = useState('m');
  const [ready,  setReady]       = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(UNIT_KEY)
      .then(v => { if (v === 'm' || v === 'ft') setUnitState(v); })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setLengthUnit = (u) => {
    if (u !== 'm' && u !== 'ft') return;
    setUnitState(u);
    AsyncStorage.setItem(UNIT_KEY, u).catch(() => {});
  };

  return (
    <PrefsContext.Provider value={{ lengthUnit, setLengthUnit, ready }}>
      {children}
    </PrefsContext.Provider>
  );
}

export const usePrefs = () => useContext(PrefsContext);
