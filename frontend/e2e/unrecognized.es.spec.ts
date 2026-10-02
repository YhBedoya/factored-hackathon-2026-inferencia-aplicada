import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

// B3 "rendered in the browser", D13, D21, ES happy path (spec §Test list).
// Fake credentials only (plan §Risks 12): no real persona, no network call
// leaves this process, no LLM. The three fixed `.sse` fixtures are the fake
// LLM, one per `/messages` or `/confirmations/*` call.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-pass";
const TOKEN_ID = "tok-e2e-201";
const AGENT_NAME = "Sofía";

test("checkboxes pick, confirm plan, handoff banner, mode switch", async ({
	page,
}) => {
	const mock = await installMockApi(page, {
		password: PASSWORD,
		fixtures: [
			"unrecognized-pick.sse",
			"unrecognized-confirm.sse",
			"unrecognized-banner.sse",
		],
	});

	await page.goto("/?login=1");
	await page.getByTestId("login-document-number").fill("12345678");
	await page.getByTestId("login-password").fill(PASSWORD);
	await page.getByTestId("login-submit").click();
	await page.waitForURL("**/home");
	await page.goto("/chat");

	await expect(page.getByTestId("mode-indicator")).toHaveText("Cardy");

	await page.getByTestId("composer-input").fill("no reconozco estas compras");
	await page.getByTestId("composer-send").click();

	const options = page.getByTestId("transaction-option");
	await expect(options).toHaveCount(3);

	const continueButton = page.getByTestId("transaction-list-continue");
	await expect(continueButton).toBeDisabled();

	await options.nth(0).check();
	await options.nth(1).check();
	await expect(continueButton).toBeEnabled();
	await continueButton.click();
	await expect(continueButton).toBeDisabled();

	expect(mock.requests.at(-1)?.body).toEqual({
		selection: { tx_ids: ["TRX-001", "TRX-002"] },
	});

	const confirmCard = page.getByTestId("confirm-card");
	await expect(confirmCard).toBeVisible();
	await expect(confirmCard.getByTestId("confirm-step")).toHaveCount(2);

	await confirmCard.getByTestId("confirm-accept").click();

	const last = mock.requests.at(-1);
	expect(last?.pathname).toContain(`/confirmations/${TOKEN_ID}`);
	expect(last?.body).toEqual({ decision: "confirm" });

	const banner = page.getByTestId("handoff-banner");
	await expect(banner).toBeVisible();
	await expect(banner).toContainText("Fraudes");
	await expect(banner.getByTestId("handoff-case-id")).toHaveCount(2);
	await expect(banner.getByTestId("handoff-case-id").first()).toHaveText(
		"CLM-AB12CD34",
	);

	await expect(page.getByTestId("mode-indicator")).toHaveText(AGENT_NAME);
});
