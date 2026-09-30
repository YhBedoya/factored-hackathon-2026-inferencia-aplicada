import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, Route } from "@playwright/test";

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
	/** The status this call actually answered with, so a replay is countable (D8/D11). */
	status: number;
};

export type InstallMockApiOptions = {
	/** The only password `/auth/login` accepts; anything else answers `401 invalid_credentials`. */
	password: string;
	/** Ordered `e2e/fixtures/*.sse` file names, one consumed per `/messages` or `/confirmations/*` call that actually succeeds. */
	fixtures: string[];
	customer?: MockCustomer;
	/**
	 * D8/D11: 1-based index, counting across every `/messages` and
	 * `/confirmations/*` POST, of the one call that answers
	 * `401 session_expired` instead of succeeding. No fixture is consumed for
	 * it, so the replay gets the fixture that call would otherwise have taken.
	 */
	expireOnRequest?: number;
	/** D8: a second persona. Logging in with `altPassword` returns `altCustomer` instead of `customer`, for the "different customer" re-login path. */
	altCustomer?: MockCustomer;
	altPassword?: string;
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
	let activeCustomer = customer;
	let turnCounter = 0;
	let writeCount = 0;

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

	// D8/D11: shared by `/messages` and `/confirmations/*`. The
	// `expireOnRequest`th call across both gets a `401` and no fixture; every
	// other call (including its replay) succeeds and consumes the next one.
	async function handleWrite(
		route: Route,
		pathname: string,
		method: string,
	): Promise<void> {
		writeCount += 1;
		const body = route.request().postDataJSON();
		if (writeCount === options.expireOnRequest) {
			requests.push({ pathname, method, body, status: 401 });
			await route.fulfill({ status: 401, json: { detail: "session_expired" } });
			return;
		}
		requests.push({ pathname, method, body, status: 202 });
		enqueueNextFixture();
		await route.fulfill({ status: 202, json: { turn_id: nextTurnId() } });
	}

	await page.route("**/api/v1/**", async (route) => {
		const request = route.request();
		const { pathname } = new URL(request.url());
		const method = request.method();

		if (pathname.endsWith("/auth/me") && method === "GET") {
			await route.fulfill(
				loggedIn
					? { status: 200, json: activeCustomer }
					: { status: 401, json: { detail: "session_expired" } },
			);
			return;
		}

		if (pathname.endsWith("/auth/refresh") && method === "POST") {
			// D8: this mock only ever exercises the expired-session path, so
			// there is no silent-refresh success to model here.
			await route.fulfill({ status: 401, json: { detail: "session_expired" } });
			return;
		}

		if (pathname.endsWith("/auth/login") && method === "POST") {
			const body = request.postDataJSON() as { password?: string };
			if (body.password === options.password) {
				activeCustomer = customer;
			} else if (options.altCustomer && body.password === options.altPassword) {
				activeCustomer = options.altCustomer;
			} else {
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
			await route.fulfill({ status: 200, json: activeCustomer });
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
			await handleWrite(route, pathname, method);
			return;
		}

		if (/\/confirmations\/[^/]+$/.test(pathname) && method === "POST") {
			await handleWrite(route, pathname, method);
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
