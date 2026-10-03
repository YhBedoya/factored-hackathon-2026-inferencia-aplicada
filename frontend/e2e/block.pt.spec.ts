import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

// B4 chips and confirm, D1 shape, PT happy path (spec §Test list). Fake
// credentials only (plan §Risks 12): no real persona, no network call leaves
// this process, no LLM. OTP has no leg here: it is proven at the A6 pairing
// (human decision), not by this spec.
test.use({ locale: "pt-BR" });

const PASSWORD = "demo-pass";
const TEMP_LOCK_LABEL = "Bloqueio temporário";
const TOKEN_ID = "tok-e2e-001";

test("quick reply, gold confirm card, verified cyan reply", async ({
	page,
}) => {
	const mock = await installMockApi(page, {
		password: PASSWORD,
		fixtures: ["block-clarify.sse", "block-confirm.sse", "block-verified.sse"],
	});

	await page.goto("/?login=1");
	await page.getByTestId("login-document-number").fill("12345678");
	await page.getByTestId("login-password").fill(PASSWORD);
	await page.getByTestId("login-submit").click();
	await page.waitForURL("**/home");
	await page.goto("/chat");

	await page.getByTestId("composer-input").fill("quero bloquear meu cartão");
	await page.getByTestId("composer-send").click();

	const chip = page
		.getByTestId("quick-reply-option")
		.filter({ hasText: TEMP_LOCK_LABEL });
	await expect(chip).toBeVisible();
	await chip.click();
	expect(mock.requests.at(-1)?.body).toEqual({ text: TEMP_LOCK_LABEL });

	const confirmCard = page.getByTestId("confirm-card");
	await expect(confirmCard).toBeVisible();
	await expect(confirmCard).toHaveCSS("border-color", "rgb(245, 198, 107)");
	await expect(confirmCard.getByTestId("confirm-step")).toHaveCount(1);

	await confirmCard.getByTestId("confirm-accept").click();

	const last = mock.requests.at(-1);
	expect(last?.pathname).toContain(`/confirmations/${TOKEN_ID}`);
	expect(last?.body).toEqual({ decision: "confirm" });

	const verifiedReply = page.getByTestId("message-bot").last();
	await expect(verifiedReply).toContainText("bloqueado temporariamente");
	await expect(verifiedReply).toHaveCSS("border-color", "rgb(61, 214, 224)");
});
