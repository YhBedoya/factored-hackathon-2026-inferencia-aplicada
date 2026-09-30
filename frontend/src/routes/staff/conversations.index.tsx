import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";

import {
	ConversationFilters,
	type ConversationSearchFilters,
} from "@/components/staff/ConversationFilters";
import { ConversationTable } from "@/components/staff/ConversationTable";
import { staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
	DEFAULT_CONVERSATION_FILTERS,
	listConversations,
} from "@/lib/traceability";

function parseSearch(
	search: Record<string, unknown>,
): ConversationSearchFilters {
	const str = (key: keyof ConversationSearchFilters): string | undefined =>
		typeof search[key] === "string" ? (search[key] as string) : undefined;
	return {
		language: str("language") as ConversationSearchFilters["language"],
		country: str("country") as ConversationSearchFilters["country"],
		intent: str("intent") as ConversationSearchFilters["intent"],
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
		queryFn: () =>
			listConversations({ ...DEFAULT_CONVERSATION_FILTERS, ...search }),
	});

	return (
		<div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
			<h1 className="font-heading text-2xl text-foreground">
				{t("staff.conversations.title")}
			</h1>
			<ConversationFilters
				value={search}
				onChange={(next) => void navigate({ search: next })}
			/>
			<ConversationTable items={data?.items ?? []} />
		</div>
	);
}
