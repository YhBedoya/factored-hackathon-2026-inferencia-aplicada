import { expect, type Page, test } from "@playwright/test";

import { installMockApi, type MockCustomer } from "./mock-api";

// B2 "Playwright covers expiry -> resume" (spec §Test list, items 4-5). No
// real backend, no LLM: the confirm POST is the one call the mock 401s, and
// the two fixed `.sse` fixtures are the fake LLM either side of it.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-pass";
const ALT_PASSWORD = "otra-clave";
const TOKEN_ID = "tok-e2e-301";

const ALT_CUSTOMER: MockCustomer = {
	role: "customer",
	login_hint: "DNI ••••321",
	display_name: "Marco Ruiz",
	country: "CO",
	customer_status: "Active",
};

async function login(
	page: Page,
	password: string,
	documentNumber: string,
): Promise<void> {
	await page.getByTestId("login-document-number").fill(documentNumber);
	await page.getByTestId("login-password").fill(password);
	await page.getByTestId("login-submit").click();
}

test("expiry -> modal -> re-login -> confirmation resumes", async ({
	page,
}) => {
	const mock = await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["expiry-confirm.sse", "expiry-verified.sse"],
		// The confirm POST (write #2, after the opening `/messages` call) is
		// the one that expires.
		expireOnRequest: 2,
	});

	await page.goto("/login");
	await login(page, PASSWORD, "12345678");
	await page.waitForURL("**/home");
	await page.goto("/chat");

	await page.getByTestId("composer-input").fill("quiero bloquear mi tarjeta");
	await page.getByTestId("composer-send").click();

	const confirmCard = page.getByTestId("confirm-card");
	await expect(confirmCard).toBeVisible();
	await confirmCard.getByTestId("confirm-accept").click();

	const modal = page.getByTestId("session-expired-modal");
	await expect(modal).toBeVisible();

	await login(page, PASSWORD, "12345678");
	await expect(modal).toBeHidden();

	const verifiedReply = page.getByTestId("message-bot").last();
	await expect(verifiedReply).toContainText("bloqueada temporalmente");

	const confirmationCalls = mock.requests.filter((r) =>
		r.pathname.includes(`/confirmations/${TOKEN_ID}`),
	);
	expect(confirmationCalls.map((r) => r.status)).toEqual([401, 202]);
});

test("different customer drops the held request", async ({ page }) => {
	const mock = await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["expiry-confirm.sse", "expiry-verified.sse"],
		expireOnRequest: 2,
		altCustomer: ALT_CUSTOMER,
		altPassword: ALT_PASSWORD,
	});

	await page.goto("/login");
	await login(page, PASSWORD, "12345678");
	await page.waitForURL("**/home");
	await page.goto("/chat");

	await page.getByTestId("composer-input").fill("quiero bloquear mi tarjeta");
	await page.getByTestId("composer-send").click();

	const confirmCard = page.getByTestId("confirm-card");
	await expect(confirmCard).toBeVisible();
	await confirmCard.getByTestId("confirm-accept").click();

	const modal = page.getByTestId("session-expired-modal");
	await expect(modal).toBeVisible();

	await login(page, ALT_PASSWORD, "87654321");
	await expect(modal).toBeHidden();

	// D8: dropped, not replayed -- a fresh chat: only the new welcome (D2).
	await expect(page.getByTestId("message-bot")).toHaveCount(1);
	await expect(page.getByTestId("message-customer")).toHaveCount(0);
	await expect(page.getByTestId("composer-input")).toBeEnabled();

	const confirmationCalls = mock.requests.filter((r) =>
		r.pathname.includes(`/confirmations/${TOKEN_ID}`),
	);
	expect(confirmationCalls.map((r) => r.status)).toEqual([401]);
});
