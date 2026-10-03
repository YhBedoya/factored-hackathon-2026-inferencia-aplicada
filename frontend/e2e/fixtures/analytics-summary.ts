import type { AnalyticsSummary } from "../../src/client";

export const REAL_CONVERSATION_ID = "conv-e2e-analytics-real";
const MOCK_CONVERSATION_ID = "conv-e2e-analytics-mock";

type Source = "all" | "real" | "mock";

/**
 * `GET /staff/analytics/summary` fixture in the generated client's shape.
 * Every block is non-empty under `all`; `real` carries no mock data, so the
 * mock badge/footer must disappear there.
 */
export function analyticsSummaryFixture(source: Source): AnalyticsSummary {
	const includesMock = source !== "real";
	const recent: AnalyticsSummary["recent"] = [];
	if (source !== "mock") {
		recent.push({
			conversation_id: REAL_CONVERSATION_ID,
			source: "real",
			ended_at: "2026-03-30T12:05:00Z",
			end_reason: "customer_closed",
			intents: ["transaction_search"],
			outcome: "resolved",
			sentiment_overall: "positive",
			cost_usd: 0.0021,
		});
	}
	if (includesMock) {
		recent.push({
			conversation_id: MOCK_CONVERSATION_ID,
			source: "mock",
			ended_at: "2026-03-29T10:00:00Z",
			end_reason: "customer_closed",
			intents: ["card_status"],
			outcome: "escalated",
			sentiment_overall: "negative",
			cost_usd: 0.004,
		});
	}
	return {
		filters: {
			date_from: "2026-03-01",
			date_to: "2026-03-31",
			language: null,
			country: null,
			source,
			timezone: "America/Mexico_City",
		},
		includes_mock: includesMock,
		tiles: {
			interactions: 10,
			resolution: { rate: 0.6, num: 6, den: 10 },
			escalation: { rate: 0.3, num: 3, den: 10 },
			cost_per_interaction: { avg_usd: 0.003, total_usd: 0.03, count: 10 },
			messages_per_interaction: { avg: 4.5, count: 10 },
			negative_sentiment: { rate: 0.2, num: 2, den: 10 },
		},
		per_day: [
			{
				day: "2026-03-29",
				escalated: 1,
				resolved: 2,
				abandoned: 1,
				abstained: 0,
				other: 0,
			},
			{
				day: "2026-03-30",
				escalated: 2,
				resolved: 4,
				abandoned: 0,
				abstained: 0,
				other: 0,
			},
		],
		intents: [
			{
				intent: "transaction_search",
				count: 8,
				resolution: { rate: 0.625, num: 5, den: 8 },
			},
			{
				intent: "card_status",
				count: 2,
				resolution: { rate: 0.5, num: 1, den: 2 },
			},
		],
		escalations: {
			by_cause_group: [{ group: "fraud", count: 3 }],
			by_queue: [{ queue: "fraudes", count: 3 }],
			time_to_claim_median_s: 42,
			time_to_claim_count: 3,
		},
		sentiment: {
			overall: { negative: 2, neutral: 3, positive: 5, scored: 10 },
			trajectory: { better: 2, same: 6, worse: 2, scored: 10 },
		},
		cost: {
			per_day: [
				{
					day: "2026-03-29",
					nlu_usd: 0.004,
					compose_usd: 0.008,
					handoff_summary_usd: 0.001,
				},
				{
					day: "2026-03-30",
					nlu_usd: 0.006,
					compose_usd: 0.01,
					handoff_summary_usd: 0.001,
				},
			],
			total_usd: 0.03,
			per_resolved: { usd: 0.005, resolved: 6 },
			sentiment_overhead_usd: 0.002,
		},
		recent,
	};
}
