import type { HandoffPacket } from "@/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

type PacketViewProps = {
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

/**
 * The claimed handoff's packet (`04` §4): verified facts, the writes already
 * applied (with their case ids), the transaction evidence and any open
 * question. Every value is shown exactly as the server built it (R4) --
 * nothing here reformats a fact, a fraud score or a date.
 */
export function PacketView({ packet }: PacketViewProps) {
	const { t } = useI18n();

	return (
		<Card data-testid="packet-view">
			<CardHeader>
				<CardTitle>{t("staff.packet.title")}</CardTitle>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				<section>
					<h3 className="text-sm font-medium">
						{t("staff.packet.verified_facts")}
					</h3>
					<ul className="text-sm text-muted-foreground">
						{packet.verified_facts.map((fact) => (
							<li key={fact.fact} data-testid="packet-verified-fact">
								{fact.fact}: {factValue(fact.value)}({fact.source})
							</li>
						))}
					</ul>
				</section>

				<section>
					<h3 className="text-sm font-medium">
						{t("staff.packet.actions_taken")}
					</h3>
					<ul className="text-sm text-muted-foreground">
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
					</ul>
				</section>

				<section>
					<h3 className="text-sm font-medium">{t("staff.packet.evidence")}</h3>
					<ul className="text-sm text-muted-foreground">
						{packet.evidence.map((item) => (
							<li key={item.ref} data-testid="packet-evidence">
								{item.ref}
								{item.fraud_score !== null ? ` (${item.fraud_score})` : ""}
							</li>
						))}
					</ul>
				</section>

				<section>
					<h3 className="text-sm font-medium">
						{t("staff.packet.open_questions")}
					</h3>
					<ul className="text-sm text-muted-foreground">
						{packet.open_questions.map((question) => (
							<li key={question} data-testid="packet-open-question">
								{question}
							</li>
						))}
					</ul>
				</section>
			</CardContent>
		</Card>
	);
}
