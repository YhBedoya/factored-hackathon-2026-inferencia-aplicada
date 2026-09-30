import { Link } from "@tanstack/react-router";
import { type TKey, useI18n } from "@/lib/i18n";
import type { ConversationListItem } from "@/lib/traceability";

type ConversationTableProps = {
	items: ConversationListItem[];
};

const HEADER_CELL = "py-2 pr-4 font-medium";
const CELL = "py-2 pr-4";

/**
 * `GET /staff/conversations` rows (D13): started, language, country,
 * intents, outcome, escalation, queue, turns, mode. `queue`, `escalation`
 * and `mode` are each a closed catalog read through the dictionary, the same
 * pattern `InboxList` uses for `queue`/`reason`; `started_at` is formatted
 * in code (R4), never left as the raw ISO string. Each row links to the
 * turn-by-turn detail.
 */
export function ConversationTable({ items }: ConversationTableProps) {
	const { t } = useI18n();

	if (items.length === 0) {
		return (
			<p className="text-sm text-muted-foreground">
				{t("staff.conversations.empty")}
			</p>
		);
	}

	return (
		<table className="w-full text-left text-sm">
			<thead>
				<tr className="text-muted-foreground">
					<th className={HEADER_CELL}>
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
					<th className={HEADER_CELL}>
						{t("staff.conversations.column.turns")}
					</th>
					<th className="py-2 font-medium">
						{t("staff.conversations.column.mode")}
					</th>
				</tr>
			</thead>
			<tbody>
				{items.map((item) => (
					<tr key={item.conversation_id} data-testid="conversation-row">
						<td className={CELL}>
							<Link
								to="/staff/conversations/$conversationId"
								params={{ conversationId: item.conversation_id }}
								data-testid="conversation-row-link"
								className="underline"
							>
								{new Date(item.started_at).toLocaleString()}
							</Link>
						</td>
						<td className={CELL}>
							{item.language ? t(`lang.${item.language}`) : "—"}
						</td>
						<td className={CELL}>{item.country}</td>
						<td className={CELL}>{item.intents.join(", ")}</td>
						<td className={CELL}>
							{item.outcome
								? t(`staff.conversations.outcome.${item.outcome}` as TKey)
								: "—"}
						</td>
						<td className={CELL}>
							{item.escalation
								? t(`staff.reason.${item.escalation}` as TKey)
								: "—"}
						</td>
						<td className={CELL}>
							{item.handoff_queue
								? t(`staff.queue.${item.handoff_queue}` as TKey)
								: "—"}
						</td>
						<td className={CELL}>{item.turns}</td>
						<td className="py-2">
							{t(`staff.conversations.mode.${item.mode}` as TKey)}
						</td>
					</tr>
				))}
			</tbody>
		</table>
	);
}
