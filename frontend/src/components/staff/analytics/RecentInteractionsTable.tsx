import { Link } from "@tanstack/react-router";

import { BlockFrame } from "@/components/staff/analytics/BlockFrame";
import { formatUsd } from "@/components/staff/analytics/format";
import type { AnalyticsSummary } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

interface RecentInteractionsTableProps {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

// The header sticks to the top of the panel body, which scrolls (D4: all 50 rows stay).
const HEADER_CELL =
	"sticky top-0 whitespace-nowrap bg-card py-1 pr-1.5 font-medium";
const CELL = "whitespace-nowrap py-1 pr-1.5";

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
	month: "short",
	day: "numeric",
	hour: "2-digit",
	minute: "2-digit",
};

/**
 * Last interactions in server order (at most 50). Only a real row links to the
 * conversation timeline: a mock row has no conversation behind it (D15), so it
 * renders no link and no anchor.
 */
export function RecentInteractionsTable({
	summary,
	isLoading,
	isError,
}: RecentInteractionsTableProps) {
	const { t } = useI18n();
	const rows = summary?.recent ?? [];

	return (
		<BlockFrame
			title={t("staff.analytics.table.title")}
			info={t("staff.analytics.info.chart.recent")}
			testId="analytics-recent"
			isLoading={isLoading}
			isError={isError}
			isEmpty={rows.length === 0}
		>
			<div className="h-full min-h-0 overflow-auto">
				<table className="w-full text-left text-xs">
					<thead>
						<tr className="text-muted-foreground">
							<th className={HEADER_CELL}>
								{t("staff.analytics.table.ended_at")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.analytics.table.end_reason")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.analytics.table.intents")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.analytics.table.outcome")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.analytics.table.sentiment")}
							</th>
							<th className={HEADER_CELL}>{t("staff.analytics.table.cost")}</th>
							<th className="sticky top-0 bg-card py-1 font-medium" />
						</tr>
					</thead>
					<tbody>
						{rows.map((row) => (
							<tr key={row.conversation_id} data-testid="analytics-recent-row">
								<td className={CELL}>
									{new Date(row.ended_at).toLocaleString(
										undefined,
										DATE_FORMAT,
									)}
								</td>
								<td className={CELL}>
									{t(`staff.analytics.end_reason.${row.end_reason}` as TKey)}
								</td>
								<td
									className={`${CELL} max-w-24 truncate`}
									title={row.intents.join(", ")}
								>
									{row.intents.join(", ")}
								</td>
								<td className={CELL}>
									{t(`staff.analytics.outcome.${row.outcome}` as TKey)}
								</td>
								<td className={CELL}>
									{row.sentiment_overall
										? t(
												`staff.analytics.sentiment.${row.sentiment_overall}` as TKey,
											)
										: "—"}
								</td>
								<td className={CELL}>{formatUsd(row.cost_usd)}</td>
								<td className="py-1">
									{row.source === "real" ? (
										<Link
											to="/staff/conversations/$conversationId"
											params={{ conversationId: row.conversation_id }}
											data-testid="analytics-recent-link"
											className="underline"
										>
											{t("staff.analytics.table.open")}
										</Link>
									) : null}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</BlockFrame>
	);
}
