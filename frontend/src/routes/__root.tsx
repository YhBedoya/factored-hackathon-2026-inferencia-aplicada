import { createRootRoute, Outlet } from "@tanstack/react-router";

// No product UI lives here yet — this just wires the route tree so the
// router and the empty shell render. Layout/chrome is added by a later card.
export const Route = createRootRoute({
	component: () => <Outlet />,
});
