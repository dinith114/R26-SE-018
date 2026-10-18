/**
 * App preferences: Simple vs Expert mode, and metres or feet.
 *
 * Simple mode (default) is designed for elderly, non-technical growers:
 *   big text, plain words, traffic-light colours, ONE action button.
 * Expert mode reveals the technical detail (VPD, charts, per-action buttons)
 * and is what you use to demonstrate the ML.
 *
 * lengthUnit ('m' | 'ft') is how house sizes and section positions are typed
 * and shown. The server always keeps metres (services/lengthUnits.js). Added 17
 * Oct 2026: the farm measured its house in feet.
 */
import React, { createContext, useContext, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'orchid.expertMode';
const UNIT_KEY = 'orchid.lengthUnit';
const PrefsContext = createContext({
  expert: false, setExpert: () => {}, lengthUnit: 'm', setLengthUnit: () => {}, ready: false,
});

export function PrefsProvider({ children }) {
  const [expert, setExpertState] = useState(false);
  const [lengthUnit, setUnitState] = useState('m');
  const [ready,  setReady]       = useState(false);

  useEffect(() => {
    Promise.all([
      AsyncStorage.getItem(KEY).then(v => { if (v !== null) setExpertState(v === '1'); }),
      AsyncStorage.getItem(UNIT_KEY).then(v => { if (v === 'm' || v === 'ft') setUnitState(v); }),
    ])
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setExpert = (v) => {
    setExpertState(v);
    AsyncStorage.setItem(KEY, v ? '1' : '0').catch(() => {});
  };

  const setLengthUnit = (u) => {
    if (u !== 'm' && u !== 'ft') return;
    setUnitState(u);
    AsyncStorage.setItem(UNIT_KEY, u).catch(() => {});
  };

  return (
    <PrefsContext.Provider value={{ expert, setExpert, lengthUnit, setLengthUnit, ready }}>
      {children}
    </PrefsContext.Provider>
  );
}

export const usePrefs = () => useContext(PrefsContext);
