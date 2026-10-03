import { createRootRoute, Outlet } from "@tanstack/react-router";

import { AppShell } from "@/components/layout/AppShell";

// The shell (stars, wordmark, language toggle, greeting/logout) wraps every
// route. Route-specific UI is the `Outlet`.
export const Route = createRootRoute({
	component: () => (
		<AppShell>
			<Outlet />
		</AppShell>
	),
});
