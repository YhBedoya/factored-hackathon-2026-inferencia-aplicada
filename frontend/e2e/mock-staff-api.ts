import type { Page } from "@playwright/test";

const CSRF_COOKIE_NAME = "csrf_token";
const CSRF_COOKIE_VALUE = "e2e-fake-staff-csrf-token";

const HANDOFF_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const CONVERSATION_ID = "conv-e2e-staff-001";

// D7-A D23: the traceability list (`GET /staff/conversations`,
// `ConversationPage`) and timeline (`GET /staff/conversations/{id}/timeline`,
// `ConversationTimeline`) fixtures, in the generated client's shapes and kept
// apart from the handoff/packet ones above -- `traceability.es.spec.ts` never
// claims a handoff, it only reads these two routes.
const TRACE_CONVERSATIONS = [
	{
		conversation_id: "conv-e2e-trace-001",
		created_at: "2026-03-30T12:00:00Z",
		language: "es",
		country: "MX",
		intents: ["transaction_search"],
		outcome: "resolved",
		escalated: false,
		queue: null,
		mode: "bot",
		status: "open",
		turns: 3,
	},
	{
		conversation_id: "conv-e2e-trace-002",
		created_at: "2026-03-30T13:00:00Z",
		language: "pt",
		country: "CO",
		intents: ["transaction_search"],
		outcome: "resolved",
		escalated: false,
		queue: null,
		mode: "bot",
		status: "open",
		turns: 2,
	},
	{
		conversation_id: "conv-e2e-trace-003",
		created_at: "2026-03-30T14:00:00Z",
		language: "es",
		country: "AR",
		intents: ["card_status", "unrecognized_charge"],
		outcome: "handoff:reclamos",
		escalated: true,
		queue: "reclamos",
		mode: "human",
		status: "open",
		turns: 1,
	},
];

function timelineEvent(
	type: string,
	payload: Record<string, unknown>,
	sources: string[] = [],
) {
	return {
		at: "2026-03-30T12:00:06Z",
		type,
		actor: "system",
		payload,
		sources,
	};
}

// One fixed timeline, served for whichever id the test opens: 2 turns, one
// with a `langfuse_url` and one without (test 12 step 6).
function timelineFixture() {
	const nlu = { intents: ["transaction_search"], status: "clear" };
	const rule = timelineEvent("rule_hit", { rule_id: "date_widened" });
	const tool = timelineEvent("tool_call", { tool: "transactions.search" }, [
		"bank.transactions",
	]);
	return {
		conversation: TRACE_CONVERSATIONS[0],
		turns: [
			{
				turn_id: "turn-e2e-001",
				started_at: "2026-03-30T12:00:05Z",
				customer_text_masked: "el cargo de ⟨MERCHANT_1⟩ del martes pasado",
				bot_text_masked: "Encontré este cargo.",
				nlu,
				rules: [rule],
				tools: [tool],
				events: [timelineEvent("nlu_result", nlu), rule, tool],
				sources: ["bank.transactions"],
				policy_version: "policy-hash-e2e",
				llm_calls: [
					{
						step: "compose",
						model_id: "claude-e2e",
						prompt_version: "compose@v7",
						temperature: 0,
						attempt: 1,
						status: "ok",
						latency_ms: 420.4,
						input_tokens: 120,
						output_tokens: 40,
						cost_usd: 0.0021,
					},
				],
				latency_ms: 650.2,
				cost_usd: 0.0021,
				langfuse_url: "https://langfuse.e2e.invalid/trace/turn-e2e-001",
			},
			{
				turn_id: "turn-e2e-002",
				started_at: "2026-03-30T12:01:05Z",
				customer_text_masked: "gracias",
				bot_text_masked: "Con gusto.",
				nlu: { intents: ["thanks_close"], status: "clear" },
				rules: [],
				tools: [],
				events: [],
				sources: [],
				policy_version: "policy-hash-e2e",
				llm_calls: [],
				latency_ms: 120,
				cost_usd: null,
				langfuse_url: null,
			},
		],
	};
}

export type RecordedRequest = {
	pathname: string;
	method: string;
	body: unknown;
};

export type InstallMockStaffApiOptions = {
	/** The only password `/auth/staff/login` accepts; anything else answers `401 invalid_credentials`. */
	password: string;
	agentDisplayName?: string;
};

export type MockStaffApi = {
	/** Every posted agent message and "return to bot" body, in call order (D21). */
	requests: RecordedRequest[];
};

function packetFor() {
	return {
		queue: "fraudes",
		priority: "high",
		reason: "suspected_fraud",
		language: "es",
		verified_facts: [
			{ fact: "card_status", value: "Active", source: "bank.cards" },
		],
		actions_taken: [
			{
				tool: "disputes.create_claim",
				result: "applied",
				verified: true,
				audit_event_id: "aud-e2e-001",
				at: "2026-03-30T12:00:05Z",
				tracking_id: null,
				case_ids: ["CLM-AB12CD34", "CLM-EF56GH78"],
			},
		],
		evidence: [{ type: "transaction", ref: "TRX-001", fraud_score: "45.00" }],
		open_questions: ["El cliente aún tiene la tarjeta en su poder."],
		escalation_rules_hit: ["suspected_fraud"],
		handoff_id: HANDOFF_ID,
		conversation_id: CONVERSATION_ID,
		request: "Cliente reporta cargos no reconocidos.",
		sentiment: null,
		policy_version: "1",
		created_at: "2026-03-30T12:00:00Z",
	};
}

/**
 * Stateful `page.route` mock of `/api/v1/**` for the staff SPA (spec D21),
 * kept separate from `mock-api.ts` (customer-only) per the plan's touch
 * map. Same style: no real backend, no LLM, the queue-poll and the claim/
 * return transitions are held in closure state instead of `.sse` fixtures,
 * since the staff routes carry no SSE-driven turn.
 */
export async function installMockStaffApi(
	page: Page,
	options: InstallMockStaffApiOptions,
): Promise<MockStaffApi> {
	const displayName = options.agentDisplayName ?? "Sofía";
	const requests: RecordedRequest[] = [];
	let loggedIn = false;
	let handoffsPolls = 0;
	let claimed = false;
	let messageCounter = 0;

	// D4-A's `StaffMeResponse`, `HandoffSummary` and `HandoffDetail` shapes.
	const profile = {
		role: "agent",
		username: "agent.fraudes",
		display_name: displayName,
		queue: "fraudes",
	};

	function summary() {
		return {
			handoff_id: HANDOFF_ID,
			reference: "HO-3FA85F64",
			conversation_id: CONVERSATION_ID,
			queue: "fraudes",
			priority: "high",
			reason: "suspected_fraud",
			status: claimed ? "claimed" : "queued",
			language: "es",
			created_at: "2026-03-30T12:00:00Z",
			claimed_by: claimed ? displayName : null,
		};
	}

	await page.route("**/api/v1/**", async (route) => {
		const request = route.request();
		const { pathname } = new URL(request.url());
		const method = request.method();

		if (pathname.endsWith("/staff/me") && method === "GET") {
			await route.fulfill(
				loggedIn
					? { status: 200, json: profile }
					: { status: 401, json: { detail: "session_expired" } },
			);
			return;
		}

		if (pathname.endsWith("/auth/staff/login") && method === "POST") {
			const body = request.postDataJSON() as { password?: string };
			if (body.password !== options.password) {
				await route.fulfill({
					status: 401,
					json: { detail: "invalid_credentials" },
				});
				return;
			}
			loggedIn = true;
			await page.context().addCookies([
				{
					name: CSRF_COOKIE_NAME,
					value: CSRF_COOKIE_VALUE,
					url: new URL(request.url()).origin,
					httpOnly: false,
				},
			]);
			await route.fulfill({ status: 200, json: profile });
			return;
		}

		// The inbox poll (D20): empty on the first call, so the second call
		// (~3s later, via `refetchInterval`) is what actually proves polling.
		if (pathname.endsWith("/staff/handoffs") && method === "GET") {
			handoffsPolls += 1;
			await route.fulfill({
				status: 200,
				json: handoffsPolls > 1 ? [summary()] : [],
			});
			return;
		}

		if (
			pathname.endsWith(`/staff/handoffs/${HANDOFF_ID}`) &&
			method === "GET"
		) {
			await route.fulfill({
				status: 200,
				json: { summary: summary(), packet: packetFor() },
			});
			return;
		}

		if (
			pathname.endsWith(`/staff/handoffs/${HANDOFF_ID}/claim`) &&
			method === "POST"
		) {
			claimed = true;
			await route.fulfill({
				status: 200,
				json: { summary: summary(), packet: packetFor() },
			});
			return;
		}

		if (
			pathname.endsWith(`/staff/handoffs/${HANDOFF_ID}/return`) &&
			method === "POST"
		) {
			requests.push({ pathname, method, body: request.postDataJSON() });
			claimed = false;
			await route.fulfill({ status: 200, json: summary() });
			return;
		}

		if (pathname.endsWith("/staff/conversations") && method === "GET") {
			const url = new URL(request.url());
			const intent = url.searchParams.get("intent");
			const language = url.searchParams.get("language");
			const outcome = url.searchParams.get("outcome");
			const escalation = url.searchParams.get("escalation");
			// Same meanings as the backend (D7-A D19): `outcome=handoff` matches
			// every `handoff:<queue>`; `escalation` is `none`, `any` or a queue.
			const items = TRACE_CONVERSATIONS.filter(
				(conversation) =>
					(!intent || conversation.intents.includes(intent)) &&
					(!language || conversation.language === language) &&
					(!outcome ||
						conversation.outcome === outcome ||
						conversation.outcome.startsWith(`${outcome}:`)) &&
					(!escalation ||
						(escalation === "none" && !conversation.escalated) ||
						(escalation === "any" && conversation.escalated) ||
						conversation.queue === escalation),
			);
			await route.fulfill({
				status: 200,
				json: { items, total: items.length },
			});
			return;
		}

		if (
			/\/staff\/conversations\/[^/]+\/timeline$/.test(pathname) &&
			method === "GET"
		) {
			await route.fulfill({ status: 200, json: timelineFixture() });
			return;
		}

		if (
			/\/staff\/conversations\/[^/]+\/messages$/.test(pathname) &&
			method === "POST"
		) {
			requests.push({ pathname, method, body: request.postDataJSON() });
			messageCounter += 1;
			await route.fulfill({
				status: 201,
				json: { message_id: `msg-e2e-${messageCounter}` },
			});
			return;
		}

		if (
			/\/staff\/conversations\/[^/]+\/stream$/.test(pathname) &&
			method === "GET"
		) {
			await route.fulfill({
				status: 200,
				contentType: "text/event-stream",
				body: "retry: 200\n\n: connected\n\n",
			});
			return;
		}

		await route.fulfill({ status: 404, json: { detail: "not_found" } });
	});

	return { requests };
}
