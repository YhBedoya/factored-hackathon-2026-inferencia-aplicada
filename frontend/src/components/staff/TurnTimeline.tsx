import type { TurnTimeline as TurnTimelineRow } from "@/client";
import { Card, CardContent } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

type TurnTimelineProps = {
	turns: TurnTimelineRow[];
};

const SECTION_TITLE = "text-sm font-medium";
const EMPTY_TEXT = "text-sm text-muted-foreground";

// R4: numbers are formatted here, never shown as the raw float.
function formatMs(ms: number | null): string {
	return ms === null ? "—" : `${Math.round(ms)} ms`;
}

function formatUsd(usd: number | null): string {
	return usd === null ? "—" : `US$ ${usd.toFixed(4)}`;
}

/** A `rule_hit` event's rule id (`{rule_id, ...}` payload), else its type. */
function ruleName(payload: Record<string, unknown>): string {
	return typeof payload.rule_id === "string" ? payload.rule_id : "rule_hit";
}

/**
 * One `<details>` per turn, in server order. Expanding a turn shows its full
 * "why" (D13): the NLU result, rules hit, tool calls with their results,
 * sources, the policy version, one line per LLM call, the turn's own
 * latency/cost and the Langfuse link -- shown only when the run was traced
 * (ADR-006 no-op tracing hook means most turns have none). Every value here
 * is the masked audit payload the server already built (R5); there is no
 * chain-of-thought field (ADR-024), so nothing here reads or renders one.
 */
export function TurnTimeline({ turns }: TurnTimelineProps) {
	const { t } = useI18n();
	const none = t("staff.packet.none");

	if (turns.length === 0) {
		return <p className={EMPTY_TEXT}>{t("staff.timeline.empty")}</p>;
	}

	return (
		<ul className="flex flex-col gap-3">
			{turns.map((turn, index) => (
				<li key={turn.turn_id}>
					<Card>
						<CardContent>
							<details data-testid="turn-details">
								<summary
									className="cursor-pointer text-sm font-medium"
									data-testid="turn-summary"
								>
									{t("staff.timeline.turn", { index: String(index + 1) })} ·{" "}
									{new Date(turn.started_at).toLocaleString()}
								</summary>

								<div
									className="mt-3 flex flex-col gap-3 text-sm"
									data-testid="turn-why"
								>
									{turn.customer_text_masked && (
										<p data-testid="turn-customer-text">
											{turn.customer_text_masked}
										</p>
									)}
									{turn.bot_text_masked && (
										<p data-testid="turn-reply-text">{turn.bot_text_masked}</p>
									)}

									<section>
										<h4 className={SECTION_TITLE}>{t("staff.timeline.nlu")}</h4>
										<pre
											className="overflow-x-auto rounded bg-muted p-2 text-xs"
											data-testid="turn-nlu"
										>
											{turn.nlu ? JSON.stringify(turn.nlu) : none}
										</pre>
									</section>

									<section>
										<h4 className={SECTION_TITLE}>
											{t("staff.timeline.rules_hit")}
										</h4>
										{turn.rules.length === 0 ? (
											<p className={EMPTY_TEXT}>{none}</p>
										) : (
											<ul>
												{turn.rules.map((rule, ruleIndex) => (
													<li
														// biome-ignore lint/suspicious/noArrayIndexKey: rule events carry no stable id
														key={`${rule.at}-${ruleIndex}`}
														data-testid="turn-rule"
													>
														{ruleName(rule.payload)}
													</li>
												))}
											</ul>
										)}
									</section>

									<section>
										<h4 className={SECTION_TITLE}>
											{t("staff.timeline.tools")}
										</h4>
										{turn.tools.length === 0 ? (
											<p className={EMPTY_TEXT}>{none}</p>
										) : (
											<ul>
												{turn.tools.map((tool, toolIndex) => (
													<li
														// biome-ignore lint/suspicious/noArrayIndexKey: tool events carry no stable id
														key={`${tool.type}-${toolIndex}`}
														data-testid="turn-tool"
													>
														{tool.type}: {JSON.stringify(tool.payload)}
													</li>
												))}
											</ul>
										)}
									</section>

									<section>
										<h4 className={SECTION_TITLE}>
											{t("staff.timeline.sources")}
										</h4>
										{turn.sources.length === 0 ? (
											<p className={EMPTY_TEXT}>{none}</p>
										) : (
											<ul>
												{turn.sources.map((source) => (
													<li key={source} data-testid="turn-source">
														{source}
													</li>
												))}
											</ul>
										)}
									</section>

									<p data-testid="turn-policy-version">
										{t("staff.timeline.policy_version")}:{" "}
										{turn.policy_version ?? none}
									</p>

									<section>
										<h4 className={SECTION_TITLE}>
											{t("staff.timeline.llm_calls")}
										</h4>
										{turn.llm_calls.length === 0 ? (
											<p className={EMPTY_TEXT}>{none}</p>
										) : (
											<ul>
												{turn.llm_calls.map((call, callIndex) => (
													<li
														// biome-ignore lint/suspicious/noArrayIndexKey: a step can repeat across retries
														key={`${call.step}-${call.attempt}-${callIndex}`}
														data-testid="turn-llm-call"
													>
														{call.step} · {call.model_id} ·{" "}
														{call.prompt_version} · {formatMs(call.latency_ms)}
														{call.cost_usd !== null
															? ` · ${formatUsd(call.cost_usd)}`
															: ""}
													</li>
												))}
											</ul>
										)}
									</section>

									<p data-testid="turn-latency-cost">
										{t("staff.timeline.turn_latency")}:{" "}
										{formatMs(turn.latency_ms)} ·{" "}
										{t("staff.timeline.turn_cost")}: {formatUsd(turn.cost_usd)}
									</p>

									{turn.langfuse_url && (
										<a
											href={turn.langfuse_url}
											target="_blank"
											rel="noreferrer"
											className="underline"
											data-testid="turn-langfuse-link"
										>
											{t("staff.timeline.langfuse_link")}
										</a>
									)}
								</div>
							</details>
						</CardContent>
					</Card>
				</li>
			))}
		</ul>
	);
}
