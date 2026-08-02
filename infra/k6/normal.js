import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

/** Normal load: 500 virtual users. SLOs: reads P95 <200ms, writes P95 <500ms. */
const readLatency = new Trend('read_latency', true);
const writeLatency = new Trend('write_latency', true);

export const options = {
  stages: [
    { duration: '2m', target: 100 },
    { duration: '3m', target: 500 },
    { duration: '10m', target: 500 },
    { duration: '2m', target: 0 },
  ],
  thresholds: {
    'read_latency': ['p(95)<200'],
    'write_latency': ['p(95)<500'],
    'http_req_failed': ['rate<0.01'],
  },
};

const BASE = __ENV.BASE_URL;
const TOKEN = __ENV.ACCESS_TOKEN;

export function setup() {
  if (!BASE || !TOKEN) throw new Error('BASE_URL and ACCESS_TOKEN are required; no target is assumed');
  return { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' };
}

export default function (headers) {
  const list = http.get(`${BASE}/v1/leads?page_size=50`, { headers });
  readLatency.add(list.timings.duration);
  check(list, { 'list returns 200': (r) => r.status === 200 });

  const created = http.post(
    `${BASE}/v1/leads`,
    JSON.stringify({ first_name: `Load${__VU}`, email: `load-${__VU}-${__ITER}@example.in` }),
    { headers: { ...headers, 'Idempotency-Key': `${__VU}-${__ITER}` } },
  );
  writeLatency.add(created.timings.duration);
  check(created, { 'create returns 201': (r) => r.status === 201 });

  sleep(1);
}
