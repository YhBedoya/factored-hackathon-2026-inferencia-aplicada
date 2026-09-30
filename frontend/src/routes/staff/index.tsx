import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, redirect } from "@tanstack/react-router";

import { InboxList } from "@/components/staff/InboxList";
import { listStaffHandoffs, staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// D5/D20: only a staff session reaches the inbox. `staffMe()` mirrors
// `chat.tsx`'s customer guard -- a missing/expired session is sent to
// `/staff/login` before the route renders anything.
export const Route = createFileRoute("/staff/")({
	beforeLoad: async () => {
		const agent = await staffMe();
		if (!agent) {
			throw redirect({ to: "/staff/login" });
		}
	},
	component: StaffInboxPage,
});

const HANDOFFS_QUERY_KEY = ["staff", "handoffs"] as const;

function StaffInboxPage() {
	const { t } = useI18n();
	const { data } = useQuery({
		queryKey: HANDOFFS_QUERY_KEY,
		queryFn: listStaffHandoffs,
		// D20: there is no inbox SSE, only a poll.
		refetchInterval: 3000,
	});

	return (
		<div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-6 py-10">
			<h1 className="font-heading text-2xl text-foreground">
				{t("staff.inbox.title")}
			</h1>
			{/* D13: traceability screens, built against the spec's proposed shapes (D12). */}
			<Link to="/staff/conversations" className="self-start text-sm underline">
				{t("staff.conversations.nav_link")}
			</Link>
			<InboxList items={data ?? []} />
		</div>
	);
}
