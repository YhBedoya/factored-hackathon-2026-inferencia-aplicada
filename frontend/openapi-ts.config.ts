import { defineConfig } from "@hey-api/openapi-ts";

// D19: `make client` runs `@hey-api/openapi-ts` against the backend's own
// OpenAPI document, through the dev Nginx proxy (same host/port a browser
// uses), into a generated, never-hand-edited client. The app and API are
// same-origin behind Nginx (`/` -> frontend, `/api/` -> backend), so the
// generated client must not bake in a host: `baseUrl: false` on the fetch
// client plugin disables that (the input URL would otherwise become the
// literal base URL).
export default defineConfig({
	input: "http://localhost/api/v1/openapi.json",
	output: "src/client",
	plugins: [{ name: "@hey-api/client-fetch", baseUrl: false }],
});
