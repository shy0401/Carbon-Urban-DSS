const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const base = process.env.DSS_GATEWAY_URL || 'http://127.0.0.1:5180';
  const credentials = JSON.parse(fs.readFileSync(path.resolve('.secrets/prototype-credentials.json'), 'utf8').replace(/^\uFEFF/, ''));
  const Authorization = 'Basic ' + Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64');
  const request = (url, options = {}) => fetch(base + url, {...options, signal: AbortSignal.timeout(30000)});
  for (const route of ['/', '/api/health', '/api/scenarios', '/api/reports']) {
    assert.equal((await request(route)).status, 401, 'Unauthenticated access: ' + route);
  }
  assert.equal((await request('/api/health', {headers:{Authorization:'Basic ' + Buffer.from('invalid:invalid').toString('base64')}})).status, 401);
  const response = await request('/api/health', {headers:{Authorization}});
  assert.equal(response.status, 200);
  assert.equal((await response.json()).database, 'connected');
  assert.equal((await request('/', {headers:{Authorization}})).status, 200);
  assert.equal((await request('/api/system/offline', {method:'POST', headers:{Authorization, 'Content-Type':'application/json', 'Sec-Fetch-Site':'cross-site'}, body:'{"enabled":true}'})).status, 403);
  console.log(JSON.stringify({passed:8, database:'connected', unauthenticated:'blocked', crossSiteWrites:'blocked'}));
})().catch(error => {console.error(error.message);process.exitCode=1;});
