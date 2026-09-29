import { Link } from "@tanstack/react-router";

import type { HandoffSummary } from "@/client";
import { Card, CardContent } from "@/components/ui/card";
import { type TKey, useI18n } from "@/lib/i18n";

type InboxListProps = {
	items: HandoffSummary[];
};

/**
 * `GET /staff/handoffs` rows (D20). `queue` and `status` are each a closed,
 * fixed-value catalog translated through the dictionary
 * (`staff.queue.<slug>`, `staff.status.<slug>`) -- the same pattern
 * `login.tsx` uses for `document_type_options`, not server-formatted text
 * (R4 covers money/dates/masks, not a fixed enum); `reason` too
 * (`staff.reason.<slug>`). `reference` is shown exactly as the server sent it.
 */
export function InboxList({ items }: InboxListProps) {
	const { t } = useI18n();

	if (items.length === 0) {
		return (
			<p className="text-sm text-muted-foreground">{t("staff.inbox.empty")}</p>
		);
	}

	return (
		<ul className="flex flex-col gap-2">
			{items.map((item) => (
				<li key={item.handoff_id}>
					<Link
						to="/staff/handoffs/$handoffId"
						params={{ handoffId: item.handoff_id }}
						data-testid="inbox-item"
					>
						<Card>
							<CardContent className="flex items-center justify-between gap-4 py-3">
								<div className="flex flex-col">
									<span className="font-medium" data-testid="inbox-item-queue">
										{t(`staff.queue.${item.queue}` as TKey)}
									</span>
									<span className="text-sm text-muted-foreground">
										{item.reference} ·{" "}
										{t(`staff.reason.${item.reason}` as TKey)}
									</span>
								</div>
								<span className="text-sm text-muted-foreground">
									{t(`staff.status.${item.status}` as TKey)}
								</span>
							</CardContent>
						</Card>
					</Link>
				</li>
			))}
		</ul>
	);
}
