import { defineConfig, devices } from "@playwright/test";

// B5 (spec D7): Playwright against the *built* frontend (`preview`), with the
// API mocked by `page.route` and scripted `.sse` fixtures standing in for the
// fake LLM. There is no real backend and no Bedrock/Anthropic call anywhere
// in this run.
export default defineConfig({
	testDir: "e2e",
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: 0,
	use: {
		baseURL: "http://localhost:4173",
	},
	projects: [
		{
			name: "chromium",
			use: { ...devices["Desktop Chrome"] },
		},
	],
	webServer: {
		command: "npm run preview -- --port 4173 --strictPort",
		url: "http://localhost:4173",
		reuseExistingServer: !process.env.CI,
	},
});
