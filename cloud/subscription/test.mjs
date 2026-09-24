import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash, randomBytes } from 'node:crypto';
import { Miniflare } from 'miniflare';

// Given a private YAML and revocable token, only authorized GET/HEAD may read it.
// Tests execute the real Worker and real local KV in workerd, not a mocked handler.
test('private subscription contract in workerd', async () => {
  const token = randomBytes(32).toString('base64url');
  const hash = createHash('sha256').update(token).digest('hex');
  const script = await readFile(new URL('./worker.mjs', import.meta.url), 'utf8');
  const options = verifier => ({workers: [{config: {name: 'subscription',
    compatibilityDate: '2026-09-24',
    manifest: {mainModule: 'worker.mjs', modules: {'worker.mjs': {type: 'esm', contents: script}}},
    env: {CONFIGS: {type: 'kv', id: 'test-configs'},
      ...(verifier ? {TOKEN_SHA256: {type: 'text', value: verifier}} : {})}}}]});
  const mf = new Miniflare(options(hash));
  try {
    const kv = await mf.getKVNamespace('CONFIGS');
    const yaml = 'mode: rule\nrules:\n  - MATCH,REJECT\n';
    await kv.put('mihomo/routing.yaml', yaml);
    const base = 'https://subscription.test/mihomo/routing.yaml';
    for (const path of [base, base+'?token=wrong', base+'?token='+randomBytes(32).toString('base64url'),
      'https://subscription.test/', 'https://subscription.test/mihomo/missing.yaml?token='+token,
      base+'?token='+token+'&token='+token]) {
      const response = await mf.dispatchFetch(path);
      assert.equal(response.status, 404);
      assert.equal(await response.text(), 'Not found');
    }
    const response = await mf.dispatchFetch(base+'?token='+token);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), yaml);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.equal(response.headers.get('etag'), '"'+createHash('sha256').update(yaml).digest('hex')+'"');
    const head = await mf.dispatchFetch(base+'?token='+token, { method: 'HEAD' });
    assert.equal(head.status, 200); assert.equal(await head.text(), '');
    const write = await mf.dispatchFetch(base+'?token='+token, { method: 'PUT', body:'replace' });
    assert.equal(write.status, 404); assert.equal(await kv.get('mihomo/routing.yaml'), yaml);
    // Missing verifier fails closed; rotation invalidates the old token.
    await mf.setOptions(options());
    assert.equal((await mf.dispatchFetch(base+'?token='+token)).status, 404);
    await mf.setOptions(options('0'.repeat(64)));
    assert.equal((await mf.dispatchFetch(base+'?token='+token)).status, 404);
  } finally { await mf.dispose(); }
});
