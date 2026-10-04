import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import type { HandoffPacket, HandoffSummary } from "@/client";
import { QUEUE_CHIP } from "@/components/staff/queueStyles";
import { type TKey, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

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

// Every section after the first sits under a divider.
const SECTION =
	"flex flex-col gap-2 border-t border-border pt-4 first:border-t-0 first:pt-0";
const HEADING = "text-[13px] font-semibold text-muted-foreground";

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
		<section className={SECTION}>
			<h3 className={HEADING}>{title}</h3>
			<ul className="flex flex-col gap-1.5">{children}</ul>
		</section>
	);
}

/**
 * The claimed handoff (`04` §4), laid out as the "Swip Staff Caso" design:
 * the case header from the summary (reference, queue, reason, priority,
 * claimant), then risk first (in red, so it is never missed), the case
 * summary (the one-line `request` when the LLM summary fell back) with the
 * pending part highlighted, the focus card, routing, verified facts, writes
 * already applied (with their case ids), transaction evidence, open
 * questions, history, friction and a link to the full conversation.
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
	const riskItems: string[] = [];
	if (risk && risk.priority_flags.length > 0) {
		riskItems.push(
			`${t("staff.packet.risk_flags")}: ${risk.priority_flags.join(", ")}`,
		);
	}
	if (risk?.legal_keyword) {
		riskItems.push(t("staff.packet.risk_legal"));
	}
	if (risk && risk.unauthorized_attempts > 0) {
		riskItems.push(
			`${t("staff.packet.risk_unauthorized")}: ${risk.unauthorized_attempts}`,
		);
	}

	// Motivo and cola are closed enums (translated); rama and flujo are
	// shown raw, as the server stored them.
	const routing = packet.routing;
	const routingRows: [TKey, string][] = routing
		? [
				[
					"staff.packet.routing_reason",
					t(`staff.reason.${routing.reason}` as TKey),
				],
				[
					"staff.packet.routing_queue",
					t(`staff.queue.${routing.queue}` as TKey),
				],
				["staff.packet.routing_branch", routing.branch],
			]
		: [];
	if (routing?.flow) {
		routingRows.push(["staff.packet.routing_flow", routing.flow]);
	}

	const historyItems: ReactNode[] = [
		...(packet.history?.handoffs ?? []).map((past) => (
			<li key={`h-${past.reference}`} data-testid="packet-history">
				<span className="text-muted-foreground">
					{t("staff.packet.history_handoffs")}:
				</span>{" "}
				<span className="font-mono text-[13px]">{past.reference}</span> ·{" "}
				{t(`staff.reason.${past.reason}` as TKey)} ·{" "}
				{t(`staff.status.${past.status}` as TKey)}
			</li>
		)),
		...(packet.history?.claims ?? []).map((claim) => (
			<li key={`c-${claim.claim_id}`} data-testid="packet-history">
				<span className="text-muted-foreground">
					{t("staff.packet.history_claims")}:
				</span>{" "}
				<span className="font-mono text-[13px]">{claim.claim_id}</span>
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
		<article
			data-testid="packet-view"
			className="flex flex-col rounded-2xl border border-border bg-card text-card-foreground"
		>
			<header className="flex flex-col gap-3 border-b border-border px-[22px] pt-5 pb-[18px]">
				<h1 className="text-xl leading-tight font-bold">
					{t("staff.packet.title")} ·{" "}
					<span className="font-mono text-[17px] font-semibold text-cyan">
						{summary.reference}
					</span>
				</h1>
				<p
					className="flex flex-wrap gap-2 text-xs font-semibold"
					data-testid="packet-meta"
				>
					<span
						data-testid="packet-queue-chip"
						className={cn("rounded-full px-3 py-1", QUEUE_CHIP[summary.queue])}
					>
						{t(`staff.queue.${summary.queue}` as TKey)}
					</span>
					<span className="rounded-full border border-border px-3 py-1">
						{t(`staff.reason.${summary.reason}` as TKey)}
					</span>
					<span className="rounded-full border border-gold px-3 py-1 text-gold">
						{t(`staff.priority.${summary.priority}` as TKey)}
					</span>
				</p>
				{summary.claimed_by && (
					<p className="text-[13px] text-muted-foreground">
						{t("staff.packet.claimed_by", { name: summary.claimed_by })}
					</p>
				)}
			</header>
			<div className="flex flex-col gap-4 px-[22px] pt-5 pb-6 text-sm">
				{riskItems.length > 0 && (
					<section data-testid="packet-risk" className={SECTION}>
						<div className="flex flex-col gap-2.5 rounded-xl border border-alert bg-alert/8 px-3.5 py-3">
							<h3 className="flex items-center gap-2 text-[13px] font-semibold text-alert">
								<span
									aria-hidden="true"
									className="flex size-[18px] items-center justify-center rounded-full bg-alert text-[11px] font-bold text-bg"
								>
									!
								</span>
								{t("staff.packet.risk")}
							</h3>
							<ul className="flex flex-wrap gap-2">
								{riskItems.map((item) => (
									<li
										key={item}
										className="rounded-full border border-border bg-surface px-3 py-1 text-xs"
									>
										{item}
									</li>
								))}
							</ul>
						</div>
					</section>
				)}

				{caseSummary && summaryRows.length > 0 ? (
					<section className={SECTION}>
						<h3 className={HEADING}>{t("staff.packet.case_summary")}</h3>
						<dl
							className="flex flex-col gap-2"
							data-testid="packet-case-summary"
						>
							{summaryRows.map(([key, text]) => {
								const pending = key === "staff.packet.summary_unfinished";
								return (
									<div
										key={key}
										data-testid={pending ? "packet-summary-pending" : undefined}
										className={cn(
											"grid grid-cols-[130px_1fr] gap-3",
											pending &&
												"-mx-3 rounded-[10px] border border-gold bg-cyan-deep px-3 py-2.5",
										)}
									>
										<dt
											className={
												pending
													? "font-semibold text-gold"
													: "text-muted-foreground"
											}
										>
											{t(key)}
										</dt>
										<dd className={cn(pending && "font-semibold")}>{text}</dd>
									</div>
								);
							})}
						</dl>
					</section>
				) : (
					!caseSummary &&
					packet.request && (
						<section className={SECTION}>
							<h3 className={HEADING}>{t("staff.packet.request")}</h3>
							<p data-testid="packet-request">{packet.request}</p>
						</section>
					)
				)}

				{packet.focus_card && (
					<section className={SECTION}>
						<h3 className={HEADING}>{t("staff.packet.focus_card")}</h3>
						<p
							className="flex items-center gap-2.5"
							data-testid="packet-focus-card"
						>
							<span
								aria-hidden="true"
								className="h-3 w-[18px] rounded-[3px] bg-gold"
							/>
							{packet.focus_card}
						</p>
					</section>
				)}

				{routingRows.length > 0 && (
					<section className={SECTION}>
						<h3 className={HEADING}>{t("staff.packet.routing")}</h3>
						<ul
							className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5"
							data-testid="packet-routing"
						>
							{routingRows.map(([key, text]) => (
								<li key={key} className="col-span-2 grid grid-cols-subgrid">
									<span className="min-w-[72px] text-muted-foreground">
										{t(key)}
									</span>
									<span className="font-mono text-[13px]">{text}</span>
								</li>
							))}
						</ul>
					</section>
				)}

				<PacketSection title={t("staff.packet.verified_facts")}>
					{packet.verified_facts.map((fact) => (
						<li key={fact.fact} data-testid="packet-verified-fact">
							{fact.fact}:{" "}
							<span className="text-muted-foreground">
								{factValue(fact.value)}
							</span>{" "}
							<span className="font-mono text-xs text-muted-foreground">
								({fact.source})
							</span>
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.actions_taken")}>
					{packet.actions_taken.map((action) => (
						<li
							key={action.tool}
							data-testid="packet-action"
							className="flex flex-wrap items-baseline gap-x-2"
						>
							<span aria-hidden="true" className="font-bold text-ok">
								✓
							</span>
							<span className="font-mono text-[13px]">{action.tool}</span>
							{action.case_ids?.map((caseId) => (
								<span
									key={caseId}
									data-testid="packet-action-case-id"
									className="font-mono text-[13px] text-muted-foreground"
								>
									{caseId}
								</span>
							))}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.evidence")}>
					{packet.evidence.map((item) => (
						<li key={item.ref} data-testid="packet-evidence">
							<span className="font-mono text-[13px]">{item.ref}</span>
							{item.fraud_score !== null && (
								<span className="text-gold"> ({item.fraud_score})</span>
							)}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.open_questions")}>
					{packet.open_questions.map((question) => (
						<li
							key={question}
							data-testid="packet-open-question"
							className="flex gap-2"
						>
							<span aria-hidden="true" className="font-bold text-cyan">
								?
							</span>
							{question}
						</li>
					))}
				</PacketSection>

				<PacketSection title={t("staff.packet.history")}>
					{historyItems}
				</PacketSection>

				{frictionRows.length > 0 && (
					<section data-testid="packet-friction" className={SECTION}>
						<h3 className={HEADING}>{t("staff.packet.friction")}</h3>
						<ul className="flex flex-wrap gap-x-5 gap-y-1">
							{frictionRows.map(([key, count]) => (
								<li key={key}>
									<span className="text-muted-foreground">{t(key)}:</span>{" "}
									<span className="font-semibold">{count}</span>
								</li>
							))}
						</ul>
					</section>
				)}

				<div className={SECTION}>
					<Link
						to="/staff/conversations/$conversationId"
						params={{ conversationId: summary.conversation_id }}
						data-testid="packet-conversation-link"
						className="self-start font-semibold text-cyan underline underline-offset-3 hover:text-foreground"
					>
						{t("staff.packet.open_conversation")}
					</Link>
				</div>
			</div>
		</article>
	);
}
