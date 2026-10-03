import { Link } from "@tanstack/react-router";
import type { ConversationSummary } from "@/client";
import { type TKey, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type ConversationTableProps = {
	items: ConversationSummary[];
};

const HEADER_CELL = "border-b border-border px-3 py-3.5 font-semibold";
const CELL = "px-3 py-3";

// Outcome pill colors ("Swip Staff Conversaciones" design), keyed by the
// `outcome` prefix (`handoff:<queue>` -> `handoff`).
const OUTCOME_PILL: Record<string, string> = {
	resolved: "border-ok bg-ok text-bg",
	clarified: "border-cyan bg-transparent text-cyan",
	abstained: "border-alert bg-alert text-bg",
	handoff: "border-gold bg-gold text-bg",
};

const MODE_DOT: Record<string, string> = {
	human: "bg-gold",
	bot: "bg-cyan",
};

/**
 * `GET /staff/conversations` rows (`ConversationSummary`, D7-A D23):
 * started, language, country, intents, outcome, escalation, queue, turns,
 * mode. `outcome` (`handoff:<queue>` is labeled by its `handoff` prefix),
 * `queue` and `mode` are each a closed catalog read through the dictionary,
 * the same pattern `InboxList` uses for `queue`/`reason`; `created_at` (the
 * conversation's start) is formatted in code (R4), never left as the raw ISO
 * string. Each row links to the turn-by-turn detail.
 */
export function ConversationTable({ items }: ConversationTableProps) {
	const { t } = useI18n();

	return (
		<section className="overflow-hidden rounded-2xl border border-border bg-card">
			<div className="overflow-x-auto">
				<table className="w-full min-w-[1180px] border-collapse text-left text-sm">
					<thead>
						<tr className="text-xs tracking-[0.06em] text-muted-foreground uppercase">
							<th className={cn(HEADER_CELL, "pl-[18px] whitespace-nowrap")}>
								{t("staff.conversations.column.started")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.language")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.country")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.intents")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.outcome")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.escalation")}
							</th>
							<th className={HEADER_CELL}>
								{t("staff.conversations.column.queue")}
							</th>
							<th className={cn(HEADER_CELL, "text-right")}>
								{t("staff.conversations.column.turns")}
							</th>
							<th className={cn(HEADER_CELL, "pr-[18px]")}>
								{t("staff.conversations.column.mode")}
							</th>
						</tr>
					</thead>
					<tbody>
						{items.map((item) => {
							const outcome = item.outcome?.split(":")[0];
							return (
								<tr
									key={item.conversation_id}
									data-testid="conversation-row"
									className="border-b border-border transition-colors hover:bg-accent"
								>
									<td className={cn(CELL, "pl-[18px] whitespace-nowrap")}>
										<Link
											to="/staff/conversations/$conversationId"
											params={{ conversationId: item.conversation_id }}
											data-testid="conversation-row-link"
											className="font-semibold text-cyan tabular-nums hover:text-foreground"
										>
											{new Date(item.created_at).toLocaleString(undefined, {
												dateStyle: "medium",
												timeStyle: "short",
											})}
										</Link>
									</td>
									<td className={cn(CELL, "font-semibold")}>
										{item.language ? t(`lang.${item.language}`) : "—"}
									</td>
									<td className={cn(CELL, "font-semibold")}>
										{item.country ?? "—"}
									</td>
									<td
										className={cn(
											CELL,
											"max-w-[300px] font-mono text-[12.5px] text-muted-foreground",
										)}
									>
										{item.intents.join(", ")}
									</td>
									<td className={cn(CELL, "whitespace-nowrap")}>
										{outcome ? (
											<span
												className={cn(
													"inline-block rounded-full border px-2.5 py-0.5 text-xs font-semibold",
													OUTCOME_PILL[outcome],
												)}
											>
												{t(`staff.conversations.outcome.${outcome}` as TKey)}
											</span>
										) : (
											<span className="text-muted-foreground">—</span>
										)}
									</td>
									<td
										className={cn(
											CELL,
											"whitespace-nowrap",
											item.escalated
												? "text-foreground"
												: "text-muted-foreground",
										)}
									>
										{t(
											item.escalated
												? "staff.conversations.escalation.any"
												: "staff.conversations.escalation.none",
										)}
									</td>
									<td
										className={cn(
											CELL,
											"whitespace-nowrap",
											item.queue ? "text-foreground" : "text-muted-foreground",
										)}
									>
										{item.queue ? t(`staff.queue.${item.queue}` as TKey) : "—"}
									</td>
									<td className={cn(CELL, "text-right tabular-nums")}>
										{item.turns}
									</td>
									<td className={cn(CELL, "pr-[18px] whitespace-nowrap")}>
										<span className="inline-flex items-center gap-1.5 font-semibold">
											<span
												aria-hidden="true"
												className={cn(
													"size-[7px] rounded-full",
													MODE_DOT[item.mode],
												)}
											/>
											{t(`staff.conversations.mode.${item.mode}` as TKey)}
										</span>
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>
			{items.length === 0 && (
				<p className="p-12 text-center text-muted-foreground">
					{t("staff.conversations.empty")}
				</p>
			)}
		</section>
	);
}
