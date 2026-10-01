import { createFileRoute, redirect } from "@tanstack/react-router";

import { ChatView } from "@/components/chat/ChatView";
import { me } from "@/lib/api";

// R1/D3-B D12: the chat guard is the one place `me()` decides who reaches the
// conversation. Nothing here ever sends a `customer_id`; the session cookie
// carries it, and every request below rides on that same cookie.
export const Route = createFileRoute("/chat")({
	beforeLoad: async () => {
		const customer = await me();
		if (!customer) {
			throw redirect({ to: "/login" });
		}
	},
	component: () => <ChatView />,
});
