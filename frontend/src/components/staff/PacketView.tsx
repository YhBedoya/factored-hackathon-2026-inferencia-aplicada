import type { ReactNode } from "react";

import type { HandoffPacket, HandoffSummary } from "@/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type TKey, useI18n } from "@/lib/i18n";

type PacketViewProps = {
	summary: HandoffSummary;
	packet: HandoffPacket;
};

// A verified fact's value is whatever JSON the server stored: a case-id list,
// a tracking id, a status or `true`. Shown as-is, never reformatted (R4).
function factValue(value: unknown): string {
	if (Array.isArray(value)) {
		return value.join(", ");
	}
	return typeof value === "string" ? value : JSON.stringify(value);
}

type PacketSectionProps = {
	title: string;
	emptyText: string;
	children: ReactNode[];
};

// One packet list; an empty one says so instead of leaving a bare heading
// (a `human_request` handoff, for one, has no facts, actions or evidence).
function PacketSection({ title, emptyText, children }: PacketSectionProps) {
	return (
		<section>
			<h3 className="text-sm font-medium">{title}</h3>
			{children.length === 0 ? (
				<p className="text-sm text-muted-foreground">{emptyText}</p>
			) : (
				<ul className="text-sm text-muted-foreground">{children}</ul>
			)}
		</section>
	);
}

/**
 * The claimed handoff (`04` §4): the case header from the summary (reference,
 * queue, reason, priority, claimant), the one-line `request`, then verified
 * facts, the writes already applied (with their case ids), the transaction
 * evidence and any open question. Every value is shown exactly as the server
 * built it (R4) -- nothing here reformats a fact, a fraud score or a date.
 * `queue`, `reason` and `priority` are closed enums translated through the
 * dictionary, the same way `InboxList` shows `queue` and `status`.
 */
export function PacketView({ summary, packet }: PacketViewProps) {
	const { t } = useI18n();
	const none = t("staff.packet.none");

	return (
		<Card data-testid="packet-view">
			<CardHeader>
				<CardTitle>
					{t("staff.packet.title")} · {summary.reference}
				</CardTitle>
				<p className="text-sm text-muted-foreground" data-testid="packet-meta">
					{t(`staff.queue.${summary.queue}` as TKey)} ·{" "}
					{t(`staff.reason.${summary.reason}` as TKey)} ·{" "}
					{t(`staff.priority.${summary.priority}` as TKey)}
				</p>
				{summary.claimed_by && (
					<p className="text-sm text-muted-foreground">
						{t("staff.packet.claimed_by", { name: summary.claimed_by })}
					</p>
				)}
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				<section>
					<h3 className="text-sm font-medium">{t("staff.packet.request")}</h3>
					<p className="text-sm" data-testid="packet-request">
						{packet.request || none}
					</p>
				</section>

				<PacketSection
					title={t("staff.packet.verified_facts")}
					emptyText={none}
				>
					{packet.verified_facts.map((fact) => (
						<li key={fact.fact} data-testid="packet-verified-fact">
							{fact.fact}: {factValue(fact.value)} ({fact.source})
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.actions_taken")} emptyText={none}>
					{packet.actions_taken.map((action) => (
						<li key={action.tool} data-testid="packet-action">
							{action.tool}
							{action.case_ids?.map((caseId) => (
								<span key={caseId} data-testid="packet-action-case-id">
									{" "}
									{caseId}
								</span>
							))}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.evidence")} emptyText={none}>
					{packet.evidence.map((item) => (
						<li key={item.ref} data-testid="packet-evidence">
							{item.ref}
							{item.fraud_score !== null ? ` (${item.fraud_score})` : ""}
						</li>
					))}
				</PacketSection>

				<PacketSection
					title={t("staff.packet.open_questions")}
					emptyText={none}
				>
					{packet.open_questions.map((question) => (
						<li key={question} data-testid="packet-open-question">
							{question}
						</li>
					))}
				</PacketSection>
			</CardContent>
		</Card>
	);
}
