import { expect, test } from "@playwright/test";

import { installMockApi, WELCOME_TEXT } from "./mock-api";

// Banking home against the mock API (spec §Test list). Fake credentials only,
// no LLM: the `.sse` fixtures are the fake one.
test.use({ locale: "es-ES" });

const PASSWORD = "demo-pass";

async function login(page: import("@playwright/test").Page) {
	await page.goto("/login");
	await page.getByTestId("login-document-number").fill("12345678");
	await page.getByTestId("login-password").fill(PASSWORD);
	await page.getByTestId("login-submit").click();
	await page.waitForURL("**/home");
}

test("login lands on /home with cards, balance and paged transactions", async ({
	page,
}) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await login(page);

	await expect(page.getByTestId("home-card")).toHaveCount(3);
	await expect(page.getByTestId("home-balance")).toContainText("$1,250.00");
	await expect(page.getByTestId("home-tx-row")).toHaveCount(3);

	await page.getByTestId("home-tx-more").click();
	await expect(page.getByTestId("home-tx-row")).toHaveCount(6);
	await expect(page.getByTestId("home-tx-more")).toHaveCount(0);
});

test("Cardy panel opens on /home with a welcome and answers a message", async ({
	page,
}) => {
	await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["card-info-ask.sse"],
	});
	await login(page);

	await page.getByTestId("cardy-launcher").click();
	await expect(page.getByTestId("cardy-panel")).toBeVisible();
	await expect(page).toHaveURL(/\/home$/);
	await expect(page.getByTestId("message-bot")).toHaveCount(1);
	await expect(page.getByTestId("message-bot")).toContainText(WELCOME_TEXT);

	await page.getByTestId("composer-input").fill("¿cuánto debo?");
	await page.getByTestId("composer-send").click();
	await expect(page.getByTestId("message-bot")).toHaveCount(2);
});

test("visiting /home without a session ends on /login", async ({ page }) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await page.goto("/home");
	await page.waitForURL("**/login");
});
