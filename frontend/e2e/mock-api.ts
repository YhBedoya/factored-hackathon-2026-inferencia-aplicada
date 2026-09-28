import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

const FIXTURES_DIR = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	"fixtures",
);

const CSRF_COOKIE_NAME = "csrf_token";
const CSRF_COOKIE_VALUE = "e2e-fake-csrf-token";

export type MockCustomer = {
	role: "customer";
	login_hint: string;
	display_name: string;
	country: "MX" | "CO" | "AR";
	customer_status: "Active" | "Inactive" | "Suspended" | "Closed";
};

/** A fake customer only: R1 means the frontend never sends `customer_id`, so this mock never models one either. */
const DEFAULT_CUSTOMER: MockCustomer = {
	role: "customer",
	login_hint: "DNI ••••678",
	display_name: "Ana Torres",
	country: "MX",
	customer_status: "Active",
};

export type RecordedRequest = {
	pathname: string;
	method: string;
	body: unknown;
};

export type InstallMockApiOptions = {
	/** The only password `/auth/login` accepts; anything else answers `401 invalid_credentials`. */
	password: string;
	/** Ordered `e2e/fixtures/*.sse` file names, one consumed per `/messages` or `/confirmations/*` call. */
	fixtures: string[];
	customer?: MockCustomer;
};

export type MockApi = {
	/** Every `/messages` and `/confirmations/*` body, in call order, for the click-equals-typing assertions (D5). */
	requests: RecordedRequest[];
};

/**
 * Stateful `page.route` mock of `/api/v1/**` (spec D7). No real backend and
 * no LLM run anywhere: the fixed `.sse` fixtures are the fake LLM.
 *
 * The stream `GET` always fulfills immediately with whatever is queued (maybe
 * nothing) and closes; `retry: 200` makes `EventSource` reconnect on its own
 * every ~200ms until a fixture has been enqueued by a `POST`, which is what
 * the plan's "EventSource under `page.route`" risk calls draining the queue.
 */
export async function installMockApi(
	page: Page,
	options: InstallMockApiOptions,
): Promise<MockApi> {
	const customer = options.customer ?? DEFAULT_CUSTOMER;
	const requests: RecordedRequest[] = [];
	const fixtureQueue = [...options.fixtures];
	const pendingFrames: string[] = [];
	let loggedIn = false;
	let turnCounter = 0;

	function nextTurnId(): string {
		turnCounter += 1;
		return `turn-e2e-${turnCounter}`;
	}

	function enqueueNextFixture(): void {
		const name = fixtureQueue.shift();
		if (!name) {
			return;
		}
		pendingFrames.push(readFileSync(path.join(FIXTURES_DIR, name), "utf-8"));
	}

	await page.route("**/api/v1/**", async (route) => {
		const request = route.request();
		const { pathname } = new URL(request.url());
		const method = request.method();

		if (pathname.endsWith("/auth/me") && method === "GET") {
			await route.fulfill(
				loggedIn
					? { status: 200, json: customer }
					: { status: 401, json: { detail: "session_expired" } },
			);
			return;
		}

		if (pathname.endsWith("/auth/login") && method === "POST") {
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
			await route.fulfill({ status: 200, json: customer });
			return;
		}

		if (pathname.endsWith("/auth/logout") && method === "POST") {
			loggedIn = false;
			await route.fulfill({ status: 204 });
			return;
		}

		if (pathname.endsWith("/conversations") && method === "POST") {
			await route.fulfill({
				status: 201,
				json: { conversation_id: "conv-e2e-001" },
			});
			return;
		}

		if (/\/messages$/.test(pathname) && method === "POST") {
			requests.push({ pathname, method, body: request.postDataJSON() });
			enqueueNextFixture();
			await route.fulfill({ status: 202, json: { turn_id: nextTurnId() } });
			return;
		}

		if (/\/confirmations\/[^/]+$/.test(pathname) && method === "POST") {
			requests.push({ pathname, method, body: request.postDataJSON() });
			enqueueNextFixture();
			await route.fulfill({ status: 202, json: { turn_id: nextTurnId() } });
			return;
		}

		if (/\/stream$/.test(pathname) && method === "GET") {
			const drained = pendingFrames.splice(0).join("");
			await route.fulfill({
				status: 200,
				contentType: "text/event-stream",
				body: `retry: 200\n\n: connected\n\n${drained}`,
			});
			return;
		}

		await route.fulfill({ status: 404, json: { detail: "not_found" } });
	});

	return { requests };
}
