import type { Page } from "@playwright/test";

const CSRF_COOKIE_NAME = "csrf_token";
const CSRF_COOKIE_VALUE = "e2e-fake-staff-csrf-token";

const HANDOFF_ID = "hnd-e2e-001";
const CONVERSATION_ID = "conv-e2e-staff-001";

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
				case_ids: ["CLM-AB12CD34", "CLM-EF56GH78"],
			},
		],
		evidence: [{ type: "transaction", ref: "TRX-001", fraud_score: "45.00" }],
		open_questions: ["El cliente aún tiene la tarjeta en su poder."],
		escalation_rules_hit: [],
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

	function summary() {
		return {
			handoff_id: HANDOFF_ID,
			conversation_id: CONVERSATION_ID,
			queue: "fraudes",
			priority: "high",
			reason: "suspected_fraud",
			status: claimed ? "claimed" : "queued",
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
					? { status: 200, json: { role: "agent", display_name: displayName } }
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
			await route.fulfill({
				status: 200,
				json: { role: "agent", display_name: displayName },
			});
			return;
		}

		// The inbox poll (D20): empty on the first call, so the second call
		// (~3s later, via `refetchInterval`) is what actually proves polling.
		if (pathname.endsWith("/staff/handoffs") && method === "GET") {
			handoffsPolls += 1;
			await route.fulfill({
				status: 200,
				json: { items: handoffsPolls > 1 ? [summary()] : [] },
			});
			return;
		}

		if (
			pathname.endsWith(`/staff/handoffs/${HANDOFF_ID}`) &&
			method === "GET"
		) {
			await route.fulfill({
				status: 200,
				json: { ...summary(), packet: packetFor() },
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
				json: { ...summary(), packet: packetFor() },
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

		if (
			/\/staff\/conversations\/[^/]+\/messages$/.test(pathname) &&
			method === "POST"
		) {
			requests.push({ pathname, method, body: request.postDataJSON() });
			messageCounter += 1;
			await route.fulfill({
				status: 202,
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
