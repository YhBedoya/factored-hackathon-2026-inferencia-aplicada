// D11/D12 (`docs/specs/d7-b-transactions-traceability-judge.md`, "Contracts"
// -> "B3: `04` §3 additions (proposed)"): hand-written types and fetchers for
// the staff traceability screens, built against the spec's proposed shapes
// because A1's generated client doesn't carry
// `GET /staff/conversations{,/{id}/timeline}` yet (D7-A1 not on `develop`
// yet). Delete this file once A1 merges and `make client` regenerates
// `src/client/types.gen.ts` with the real routes (`06` §4); every import
// below then moves to `@/client` + `lib/api.ts`, following the
// `withStaffAuth` pattern those already use.

/** `backend/app/domains/conversation/schemas.py::Intent`, the closed catalog. */
export type Intent =
	| "card_status"
	| "balance_due"
	| "decline_explain"
	| "transaction_search"
	| "pending_reversal_explain"
	| "card_block"
	| "card_unlock"
	| "unrecognized_charge"
	| "replacement_request"
	| "human_request"
	| "general_question"
	| "greeting"
	| "thanks_close"
	| "affirm"
	| "deny"
	| "travel_notice"
	| "spending_limits"
	| "card_doctor"
	| "expiry_renewal"
	| "benefits_info"
	| "card_activation"
	| "pin_reset"
	| "card_cancel"
	| "limit_increase"
	| "card_finder"
	| "prequalification";

/** `backend/app/domains/handoff/schemas.py::HandoffReason`, plus `priority_claim` (SA1, this card). */
export type HandoffReason =
	| "human_request"
	| "clarification_exhausted"
	| "legal_regulator"
	| "customer_not_active"
	| "bank_side_block"
	| "action_unverified"
	| "unauthorized_access"
	| "suspected_fraud"
	| "tool_failure"
	| "llm_unavailable"
	| "priority_claim";

export type Queue = "atencion" | "cobranza" | "fraudes" | "reclamos";

export type ConversationOutcome =
	| "resolved"
	| "clarified"
	| "abstained"
	| "handoff";

/** `GET /staff/conversations` query (D11's `ConversationFilters`). */
export type ConversationFilters = {
	language: "es" | "pt" | null;
	country: "MX" | "CO" | "AR" | null;
	intent: Intent | null;
	outcome: ConversationOutcome | null;
	escalation: HandoffReason | null;
	date_from: string | null; // ISO date, `YYYY-MM-DD`
	date_to: string | null; // ISO date, `YYYY-MM-DD`
	limit: number;
	offset: number;
};

export const DEFAULT_CONVERSATION_FILTERS: ConversationFilters = {
	language: null,
	country: null,
	intent: null,
	outcome: null,
	escalation: null,
	date_from: null,
	date_to: null,
	limit: 50,
	offset: 0,
};

export type ConversationListItem = {
	conversation_id: string;
	started_at: string;
	language: "es" | "pt" | null;
	country: "MX" | "CO" | "AR";
	intents: Intent[];
	outcome: string | null;
	escalation: HandoffReason | null;
	handoff_queue: Queue | null;
	turns: number;
	mode: "bot" | "human";
};

export type ConversationList = {
	items: ConversationListItem[];
	total: number;
};

export type TimelineLLMCall = {
	step: string;
	model_id: string;
	prompt_version: string;
	latency_ms: number;
	input_tokens: number | null;
	output_tokens: number | null;
	cost_usd: string | null; // Decimal, serialized as a string (same as `HandoffEvidence.fraud_score`)
	status: string;
};

/** One `audit.audit_events` row; the payload is already masked (R5). */
export type TimelineEvent = {
	at: string;
	type: string;
	actor: string;
	payload: Record<string, unknown>;
	sources: string[];
};

export type TurnTimeline = {
	turn_id: string;
	at: string;
	customer_text_masked: string | null;
	reply_text: string | null;
	nlu: Record<string, unknown> | null;
	rules_hit: string[];
	tools: TimelineEvent[];
	sources: string[];
	policy_version: string;
	llm_calls: TimelineLLMCall[];
	latency_ms: number | null;
	cost_usd: string | null;
	langfuse_url: string | null;
	events: TimelineEvent[];
};

export type ConversationTimeline = {
	conversation_id: string;
	system: Record<string, unknown>;
	turns: TurnTimeline[];
};

const STAFF_CONVERSATIONS_PATH = "/api/v1/staff/conversations";

// D4-B D3/D5 pattern (`lib/api.ts`'s `withStaffAuth`): an agent session's
// `401` has no refresh path (`/auth/refresh` answers `403` for staff, not
// `401`), so this goes straight to `/staff/login` instead of retrying.
async function staffGet<T>(path: string): Promise<T> {
	const response = await fetch(path, { credentials: "include" });
	if (response.status === 401) {
		window.location.assign("/staff/login");
		throw new Error("unauthorized");
	}
	if (!response.ok) {
		throw new Error(`traceability: ${response.status} on ${path}`);
	}
	return (await response.json()) as T;
}

function toQuery(filters: Partial<ConversationFilters>): string {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters)) {
		if (value !== null && value !== undefined && value !== "") {
			params.set(key, String(value));
		}
	}
	const query = params.toString();
	return query ? `?${query}` : "";
}

export async function listConversations(
	filters: Partial<ConversationFilters>,
): Promise<ConversationList> {
	return staffGet<ConversationList>(
		`${STAFF_CONVERSATIONS_PATH}${toQuery(filters)}`,
	);
}

export async function getConversationTimeline(
	conversationId: string,
): Promise<ConversationTimeline> {
	return staffGet<ConversationTimeline>(
		`${STAFF_CONVERSATIONS_PATH}/${conversationId}/timeline`,
	);
}
