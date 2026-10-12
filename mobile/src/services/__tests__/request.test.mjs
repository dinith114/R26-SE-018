/**
 * What request.js decides, proven without a device.
 *
 * Run: cd mobile && node --test src/services/__tests__/
 *
 * request.js is loaded from source through a data: URI rather than imported by
 * path. The app has no "type": "module" and no build step, so Node would read a
 * .js file as CommonJS and choke on its `export`. Reading the real file and
 * evaluating it keeps this a test of the shipped code rather than of a copy -
 * which is the whole reason request.js is allowed no imports of its own.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'request.js'), 'utf8');
const { makeRequest } = await import(
  'data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const KEY = 'test-api-key';

/** A fetch that replays the given statuses in order and records every call. */
function stubFetch(statuses) {
  const calls = [];
  const queue = [...statuses];
  const impl = async (url, opts) => {
    calls.push({ url, headers: opts.headers, method: opts.method });
    const status = queue.length > 1 ? queue.shift() : queue[0];
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => (status >= 400 ? { detail: `boom ${status}` } : { ok: true }),
    };
  };
  return { impl, calls };
}

function harness({ statuses, tokens = ['tok-1', 'tok-2'] }) {
  const { impl, calls } = stubFetch(statuses);
  const issued = [];
  let signedOut = 0;
  const request = makeRequest({
    apiKey: KEY,
    fetchImpl: impl,
    getToken: async ({ force = false } = {}) => {
      const t = force ? tokens[1] : tokens[0];
      issued.push({ force, token: t });
      return t;
    },
    signOutNow: async () => { signedOut += 1; },
  });
  return { request, calls, issued, signedOut: () => signedOut };
}

test('a request carries the bearer token and the legacy key', async () => {
  const h = harness({ statuses: [200] });
  await h.request('http://x', '/overview');
  const sent = h.calls[0].headers;
  assert.equal(sent.Authorization, 'Bearer tok-1');
  assert.equal(sent['X-API-Key'], KEY);
  assert.equal(sent['Content-Type'], 'application/json');
});

test('the token is fetched per call, not captured once', async () => {
  const h = harness({ statuses: [200] });
  await h.request('http://x', '/overview');
  await h.request('http://x', '/alerts');
  assert.equal(h.issued.length, 2, 'each call asks for a token of its own');
});

test('401 retries exactly once, with a FORCED refresh', async () => {
  const h = harness({ statuses: [401, 200] });
  await h.request('http://x', '/overview');
  assert.equal(h.calls.length, 2, 'one retry, not a loop');
  assert.equal(h.calls[0].headers.Authorization, 'Bearer tok-1');
  assert.equal(h.calls[1].headers.Authorization, 'Bearer tok-2',
    'the retry must carry a NEW token, or it is just the same failure again');
  assert.deepEqual(h.issued.map(i => i.force), [false, true]);
  assert.equal(h.signedOut(), 0, 'a recoverable 401 must not sign anyone out');
});

test('a 401 that survives the refresh signs out', async () => {
  const h = harness({ statuses: [401] });
  await assert.rejects(() => h.request('http://x', '/overview'), /boom 401/);
  assert.equal(h.calls.length, 2, 'tried once more, then gave up');
  assert.equal(h.signedOut(), 1);
});

test('403 does NOT retry and does NOT sign out', async () => {
  /* The whole point of separating them. A viewer pressing an admin control is
     correctly signed in; signing them out would read as "session expired" and
     send them to re-enter a password that cannot help. */
  const h = harness({ statuses: [403] });
  await assert.rejects(() => h.request('http://x', '/water', { method: 'POST' }),
    (e) => e.status === 403);
  assert.equal(h.calls.length, 1, 'no retry');
  assert.equal(h.signedOut(), 0, 'no sign-out');
});

test('a write is never blind-retried: one 401 refresh is the only repeat', async () => {
  /* A second POST /water is a second pour. */
  const h = harness({ statuses: [500] });
  await assert.rejects(() => h.request('http://x', '/water', { method: 'POST' }));
  assert.equal(h.calls.length, 1);
});

test('err.status is set on every path, not just devices', async () => {
  for (const status of [403, 409, 500]) {
    const h = harness({ statuses: [status] });
    await assert.rejects(() => h.request('http://x', '/anything'),
      (e) => e.status === status);
  }
});

test('the detail from the server is what the person sees', async () => {
  const h = harness({ statuses: [403] });
  await assert.rejects(() => h.request('http://x', '/water'), /boom 403/);
});

test('with nobody signed in, a 401 does not sign out again', async () => {
  /* Screens can fire mid sign-out. There is nothing to refresh and no session
     to end; calling signOut again would race the one already running. */
  const { impl, calls } = stubFetch([401]);
  let signedOut = 0;
  const request = makeRequest({
    apiKey: KEY,
    fetchImpl: impl,
    getToken: async () => null,
    signOutNow: async () => { signedOut += 1; },
  });
  await assert.rejects(() => request('http://x', '/overview'));
  assert.equal(calls.length, 1, 'no pointless retry');
  assert.equal(signedOut, 0);
  assert.equal(calls[0].headers.Authorization, undefined,
    'no Authorization header at all, rather than "Bearer null"');
});

test('an options.headers cannot drop the Authorization header', async () => {
  /* The old helpers spread the header constant FIRST, so a caller passing its
     own headers replaced it wholesale. No caller does today - measured, 0 of
     them - but a request that silently loses its token is a 401 nobody can
     explain, so the ordering was reversed deliberately. */
  const h = harness({ statuses: [200] });
  await h.request('http://x', '/overview', { headers: { 'X-Other': '1' } });
  assert.equal(h.calls[0].headers.Authorization, 'Bearer tok-1');
});
