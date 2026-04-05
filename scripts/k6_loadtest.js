import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter, Rate } from "k6/metrics";

// Custom metrics per endpoint
const searchLatency = new Trend("search_latency", true);
const detailLatency = new Trend("indicator_detail_latency", true);
const timelineLatency = new Trend("campaign_timeline_latency", true);
const dashboardLatency = new Trend("dashboard_latency", true);
const healthLatency = new Trend("health_latency", true);
const slaViolations = new Counter("sla_violations");
const successRate = new Rate("success_rate");

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

// SLA targets from PRD (ms)
const SLA = {
  search: 100,
  indicator_detail: 100,
  campaign_timeline: 250,
  dashboard: 250,
  health: 100,
};

export const options = {
  scenarios: {
    load_test: {
      executor: "constant-vus",
      vus: 50,
      duration: "30s",
    },
  },
  thresholds: {
    // Server-side SLA targets
    "search_latency": ["p(95)<100"],
    "indicator_detail_latency": ["p(95)<100"],
    "campaign_timeline_latency": ["p(95)<250"],
    "dashboard_latency": ["p(95)<250"],
    "health_latency": ["p(95)<100"],
    // Overall
    "http_req_failed": ["rate<0.01"],
    "success_rate": ["rate>0.99"],
  },
};

// Discover IDs in setup phase
export function setup() {
  const searchResp = http.get(`${BASE_URL}/api/indicators/search?limit=50`);
  const indicatorIds = [];
  const campaignIds = [];

  if (searchResp.status === 200) {
    const data = JSON.parse(searchResp.body).data;
    for (const item of data) {
      indicatorIds.push(item.id);
    }
  }

  // Discover campaign IDs from indicator details
  for (let i = 0; i < Math.min(5, indicatorIds.length); i++) {
    const resp = http.get(`${BASE_URL}/api/indicators/${indicatorIds[i]}`);
    if (resp.status === 200) {
      const detail = JSON.parse(resp.body);
      for (const camp of detail.campaigns || []) {
        if (!campaignIds.includes(camp.id)) {
          campaignIds.push(camp.id);
        }
      }
    }
  }

  console.log(`Setup: found ${indicatorIds.length} indicators, ${campaignIds.length} campaigns`);
  return { indicatorIds, campaignIds };
}

export default function (data) {
  const { indicatorIds, campaignIds } = data;
  const roll = Math.random();

  let resp;

  if (roll < 0.4) {
    // 40% — Search
    const types = ["ip", "domain", "url", "hash"];
    const limits = [10, 20, 50];
    const params = { limit: limits[Math.floor(Math.random() * limits.length)] };
    if (Math.random() > 0.5) {
      params.type = types[Math.floor(Math.random() * types.length)];
    }
    resp = http.get(`${BASE_URL}/api/indicators/search`, { params });
    searchLatency.add(resp.timings.duration);
    if (resp.timings.duration > SLA.search) slaViolations.add(1);

  } else if (roll < 0.7) {
    // 30% — Indicator detail
    const id = indicatorIds[Math.floor(Math.random() * indicatorIds.length)];
    resp = http.get(`${BASE_URL}/api/indicators/${id}`);
    detailLatency.add(resp.timings.duration);
    if (resp.timings.duration > SLA.indicator_detail) slaViolations.add(1);

  } else if (roll < 0.85) {
    // 15% — Campaign timeline
    const id = campaignIds.length > 0
      ? campaignIds[Math.floor(Math.random() * campaignIds.length)]
      : indicatorIds[Math.floor(Math.random() * indicatorIds.length)];
    const groupBy = Math.random() > 0.5 ? "day" : "week";
    resp = http.get(`${BASE_URL}/api/campaigns/${id}/indicators`, { params: { group_by: groupBy } });
    timelineLatency.add(resp.timings.duration);
    if (resp.timings.duration > SLA.campaign_timeline) slaViolations.add(1);

  } else if (roll < 0.95) {
    // 10% — Dashboard
    const ranges = ["24h", "7d", "30d"];
    const timeRange = ranges[Math.floor(Math.random() * ranges.length)];
    resp = http.get(`${BASE_URL}/api/dashboard/summary`, { params: { time_range: timeRange } });
    dashboardLatency.add(resp.timings.duration);
    if (resp.timings.duration > SLA.dashboard) slaViolations.add(1);

  } else {
    // 5% — Health
    resp = http.get(`${BASE_URL}/health`);
    healthLatency.add(resp.timings.duration);
    if (resp.timings.duration > SLA.health) slaViolations.add(1);
  }

  const ok = resp.status >= 200 && resp.status < 500;
  successRate.add(ok);
  check(resp, { "status < 500": (r) => r.status < 500 });

  // Small jitter between requests
  sleep(Math.random() * 0.01);
}
