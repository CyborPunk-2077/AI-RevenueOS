import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

/** Year-one P95 target: 200 concurrent users, with an 80/20 read/write mix. */
const readLatency = new Trend('peak_read_latency', true);
const writeLatency = new Trend('peak_write_latency', true);

export const options = {
  scenarios: {
    peak: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50 },
        { duration: '3m', target: 200 },
        { duration: '10m', target: 200 },
        { duration: '3m', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    peak_read_latency: ['p(95)<200'],
    peak_write_latency: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
};

const BASE = __ENV.BASE_URL;
const TOKEN = __ENV.ACCESS_TOKEN;

export function setup() {
  if (!BASE || !TOKEN) throw new Error('BASE_URL and ACCESS_TOKEN are required; no target is assumed');
  return { headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' } };
}

export default function (data) {
  if (__ITER % 5 !== 0) {
    const response = http.get(`${BASE}/v1/leads?page_size=50`, { headers: data.headers });
    readLatency.add(response.timings.duration);
    check(response, { 'peak read is 200': (r) => r.status === 200 });
  } else {
    const key = `peak-${__VU}-${__ITER}`;
    const response = http.post(
      `${BASE}/v1/leads`,
      JSON.stringify({ first_name: `Peak${__VU}`, email: `${key}@example.invalid` }),
      { headers: { ...data.headers, 'Idempotency-Key': key } },
    );
    writeLatency.add(response.timings.duration);
    check(response, { 'peak write is 201': (r) => r.status === 201 });
  }
  sleep(1);
}
