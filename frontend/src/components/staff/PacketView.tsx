import { Link } from "@tanstack/react-router";
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
	children: ReactNode[];
};

// One packet list. An empty one renders nothing, heading included: a
// `human_request` handoff, for one, has no facts, actions or evidence.
function PacketSection({ title, children }: PacketSectionProps) {
	if (children.length === 0) {
		return null;
	}
	return (
		<section>
			<h3 className="text-sm font-medium">{title}</h3>
			<ul className="text-sm text-muted-foreground">{children}</ul>
		</section>
	);
}

/**
 * The claimed handoff (`04` §4): the case header from the summary (reference,
 * queue, reason, priority, claimant), the case summary (the one-line `request`
 * when the LLM summary fell back), the focus card, routing, risk, verified
 * facts, writes already applied (with their case ids), transaction evidence,
 * open questions, history, friction and a link to the full conversation.
 * A section with nothing to show is left out entirely. Every value is shown
 * exactly as the server built it (R4) -- nothing here reformats a fact, a
 * fraud score or a date. `queue`, `reason` and `priority` are closed enums
 * translated through the dictionary, the same way `InboxList` shows `queue`
 * and `status`.
 */
export function PacketView({ summary, packet }: PacketViewProps) {
	const { t } = useI18n();

	const caseSummary = packet.case_summary;
	const summaryRows = caseSummary
		? (
				[
					["staff.packet.summary_asked", caseSummary.asked],
					["staff.packet.summary_did", caseSummary.did],
					["staff.packet.summary_unfinished", caseSummary.unfinished],
				] as const
			).filter(([, text]) => text)
		: [];

	const risk = packet.risk;
	const riskItems: ReactNode[] = [];
	if (risk && risk.priority_flags.length > 0) {
		riskItems.push(
			<li key="flags">
				{t("staff.packet.risk_flags")}: {risk.priority_flags.join(", ")}
			</li>,
		);
	}
	if (risk?.legal_keyword) {
		riskItems.push(<li key="legal">{t("staff.packet.risk_legal")}</li>);
	}
	if (risk && risk.unauthorized_attempts > 0) {
		riskItems.push(
			<li key="unauthorized">
				{t("staff.packet.risk_unauthorized")}: {risk.unauthorized_attempts}
			</li>,
		);
	}

	const historyItems: ReactNode[] = [
		...(packet.history?.handoffs ?? []).map((past) => (
			<li key={`h-${past.reference}`} data-testid="packet-history">
				{t("staff.packet.history_handoffs")}: {past.reference} ·{" "}
				{t(`staff.reason.${past.reason}` as TKey)} ·{" "}
				{t(`staff.status.${past.status}` as TKey)}
			</li>
		)),
		...(packet.history?.claims ?? []).map((claim) => (
			<li key={`c-${claim.claim_id}`} data-testid="packet-history">
				{t("staff.packet.history_claims")}: {claim.claim_id}
				{claim.category ? ` · ${claim.category}` : ""}
				{claim.status ? ` · ${claim.status}` : ""}
			</li>
		)),
	];

	const frictionRows = packet.friction
		? (
				[
					[
						"staff.packet.friction_clarifications",
						packet.friction.clarifications,
					],
					["staff.packet.friction_abstentions", packet.friction.abstentions],
					["staff.packet.friction_non_answers", packet.friction.non_answers],
				] as const
			).filter(([, count]) => count > 0)
		: [];

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
				{caseSummary && summaryRows.length > 0 ? (
					<section>
						<h3 className="text-sm font-medium">
							{t("staff.packet.case_summary")}
						</h3>
						<dl className="text-sm" data-testid="packet-case-summary">
							{summaryRows.map(([key, text]) => (
								<div key={key}>
									<dt className="text-muted-foreground">{t(key)}</dt>
									<dd>{text}</dd>
								</div>
							))}
						</dl>
					</section>
				) : (
					!caseSummary &&
					packet.request && (
						<section>
							<h3 className="text-sm font-medium">
								{t("staff.packet.request")}
							</h3>
							<p className="text-sm" data-testid="packet-request">
								{packet.request}
							</p>
						</section>
					)
				)}

				{packet.focus_card && (
					<section>
						<h3 className="text-sm font-medium">
							{t("staff.packet.focus_card")}
						</h3>
						<p
							className="text-sm text-muted-foreground"
							data-testid="packet-focus-card"
						>
							{packet.focus_card}
						</p>
					</section>
				)}

				{packet.routing && (
					<section>
						<h3 className="text-sm font-medium">{t("staff.packet.routing")}</h3>
						<ul
							className="text-sm text-muted-foreground"
							data-testid="packet-routing"
						>
							<li>
								{t("staff.packet.routing_reason")}:{" "}
								{t(`staff.reason.${packet.routing.reason}` as TKey)}
							</li>
							<li>
								{t("staff.packet.routing_queue")}:{" "}
								{t(`staff.queue.${packet.routing.queue}` as TKey)}
							</li>
							<li>
								{t("staff.packet.routing_branch")}: {packet.routing.branch}
							</li>
							{packet.routing.flow && (
								<li>
									{t("staff.packet.routing_flow")}: {packet.routing.flow}
								</li>
							)}
						</ul>
					</section>
				)}

				{riskItems.length > 0 && (
					<section data-testid="packet-risk">
						<h3 className="text-sm font-medium">{t("staff.packet.risk")}</h3>
						<ul className="text-sm text-muted-foreground">{riskItems}</ul>
					</section>
				)}

				<PacketSection title={t("staff.packet.verified_facts")}>
					{packet.verified_facts.map((fact) => (
						<li key={fact.fact} data-testid="packet-verified-fact">
							{fact.fact}: {factValue(fact.value)} ({fact.source})
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.actions_taken")}>
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

				<PacketSection title={t("staff.packet.evidence")}>
					{packet.evidence.map((item) => (
						<li key={item.ref} data-testid="packet-evidence">
							{item.ref}
							{item.fraud_score !== null ? ` (${item.fraud_score})` : ""}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.open_questions")}>
					{packet.open_questions.map((question) => (
						<li key={question} data-testid="packet-open-question">
							{question}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.history")}>
					{historyItems}
				</PacketSection>

				{frictionRows.length > 0 && (
					<section data-testid="packet-friction">
						<h3 className="text-sm font-medium">
							{t("staff.packet.friction")}
						</h3>
						<ul className="text-sm text-muted-foreground">
							{frictionRows.map(([key, count]) => (
								<li key={key}>
									{t(key)}: {count}
								</li>
							))}
						</ul>
					</section>
				)}

				<Link
					to="/staff/conversations/$conversationId"
					params={{ conversationId: summary.conversation_id }}
					data-testid="packet-conversation-link"
					className="text-sm text-cyan underline"
				>
					{t("staff.packet.open_conversation")}
				</Link>
			</CardContent>
		</Card>
	);
}
