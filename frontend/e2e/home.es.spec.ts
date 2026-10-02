import { expect, test } from "@playwright/test";

import es from "../src/lib/i18n/es.json" with { type: "json" };
import { installMockApi, WELCOME_TEXT } from "./mock-api";

// Banking home against the mock API (spec §Test list). Fake credentials only,
// no LLM: the `.sse` fixtures are the fake one.
test.use({ locale: "es-ES" });

const PASSWORD = "demo-pass";

async function login(page: import("@playwright/test").Page) {
	await page.goto("/?login=1");
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

	// The first card is selected: its available credit and its movements.
	await expect(page.getByTestId("home-card")).toHaveCount(3);
	await expect(page.getByTestId("home-balance-amount")).toHaveText("$3,750.00");
	await expect(page.getByTestId("home-tx-row")).toHaveCount(3);

	await page.getByTestId("home-tx-more").click();
	await expect(page.getByTestId("home-tx-row")).toHaveCount(6);
	await expect(page.getByTestId("home-tx-more")).toHaveCount(0);
});

test("selecting the debit card shows its balance; chips filter; balances hide", async ({
	page,
}) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await login(page);

	await expect(page.getByTestId("home-tx-row")).toHaveCount(3);
	await page.getByTestId("home-tx-filter-out").click();
	await expect(page.getByTestId("home-tx-row")).toHaveCount(2);
	await page.getByTestId("home-tx-filter-in").click();
	await expect(page.getByTestId("home-tx-row")).toHaveCount(1);
	await expect(page.getByTestId("home-tx-row")).toContainText("Comercio A2");

	// A1/ADR-032: a debit card shows its available balance.
	await page.getByTestId("home-card").nth(1).click();
	await expect(page.getByTestId("home-balance-amount")).toHaveText("$820.50");
	await expect(page.getByTestId("home-tx-row")).toHaveCount(2);
	await expect(page.getByTestId("home-tx-row").first()).toContainText(
		"Depósito nómina",
	);

	await page.getByTestId("home-toggle-balances").click();
	await expect(page.getByTestId("home-balance-amount")).toHaveText("•••••••");
	await expect(page.getByTestId("home-cards")).not.toContainText("$820.50");
	await expect(page.getByTestId("home-transactions")).not.toContainText(
		"$100.00",
	);
});

test("the bell lists the alerts and a movement asks Cardy about itself", async ({
	page,
}) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await login(page);

	// The blocked card and the recent decline.
	await expect(page.getByTestId("home-bell-count")).toHaveText("2");
	await page.getByTestId("home-bell").click();
	await expect(page.getByTestId("home-alert")).toHaveCount(2);
	await page.getByTestId("home-alert").first().click();
	await expect(page.getByTestId("cardy-panel")).toBeVisible();
	await expect(page.getByTestId("composer-input")).toHaveValue(
		es["home.ask.status.Blocked"].replace("{mask}", "•••• 9001"),
	);
	await page
		.getByTestId("cardy-panel")
		.getByRole("button", { name: es["home.cardy.close"], exact: true })
		.click();

	await page.getByTestId("home-tx-row").nth(1).getByRole("button").click();
	await expect(page.getByTestId("home-tx-details")).toContainText("tx-a1");
	await page.getByTestId("home-tx-ask").click();
	await expect(page.getByTestId("composer-input")).toHaveValue(/Comercio A1/);
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

	// Closing ends that conversation: reopening starts a new one, and Cardy
	// greets again instead of showing an empty chat.
	await page
		.getByTestId("cardy-panel")
		.getByRole("button", { name: es["home.cardy.close"], exact: true })
		.click();
	await expect(page.getByTestId("cardy-panel")).toHaveCount(0);
	await page.getByTestId("cardy-launcher").click();
	await expect(page.getByTestId("message-bot")).toHaveCount(1);
	await expect(page.getByTestId("message-bot")).toContainText(WELCOME_TEXT);
});

test("minimizing the Cardy panel keeps the conversation", async ({ page }) => {
	await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["card-info-ask.sse"],
	});
	await login(page);

	await page.getByTestId("cardy-launcher").click();
	await page.getByTestId("composer-input").fill("¿cuánto debo?");
	await page.getByTestId("composer-send").click();
	await expect(page.getByTestId("message-bot")).toHaveCount(2);

	await page
		.getByTestId("cardy-panel")
		.getByRole("button", { name: es["home.cardy.minimize"], exact: true })
		.click();
	await expect(page.getByTestId("cardy-panel")).toBeHidden();
	await page.getByTestId("cardy-launcher").click();
	await expect(page.getByTestId("message-customer")).toHaveCount(1);
	await expect(page.getByTestId("message-bot")).toHaveCount(2);
	await expect(page.getByTestId("composer-input")).toBeFocused();
});

test("visiting /home without a session opens the login pop-up on the landing", async ({
	page,
}) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await page.goto("/home");
	await page.waitForURL("**/?login=true");
	await expect(page.getByTestId("login-dialog")).toBeVisible();
});

test("the landing's login button opens the pop-up without leaving /", async ({
	page,
}) => {
	await installMockApi(page, { password: PASSWORD, fixtures: [] });
	await page.goto("/");
	await page.getByRole("link", { name: es["landing.cta"] }).first().click();
	await expect(page.getByTestId("login-dialog")).toBeVisible();
	expect(new URL(page.url()).pathname).toBe("/");
	await page.keyboard.press("Escape");
	await expect(page.getByTestId("login-dialog")).toHaveCount(0);
});
