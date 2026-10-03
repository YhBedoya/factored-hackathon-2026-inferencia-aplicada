import { expect, test } from "@playwright/test";

import { installMockStaffApi } from "./mock-staff-api";

// B4 "rendered in the browser", D20, D21, ES happy path (spec §Test list).
// Fake staff credentials only (same convention as `unrecognized.es.spec.ts`):
// no real backend, no LLM, no network call leaves this process.
test.use({ locale: "es-MX" });

const PASSWORD = "demo-staff-pass";
const AGENT_NAME = "Sofía";

test("login, live inbox, claim, packet, agent chat, return to bot", async ({
	page,
}) => {
	const mock = await installMockStaffApi(page, {
		password: PASSWORD,
		agentDisplayName: AGENT_NAME,
	});

	await page.goto("/staff/login");
	await page.getByTestId("staff-login-username").fill("agent.fraudes");
	await page.getByTestId("staff-login-password").fill(PASSWORD);
	await page.getByTestId("staff-login-submit").click();
	await page.waitForURL("**/staff");

	// The first poll is empty; the queued Fraudes case only shows up after
	// the second one, ~3s later (`refetchInterval`), which is what proves
	// this is a poll and not a one-shot fetch (D20).
	await expect(page.getByTestId("inbox-item")).toHaveCount(0);
	await expect(page.getByTestId("inbox-item-queue")).toHaveText("Fraudes", {
		timeout: 10000,
	});

	// Claiming from the inbox row goes straight to the case chat.
	await page.getByTestId("inbox-claim").click();
	await page.waitForURL("**/staff/handoffs/**");

	const packet = page.getByTestId("packet-view");
	await expect(packet).toBeVisible();
	await expect(packet.getByTestId("packet-verified-fact")).toHaveCount(1);
	await expect(packet.getByTestId("packet-action-case-id")).toHaveCount(2);
	await expect(packet.getByTestId("packet-evidence")).toHaveCount(1);
	await expect(packet.getByTestId("packet-open-question")).toHaveCount(1);

	await page.getByTestId("agent-chat-input").fill("Ya revisamos tu caso.");
	await page.getByTestId("agent-chat-send").click();

	await expect
		.poll(() => mock.requests.at(-1)?.pathname)
		.toContain("/messages");
	expect(mock.requests.at(-1)?.body).toEqual({
		text: "Ya revisamos tu caso.",
	});

	await page.getByTestId("return-handoff").click();

	await expect.poll(() => mock.requests.at(-1)?.pathname).toContain("/return");
});
