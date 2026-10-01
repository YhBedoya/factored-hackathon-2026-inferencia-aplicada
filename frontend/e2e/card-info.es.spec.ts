import { expect, test } from "@playwright/test";

import es from "../src/lib/i18n/es.json" with { type: "json" };
import pt from "../src/lib/i18n/pt.json" with { type: "json" };
import { installMockApi } from "./mock-api";

// B2, B3, B4 picker, B1 language (end-of-day steps 1-2, spec §Test list).
// Fake credentials only (plan §Risks 12): no real persona, no network call
// leaves this process, no LLM.
test.use({ locale: "es-ES" });

const PASSWORD = "demo-pass";
const CREDIT_LABEL = "Crédito •••• 6475 · Activa";

test("ES chrome, card picker, language toggle and logout", async ({ page }) => {
	const mock = await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["card-info-ask.sse", "card-info-answer.sse"],
	});

	await page.goto("/login");
	await page.getByTestId("login-document-number").fill("12345678");
	await page.getByTestId("login-password").fill(PASSWORD);
	await page.getByTestId("login-submit").click();
	await page.waitForURL("**/home");
	await page.goto("/chat");

	await page
		.getByTestId("composer-input")
		.fill("¿cuánto debo de mi tarjeta de crédito?");
	await page.getByTestId("composer-send").click();

	const option = page
		.getByTestId("card-picker-option")
		.filter({ hasText: CREDIT_LABEL });
	await expect(option).toBeVisible();
	await option.click();

	expect(mock.requests.at(-1)?.body).toEqual({ text: CREDIT_LABEL });
	await expect(page.getByTestId("message-bot").last()).toContainText(
		"1,250.00",
	);

	// D10: the toggle changes only the UI chrome, checked against the real
	// dictionaries rather than a hardcoded string.
	await expect(page.getByTestId("logout")).toHaveText(es["shell.logout"]);
	await page.getByTestId("lang-pt").click();
	await expect(page.getByTestId("logout")).toHaveText(pt["shell.logout"]);

	await page.getByTestId("logout").click();
	await page.waitForURL("**/login");

	await page.goto("/chat");
	await page.waitForURL("**/login");
});
