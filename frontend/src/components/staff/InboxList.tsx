import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";

import type { HandoffSummary } from "@/client";
import { type TKey, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type InboxListProps = {
	items: HandoffSummary[];
	// Handoffs that arrived in the latest poll that brought new rows.
	freshIds?: ReadonlySet<string>;
};

// Each queue keeps one brand color ("Swip Staff Bandeja" design): Fraudes
// is the alert red, Reclamos gold, Atención cyan, Cobranza neutral.
const QUEUE_BAR: Record<HandoffSummary["queue"], string> = {
	atencion: "bg-cyan",
	cobranza: "bg-muted-foreground",
	fraudes: "bg-alert",
	reclamos: "bg-gold",
};

const STATUS_PILL: Record<HandoffSummary["status"], string> = {
	queued: "border-gold text-gold",
	claimed: "border-cyan bg-cyan/15 text-cyan",
	returned: "border-border text-muted-foreground",
};

/**
 * `GET /staff/handoffs` rows (D20). `queue` and `status` are each a closed,
 * fixed-value catalog translated through the dictionary
 * (`staff.queue.<slug>`, `staff.status.<slug>`) -- the same pattern
 * `login.tsx` uses for `document_type_options`, not server-formatted text
 * (R4 covers money/dates/masks, not a fixed enum); `reason` too
 * (`staff.reason.<slug>`). `reference` is shown exactly as the server sent it.
 */
export function InboxList({ items, freshIds }: InboxListProps) {
	const { t } = useI18n();

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
				<li key={item.handoff_id}>
					<Link
						to="/staff/handoffs/$handoffId"
						params={{ handoffId: item.handoff_id }}
						data-testid="inbox-item"
						className={cn(
							"grid grid-cols-[6px_minmax(0,1fr)_auto_20px] items-center gap-[18px] rounded-2xl border border-border py-[18px] pr-[22px] pl-[18px] text-foreground transition-[background-color,border-color,transform] duration-250 hover:translate-x-[3px] hover:border-cyan hover:bg-accent",
							freshIds?.has(item.handoff_id) ? "bg-accent" : "bg-card",
						)}
					>
						<span
							aria-hidden="true"
							className={cn(
								"self-stretch rounded-[3px]",
								QUEUE_BAR[item.queue],
							)}
						/>
						<span className="flex min-w-0 flex-col gap-[3px]">
							<span
								className="font-heading text-xl leading-tight font-bold"
								data-testid="inbox-item-queue"
							>
								{t(`staff.queue.${item.queue}` as TKey)}
							</span>
							<span className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
								<span className="font-mono text-[13px] text-foreground">
									{item.reference}
								</span>
								<span aria-hidden="true" className="text-border">
									·
								</span>
								<span className="truncate">
									{t(`staff.reason.${item.reason}` as TKey)}
								</span>
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
						<ChevronRight
							aria-hidden="true"
							className="size-4 justify-self-center text-muted-foreground"
						/>
					</Link>
				</li>
			))}
		</ul>
	);
}
