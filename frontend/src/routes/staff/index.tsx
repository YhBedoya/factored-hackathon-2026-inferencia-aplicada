import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { InboxList } from "@/components/staff/InboxList";
import { StaffNav } from "@/components/staff/StaffNav";
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
		return { staff: agent };
	},
	component: StaffInboxPage,
});

const HANDOFFS_QUERY_KEY = ["staff", "handoffs"] as const;
const LOCALES = { es: "es", pt: "pt-BR" } as const;

function StaffInboxPage() {
	const { t, lang } = useI18n();
	const { data, dataUpdatedAt } = useQuery({
		queryKey: HANDOFFS_QUERY_KEY,
		queryFn: listStaffHandoffs,
		// D20: there is no inbox SSE, only a poll.
		refetchInterval: 3000,
	});
	const freshIds = useFreshIds(data);
	// The poll time is presentation only, in the UI language.
	const lastPoll = dataUpdatedAt
		? new Intl.DateTimeFormat(LOCALES[lang], { timeStyle: "medium" }).format(
				dataUpdatedAt,
			)
		: "—";

	return (
		<>
			<StaffNav />
			<div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-6 pt-11 pb-30 lg:px-10">
				<header className="flex flex-wrap items-end justify-between gap-4">
					<h1 className="font-heading text-[38px] leading-tight font-bold tracking-[-0.025em] text-foreground">
						{t("staff.inbox.title")}
					</h1>
					<span
						data-testid="inbox-last-poll"
						className="inline-flex flex-none items-center gap-2 rounded-full border border-border px-3.5 py-1.5 text-[13px] font-semibold whitespace-nowrap text-muted-foreground tabular-nums"
					>
						<span aria-hidden="true" className="size-2 rounded-full bg-ok" />
						{t("staff.inbox.refresh", { time: lastPoll })}
					</span>
				</header>
				<InboxList items={data ?? []} freshIds={freshIds} />
			</div>
		</>
	);
}

// The handoffs that showed up in the latest poll that brought new rows; they
// stay highlighted until a later poll brings others. The first load marks
// nothing as new.
function useFreshIds(
	items: { handoff_id: string }[] | undefined,
): ReadonlySet<string> {
	const seen = useRef<Set<string> | null>(null);
	const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());

	useEffect(() => {
		if (!items) {
			return;
		}
		const ids = new Set(items.map((item) => item.handoff_id));
		if (seen.current) {
			const arrived = [...ids].filter((id) => !seen.current?.has(id));
			if (arrived.length > 0) {
				setFresh(new Set(arrived));
			}
		}
		seen.current = ids;
	}, [items]);

	return fresh;
}
