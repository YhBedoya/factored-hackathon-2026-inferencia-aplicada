import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import type { HandoffSummary } from "@/client";
import { QUEUE_BAR } from "@/components/staff/queueStyles";
import { Button } from "@/components/ui/button";
import { claimStaffHandoff } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type InboxListProps = {
	items: HandoffSummary[];
	// Handoffs that arrived in the latest poll that brought new rows.
	freshIds?: ReadonlySet<string>;
};

const STATUS_PILL: Record<HandoffSummary["status"], string> = {
	queued: "border-gold text-gold",
	claimed: "border-cyan bg-cyan/15 text-cyan",
	returned: "border-border text-muted-foreground",
};

// Time in queue (AS7): from `created_at` to now, frozen at `claimed_at` once
// claimed. Computed client-side so it ticks between polls and SSE updates.
function queueClock(item: HandoffSummary, now: number): string {
	const end = item.claimed_at ? Date.parse(item.claimed_at) : now;
	const total = Math.max(
		0,
		Math.floor((end - Date.parse(item.created_at)) / 1000),
	);
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	const seconds = total % 60;
	const pad = (n: number) => String(n).padStart(2, "0");
	return hours > 0
		? `${hours}:${pad(minutes)}:${pad(seconds)}`
		: `${pad(minutes)}:${pad(seconds)}`;
}

/**
 * `GET /staff/handoffs` rows (D20). `queue` and `status` are each a closed,
 * fixed-value catalog translated through the dictionary
 * (`staff.queue.<slug>`, `staff.status.<slug>`) -- the same pattern
 * `login.tsx` uses for `document_type_options`, not server-formatted text
 * (R4 covers money/dates/masks, not a fixed enum); `reason` too
 * (`staff.reason.<slug>`). `reference` is shown exactly as the server sent it.
 *
 * A claimed or returned row opens the case as a whole. A queued row is not
 * a link: only its claim button acts, claiming it right here and going
 * straight to the case chat.
 */
export function InboxList({ items, freshIds }: InboxListProps) {
	const { t } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const [claimingId, setClaimingId] = useState<string | null>(null);
	const [failedId, setFailedId] = useState<string | null>(null);
	const [now, setNow] = useState(() => Date.now());

	useEffect(() => {
		const timer = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(timer);
	}, []);

	async function handleClaim(handoffId: string) {
		setClaimingId(handoffId);
		setFailedId(null);
		try {
			await claimStaffHandoff(handoffId);
			await navigate({
				to: "/staff/handoffs/$handoffId",
				params: { handoffId },
			});
		} catch {
			// Most likely another agent claimed it first; the next poll shows it.
			setFailedId(handoffId);
			setClaimingId(null);
			void queryClient.invalidateQueries({ queryKey: ["staff", "handoffs"] });
		}
	}

	if (items.length === 0) {
		return (
			<p className="rounded-2xl border border-dashed border-border p-14 text-center text-muted-foreground">
				{t("staff.inbox.empty")}
			</p>
		);
	}

	return (
		<ul className="flex flex-col gap-2.5">
			{items.map((item) => (
				<li key={item.handoff_id} className="flex flex-col gap-1.5">
					<div
						data-testid="inbox-item"
						className={cn(
							"relative grid grid-cols-[6px_minmax(0,1fr)_auto] items-center gap-x-[18px] gap-y-3 sm:grid-cols-[6px_minmax(0,1fr)_auto_auto] rounded-2xl border border-border py-[18px] pr-[22px] pl-[18px] text-foreground transition-[background-color,border-color,transform] duration-250",
							// Only a row that opens the case reacts to hover.
							item.status !== "queued" &&
								"hover:translate-x-[3px] hover:border-cyan hover:bg-accent has-[a:focus-visible]:border-cyan has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-ring/50",
							freshIds?.has(item.handoff_id) ? "bg-accent" : "bg-card",
						)}
					>
						<span
							aria-hidden="true"
							className={cn(
								"self-stretch rounded-[3px]",
								// Narrow screens put the claim button on a second line.
								item.status === "queued" && "row-span-2 sm:row-span-1",
								QUEUE_BAR[item.queue],
							)}
						/>
						<span className="flex min-w-0 flex-col gap-[3px]">
							{item.status === "queued" ? (
								<span
									data-testid="inbox-item-queue"
									className="font-heading text-xl leading-tight font-bold"
								>
									{t(`staff.queue.${item.queue}` as TKey)}
								</span>
							) : (
								// The link stretches over the whole row.
								<Link
									to="/staff/handoffs/$handoffId"
									params={{ handoffId: item.handoff_id }}
									data-testid="inbox-item-queue"
									className="font-heading text-xl leading-tight font-bold outline-none after:absolute after:inset-0 after:rounded-2xl"
								>
									{t(`staff.queue.${item.queue}` as TKey)}
								</Link>
							)}
							<span className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
								<span className="font-mono text-[13px] whitespace-nowrap text-foreground">
									{item.reference}
								</span>
								<span aria-hidden="true" className="text-border">
									·
								</span>
								<span className="truncate">
									{t(`staff.reason.${item.reason}` as TKey)}
								</span>
							</span>
							<span
								data-testid="inbox-item-preview"
								className="truncate text-sm text-foreground"
							>
								{item.case_summary?.asked ?? item.request}
							</span>
							<span
								data-testid="inbox-item-clock"
								className="font-mono text-xs text-muted-foreground"
							>
								{t(
									item.claimed_at
										? "staff.inbox.waited"
										: "staff.inbox.in_queue",
									{ time: queueClock(item, now) },
								)}
							</span>
						</span>
						<span
							className={cn(
								"rounded-full border px-3 py-0.5 text-xs font-semibold whitespace-nowrap",
								STATUS_PILL[item.status],
							)}
						>
							{t(`staff.status.${item.status}` as TKey)}
						</span>
						{item.status === "queued" ? (
							<Button
								data-testid="inbox-claim"
								className="col-span-2 justify-self-start sm:col-span-1"
								disabled={claimingId !== null}
								onClick={() => void handleClaim(item.handoff_id)}
							>
								{t("staff.detail.claim")}
							</Button>
						) : (
							<ChevronRight
								aria-hidden="true"
								className="hidden size-4 justify-self-center text-muted-foreground sm:block"
							/>
						)}
					</div>
					{failedId === item.handoff_id && (
						<p role="alert" className="px-2 text-sm text-alert">
							{t("errors.generic")}
						</p>
					)}
				</li>
			))}
		</ul>
	);
}
