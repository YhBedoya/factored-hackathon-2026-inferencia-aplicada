import { expect, test } from "@playwright/test";

import { installMockStaffApi } from "./mock-staff-api";

// B3 "rendered in the browser" (D11-D13), ES happy path (spec §Test list,
// test 12). Same fake-staff-session convention as `staff.es.spec.ts`: no
// real backend, no LLM, no network call leaves this process.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-staff-pass";

test("staff login, list, filter by intent, select a turn's why", async ({
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
	// `handoff:reclamos` is labeled by its prefix, the queue by the dictionary
	await expect(rows.first()).toContainText("Escalado");
	await expect(rows.first()).toContainText("Reclamos");

	// 3b. escalation takes `none` / `any` / a queue, not a handoff reason
	await page.getByTestId("filter-intent").selectOption("");
	await page.getByTestId("filter-escalation").selectOption("none");
	await expect(rows).toHaveCount(2);
	await expect(page).toHaveURL(/escalation=none/);
	await page.getByTestId("filter-escalation").selectOption("");
	await page.getByTestId("filter-intent").selectOption("card_status");
	await expect(rows).toHaveCount(1);

	// 4. open a conversation: the turn list shows every turn, the first one
	// is selected and its "why" is on screen
	await page.getByTestId("conversation-row-link").first().click();
	await page.waitForURL("**/staff/conversations/**");
	const turnItems = page.getByTestId("turn-item");
	await expect(turnItems).toHaveCount(2);
	const detail = page.getByTestId("turn-details");
	await expect(detail).toHaveCount(1);

	// 5. NLU, rules, sources, the policy hash and the Langfuse link are visible
	await expect(detail.getByTestId("turn-nlu")).toBeVisible();
	await expect(detail.getByTestId("turn-rule").first()).toBeVisible();
	await expect(detail.getByTestId("turn-source").first()).toBeVisible();
	await expect(detail.getByTestId("turn-policy-version")).toBeVisible();
	await expect(detail.getByTestId("turn-langfuse-link")).toBeVisible();

	// 6. selecting the null-link turn shows no link
	await turnItems.nth(1).click();
	await expect(turnItems.nth(1)).toHaveAttribute("aria-current", "true");
	await expect(detail.getByTestId("turn-langfuse-link")).toHaveCount(0);
});
