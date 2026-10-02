import { expect, test } from "@playwright/test";

import { REAL_CONVERSATION_ID } from "./fixtures/analytics-summary";
import { installMockStaffApi } from "./mock-staff-api";

// Analytics dashboard, admin-only (D14), ES UI. Fake credentials, mocked
// staff API: no real backend, no LLM.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-staff-pass";

async function login(page: import("@playwright/test").Page, user: string) {
	await page.goto("/staff/login");
	await page.getByTestId("staff-login-username").fill(user);
	await page.getByTestId("staff-login-password").fill(PASSWORD);
	await page.getByTestId("staff-login-submit").click();
	await page.waitForURL("**/staff");
}

test("admin sees the dashboard, mock notices and the real-row link", async ({
	page,
}) => {
	await installMockStaffApi(page, { password: PASSWORD, role: "admin" });
	await login(page, "admin");

	await page.getByTestId("analytics-nav-link").click();
	await page.waitForURL("**/staff/analytics");

	for (const tile of [
		"interactions",
		"resolution",
		"escalation",
		"cost",
		"messages",
		"negative",
	]) {
		await expect(page.getByTestId(`analytics-tile-${tile}`)).toBeVisible();
	}
	for (const chart of [
		"per-day",
		"intents",
		"escalations",
		"sentiment",
		"cost",
	]) {
		await expect(page.getByTestId(`analytics-chart-${chart}`)).toBeVisible();
	}
	await expect(page.getByTestId("analytics-recent-row")).toHaveCount(2);
	await expect(page.getByTestId("analytics-mock-badge")).toBeVisible();
	await expect(page.getByTestId("analytics-mock-footer")).toBeVisible();
	// Only the real row links to its conversation.
	await expect(page.getByTestId("analytics-recent-link")).toHaveCount(1);

	await page.getByTestId("analytics-filter-source").selectOption("real");
	await expect(page.getByTestId("analytics-mock-badge")).toHaveCount(0);
	await expect(page.getByTestId("analytics-mock-footer")).toHaveCount(0);
	await expect(page.getByTestId("analytics-recent-row")).toHaveCount(1);

	await page.getByTestId("analytics-recent-link").click();
	await page.waitForURL(`**/staff/conversations/${REAL_CONVERSATION_ID}`);
});

test("agent has no analytics link and is bounced back to the inbox", async ({
	page,
}) => {
	await installMockStaffApi(page, { password: PASSWORD });
	await login(page, "agent.fraudes");

	await expect(page.getByTestId("analytics-nav-link")).toHaveCount(0);
	await page.goto("/staff/analytics");
	await page.waitForURL("**/staff");
	expect(new URL(page.url()).pathname).toBe("/staff");
});
