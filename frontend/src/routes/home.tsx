import { createFileRoute, redirect } from "@tanstack/react-router";

import { HomeView } from "@/components/home/HomeView";
import { me } from "@/lib/api";

// A9: same guard as `/chat`. The session cookie carries the customer; every
// `/me/*` request below rides on it and none sends a `customer_id` (R1).
export const Route = createFileRoute("/home")({
	beforeLoad: async () => {
		const customer = await me();
		if (!customer) {
			throw redirect({ to: "/login" });
		}
	},
	component: HomeView,
});
