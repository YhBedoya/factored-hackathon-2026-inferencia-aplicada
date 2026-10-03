import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";
import { Eye } from "lucide-react";

import {
	ConversationFilters,
	type ConversationSearchFilters,
} from "@/components/staff/ConversationFilters";
import { ConversationTable } from "@/components/staff/ConversationTable";
import { StaffNav } from "@/components/staff/StaffNav";
import { listStaffConversations, staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// D7-A D19's default page; this screen has no pager yet.
const PAGE_SIZE = 50;

function parseSearch(
	search: Record<string, unknown>,
): ConversationSearchFilters {
	const str = (key: keyof ConversationSearchFilters): string | undefined =>
		typeof search[key] === "string" ? (search[key] as string) : undefined;
	return {
		language: str("language") as ConversationSearchFilters["language"],
		country: str("country") as ConversationSearchFilters["country"],
		intent: str("intent"),
		outcome: str("outcome") as ConversationSearchFilters["outcome"],
		escalation: str("escalation") as ConversationSearchFilters["escalation"],
		date_from: str("date_from"),
		date_to: str("date_to"),
	};
}

// D5/D20-style guard, same as `staff/index.tsx`. The filters live in the URL
// (`validateSearch`, D13) so the list is a shareable, back-button-safe `GET`.
export const Route = createFileRoute("/staff/conversations/")({
	beforeLoad: async () => {
		const agent = await staffMe();
		if (!agent) {
			throw redirect({ to: "/staff/login" });
		}
	},
	validateSearch: parseSearch,
	component: ConversationListPage,
});

function ConversationListPage() {
	const { t } = useI18n();
	const search = Route.useSearch();
	const navigate = Route.useNavigate();

	const { data } = useQuery({
		queryKey: ["staff", "conversations", search],
		queryFn: () => listStaffConversations({ ...search, limit: PAGE_SIZE }),
	});

	return (
		<>
			<StaffNav />
			<div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-6 pt-11 pb-30 lg:px-10">
				<header className="flex flex-wrap items-center gap-3.5">
					<h1 className="font-heading text-[38px] leading-tight font-bold tracking-[-0.025em] text-foreground">
						{t("staff.conversations.title")}
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
				<ConversationFilters
					value={search}
					onChange={(next) => void navigate({ search: next })}
				/>
				<ConversationTable items={data?.items ?? []} />
			</div>
		</>
	);
}
