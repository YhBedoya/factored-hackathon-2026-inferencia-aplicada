import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";
import { Eye } from "lucide-react";

import { StaffNav } from "@/components/staff/StaffNav";
import { TurnTimeline } from "@/components/staff/TurnTimeline";
import { getStaffConversationTimeline, staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
		queryFn: () => getStaffConversationTimeline(conversationId),
	});

	return (
		<>
			<StaffNav />
			<div className="mx-auto flex w-full max-w-[1320px] flex-col gap-7 px-6 pt-11 pb-30 lg:px-10">
				<header className="flex flex-wrap items-center gap-3.5">
					<h1 className="font-heading text-[38px] leading-tight font-bold tracking-[-0.025em] text-foreground">
						{t("staff.timeline.title")}
					</h1>
					<span className="inline-flex items-center gap-1.5 rounded-full border border-border py-[3px] pr-3 pl-1 text-xs font-semibold text-muted-foreground">
						<span
							aria-hidden="true"
							className="grid size-[18px] place-items-center rounded-full bg-card"
						>
							<Eye className="size-[11px]" strokeWidth={2.5} />
						</span>
						{t("staff.conversations.read_only")}
					</span>
				</header>
				{data && <TurnTimeline turns={data.turns} />}
			</div>
		</>
	);
}
