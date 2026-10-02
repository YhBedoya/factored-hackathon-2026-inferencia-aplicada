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

/** Fixed, language-neutral welcome the mock returns when the create asks for one (D2). */
export const WELCOME_TEXT = "Welcome from Cardy (e2e)";

/** Fake `/me/*` data for the default MX customer (home spec). Display strings are what the backend would format (R4). */
const ME_CARDS = [
	{
		card_id: "card-credit",
		kind: "credit",
		last4: "6475",
		mask: "•••• 6475",
		status: "Active",
		locked: false,
	},
	{
		card_id: "card-debit",
		kind: "debit",
		last4: "1122",
		mask: "•••• 1122",
		status: "Active",
		locked: false,
	},
	{
		card_id: "card-blocked",
		kind: "credit",
		last4: "9001",
		mask: "•••• 9001",
		status: "Blocked",
		locked: true,
	},
] as const;

const ME_CARD_DETAILS: Record<string, Record<string, unknown>> = {
	"card-credit": {
		...ME_CARDS[0],
		currency: "MXN",
		expiration_date: "2028-09-30",
		expiration_date_display: "09/2028",
		credit_limit: "5000.00",
		credit_limit_display: "$5,000.00",
		current_balance: "1250.00",
		current_balance_display: "$1,250.00",
		available_credit: "3750.00",
		available_credit_display: "$3,750.00",
		days_past_due: 0,
	},
	"card-debit": {
		...ME_CARDS[1],
		currency: "MXN",
		expiration_date: "2028-09-30",
		expiration_date_display: "09/2028",
		credit_limit: null,
		credit_limit_display: null,
		current_balance: "820.50",
		current_balance_display: "$820.50",
		available_credit: null,
		available_credit_display: null,
		days_past_due: null,
	},
	"card-blocked": {
		...ME_CARDS[2],
		currency: "MXN",
		expiration_date: "2027-01-31",
		expiration_date_display: "01/2027",
		credit_limit: "2000.00",
		credit_limit_display: "$2,000.00",
		current_balance: "0.00",
		current_balance_display: "$0.00",
		available_credit: "2000.00",
		available_credit_display: "$2,000.00",
		days_past_due: 0,
	},
};

/**
 * One page of fake transactions for `cardId` (none = every card, as the
 * home's alerts ask). Dates are computed at request time so the 7-day decline
 * alert stays true. The credit card has two pages, with one income row
 * (`Payment`); the debit card one page with a `Deposit` and a `Withdrawal`;
 * the blocked card none.
 */
function txPage(cursor: string | null, cardId: string | null) {
	const base = Date.now() - 24 * 60 * 60 * 1000;
	const row = (
		id: string,
		hoursAgo: number,
		card: string,
		mask: string,
		merchant: string,
		type: string,
		status: string,
	) => {
		const at = new Date(base - hoursAgo * 60 * 60 * 1000);
		return {
			tx_id: id,
			card_id: card,
			card_mask: mask,
			occurred_at: at.toISOString(),
			date_display: at.toISOString().slice(0, 10),
			amount: "100.00",
			currency: "MXN",
			amount_display: "$100.00",
			merchant_name: merchant,
			type,
			status,
		};
	};
	if (cardId === "card-debit") {
		return {
			items: [
				row(
					"tx-d0",
					0,
					cardId,
					"•••• 1122",
					"Depósito nómina",
					"Deposit",
					"Approved",
				),
				row(
					"tx-d1",
					2,
					cardId,
					"•••• 1122",
					"Cajero Centro",
					"Withdrawal",
					"Approved",
				),
			],
			next_cursor: null,
		};
	}
	if (cardId === "card-blocked") {
		return { items: [], next_cursor: null };
	}
	const second = cursor !== null;
	const items = [0, 1, 2].map((i) => {
		const merchant = `Comercio ${second ? "B" : "A"}${i}`;
		const declined = !second && i === 0;
		const income = !second && i === 2;
		return row(
			`tx-${second ? "b" : "a"}${i}`,
			second ? 10 + i : i,
			"card-credit",
			"•••• 6475",
			merchant,
			income ? "Payment" : "Purchase",
			declined ? "Declined" : "Approved",
		);
	});
	return { items, next_cursor: second ? null : "page-2" };
}

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
			const body = request.postDataJSON() as { welcome?: boolean } | null;
			await route.fulfill({
				status: 201,
				json: {
					conversation_id: "conv-e2e-001",
					welcome: body?.welcome ? { text: WELCOME_TEXT } : null,
				},
			});
			return;
		}

		if (method === "GET" && pathname.endsWith("/me/cards")) {
			await route.fulfill({ status: 200, json: ME_CARDS });
			return;
		}

		const cardMatch = /\/me\/cards\/([^/]+)$/.exec(pathname);
		if (method === "GET" && cardMatch) {
			const details = ME_CARD_DETAILS[cardMatch[1] ?? ""];
			await route.fulfill(
				details
					? { status: 200, json: details }
					: { status: 404, json: { detail: "not_found" } },
			);
			return;
		}

		if (method === "GET" && pathname.endsWith("/me/transactions")) {
			const params = new URL(request.url()).searchParams;
			await route.fulfill({
				status: 200,
				json: txPage(params.get("cursor"), params.get("card_id")),
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
