import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

/** Deliberate 2x spike above the 200-user P95 target, followed by recovery. */
const recoveryLatency = new Trend('spike_recovery_latency', true);

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: 20,
      stages: [
        { duration: '2m', target: 50 },
        { duration: '30s', target: 400 },
        { duration: '1m', target: 400 },
        { duration: '30s', target: 50 },
        { duration: '5m', target: 50 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    checks: ['rate>0.95'],
    spike_recovery_latency: ['p(95)<300'],
  },
};

const BASE = __ENV.BASE_URL;
const TOKEN = __ENV.ACCESS_TOKEN;

export function setup() {
  if (!BASE || !TOKEN) throw new Error('BASE_URL and ACCESS_TOKEN are required; no target is assumed');
  return { Authorization: `Bearer ${TOKEN}` };
}

export default function (headers) {
  const response = http.get(`${BASE}/v1/leads?page_size=20`, { headers });
  if (__VU <= 50) recoveryLatency.add(response.timings.duration);
  check(response, { 'spike request is served or truthfully throttled': (r) => [200, 429].includes(r.status) });
  sleep(0.5);
}
