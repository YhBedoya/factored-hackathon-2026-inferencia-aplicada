import { expect, test } from "@playwright/test";

import { installMockStaffApi } from "./mock-staff-api";

// B3 "rendered in the browser" (D11-D13), ES happy path (spec §Test list,
// test 12). Same fake-staff-session convention as `staff.es.spec.ts`: no
// real backend, no LLM, no network call leaves this process.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-staff-pass";

test("staff login, list, filter by intent, expand a turn's why", async ({
	page,
}) => {
	await installMockStaffApi(page, { password: PASSWORD });

	// 1. staff login
	await page.goto("/staff/login");
	await page.getByTestId("staff-login-username").fill("agent.reclamos");
	await page.getByTestId("staff-login-password").fill(PASSWORD);
	await page.getByTestId("staff-login-submit").click();
	await page.waitForURL("**/staff");

	// 2. open /staff/conversations, see N rows
	await page.goto("/staff/conversations");
	const rows = page.getByTestId("conversation-row");
	await expect(rows).toHaveCount(3);

	// 3. filter by intent: the count changes and the URL carries the param
	await page.getByTestId("filter-intent").selectOption("card_status");
	await expect(rows).toHaveCount(1);
	await expect(page).toHaveURL(/intent=card_status/);

	// 4. open a conversation and expand a turn
	await page.getByTestId("conversation-row-link").first().click();
	await page.waitForURL("**/staff/conversations/**");
	const turns = page.getByTestId("turn-details");
	await expect(turns).toHaveCount(2);
	await turns.first().locator("summary").click();

	// 5. NLU, rules, sources, the policy hash and the Langfuse link are visible
	const firstTurn = turns.first();
	await expect(firstTurn.getByTestId("turn-nlu")).toBeVisible();
	await expect(firstTurn.getByTestId("turn-rule")).toBeVisible();
	await expect(firstTurn.getByTestId("turn-source")).toBeVisible();
	await expect(firstTurn.getByTestId("turn-policy-version")).toBeVisible();
	await expect(firstTurn.getByTestId("turn-langfuse-link")).toBeVisible();

	// 6. the null-link turn shows no link
	await turns.nth(1).locator("summary").click();
	await expect(turns.nth(1).getByTestId("turn-langfuse-link")).toHaveCount(0);
});
