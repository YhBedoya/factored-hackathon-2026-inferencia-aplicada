import { createFileRoute } from "@tanstack/react-router";

// Empty shell for the `/` route. No product UI: this task only proves the
// toolchain (router + query client) renders.
export const Route = createFileRoute("/")({
	component: () => null,
});
