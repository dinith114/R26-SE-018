/**
 * App preferences — currently just Simple vs Expert mode.
 *
 * Simple mode (default) is designed for elderly, non-technical growers:
 *   big text, plain words, traffic-light colours, ONE action button.
 * Expert mode reveals the technical detail (VPD, charts, per-action buttons)
 * and is what you use to demonstrate the ML.
 */
import React, { createContext, useContext, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'orchid.expertMode';
const PrefsContext = createContext({ expert: false, setExpert: () => {}, ready: false });

export function PrefsProvider({ children }) {
  const [expert, setExpertState] = useState(false);
  const [ready,  setReady]       = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then(v => { if (v !== null) setExpertState(v === '1'); })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setExpert = (v) => {
    setExpertState(v);
    AsyncStorage.setItem(KEY, v ? '1' : '0').catch(() => {});
  };

  return (
    <PrefsContext.Provider value={{ expert, setExpert, ready }}>
      {children}
    </PrefsContext.Provider>
  );
}

export const usePrefs = () => useContext(PrefsContext);
