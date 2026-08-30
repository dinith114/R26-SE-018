import { useState, useCallback, useEffect, useRef } from 'react';
import { useFocusEffect } from '@react-navigation/native';

/**
 * Live-polling data hook.
 *
 * The farm is a live system — sensors report every few minutes — so screens
 * must refresh on their own, not only when you navigate to them. This polls
 * while the screen is focused and stops when it is not, so it never runs in
 * the background wasting battery.
 *
 *   const { data, loading, error, refreshing, refresh } = useLiveData(getOverview, 15000);
 */
/* How often a screen re-reads the farm.
 *
 * Matched to how often the DATA can actually change: a node reports roughly
 * every 27 s (a 15 s read interval plus its network work), so polling at 15 s
 * downloaded every reading twice and paid Firebase egress for the duplicate.
 * That duplication, multiplied across several open screens, is part of what
 * exhausted the free tier. Do not lower this below the node's read interval.
 */
export const LIVE_MS = 30000;

export default function useLiveData(fetcher, intervalMs = LIVE_MS) {
  const [data,       setData]       = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,      setError]      = useState(null);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const alive = useRef(false);

  const load = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true);
    try {
      const d = await fetcherRef.current();
      if (alive.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current) setError(e.message);
    } finally {
      if (alive.current) { setLoading(false); setRefreshing(false); }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      alive.current = true;
      load();
      const id = setInterval(() => load(), intervalMs);
      return () => { alive.current = false; clearInterval(id); };
    }, [load, intervalMs])
  );

  return { data, loading, error, refreshing, refresh: () => load(true), reload: load };
}
