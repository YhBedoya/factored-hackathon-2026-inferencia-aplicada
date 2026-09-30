import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";

import { TurnTimeline } from "@/components/staff/TurnTimeline";
import { staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { getConversationTimeline } from "@/lib/traceability";

// D5/D20-style guard, same as `staff/index.tsx` and `staff/handoffs.$handoffId.tsx`.
export const Route = createFileRoute("/staff/conversations/$conversationId")({
	beforeLoad: async () => {
		const agent = await staffMe();
		if (!agent) {
			throw redirect({ to: "/staff/login" });
		}
	},
	component: ConversationTimelinePage,
});

function ConversationTimelinePage() {
	const { t } = useI18n();
	const { conversationId } = Route.useParams();

	const { data } = useQuery({
		queryKey: ["staff", "conversations", conversationId, "timeline"],
		queryFn: () => getConversationTimeline(conversationId),
	});

	return (
		<div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 px-6 py-10">
			<h1 className="font-heading text-2xl text-foreground">
				{t("staff.timeline.title")}
			</h1>
			{data && <TurnTimeline turns={data.turns} />}
		</div>
	);
}
