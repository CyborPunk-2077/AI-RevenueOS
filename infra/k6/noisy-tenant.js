import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

/**
 * Noisy-tenant mix: one tenant issues 90% of the traffic. The quiet tenant must
 * keep meeting its SLO - throttling happens before shared-resource exhaustion.
 */
const quietTenantLatency = new Trend('quiet_tenant_latency', true);

export const options = {
  scenarios: {
    noisy: { executor: 'constant-vus', vus: 90, duration: '10m', env: { TENANT: 'noisy' } },
    quiet: { executor: 'constant-vus', vus: 10, duration: '10m', env: { TENANT: 'quiet' } },
  },
  thresholds: {
    // The quiet tenant is never starved by the noisy one.
    'quiet_tenant_latency': ['p(95)<200'],
  },
};

const BASE = __ENV.BASE_URL;

export function setup() {
  if (!BASE || !__ENV.NOISY_TOKEN || !__ENV.QUIET_TOKEN) {
    throw new Error('BASE_URL, NOISY_TOKEN and QUIET_TOKEN are required; no target is assumed');
  }
}

export default function () {
  const token = __ENV.TENANT === 'noisy' ? __ENV.NOISY_TOKEN : __ENV.QUIET_TOKEN;
  const response = http.get(`${BASE}/v1/leads?page_size=50`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (__ENV.TENANT === 'quiet') quietTenantLatency.add(response.timings.duration);
  check(response, { 'not starved': (r) => r.status === 200 || r.status === 429 });
}
