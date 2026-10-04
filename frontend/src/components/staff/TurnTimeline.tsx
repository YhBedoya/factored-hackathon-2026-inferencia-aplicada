import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { type ReactNode, useState } from "react";

import type { TurnTimeline as TurnTimelineRow } from "@/client";
import { type Lang, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type TurnTimelineProps = {
	turns: TurnTimelineRow[];
};

const NUMBER_LOCALES: Record<Lang, string> = { es: "es-CO", pt: "pt-BR" };

const EYEBROW =
	"text-xs font-semibold tracking-[0.06em] text-muted-foreground uppercase";
const EMPTY_TEXT = "text-sm text-muted-foreground";
const MONO = "font-mono text-[13px]";
const ROW_TERM =
	"border-t border-border py-3.5 text-[13px] font-semibold text-muted-foreground";
const ROW_DATA = "m-0 min-w-0 border-border pb-3.5 md:border-t md:pt-3.5";
const NAV_BUTTON =
	"grid size-9 cursor-pointer place-items-center rounded-full border border-border bg-[#0B1328] p-0 text-foreground disabled:cursor-default disabled:opacity-35";
const STAT =
	"flex min-w-[180px] flex-col gap-0.5 rounded-xl border border-border bg-[#0B1328] px-[18px] py-3";

// R4: numbers are formatted here, never shown as the raw float.
function formatMs(ms: number | null, lang: Lang): string {
	return ms === null
		? "—"
		: `${new Intl.NumberFormat(NUMBER_LOCALES[lang]).format(Math.round(ms))} ms`;
}

function formatUsd(usd: number | null): string {
	return usd === null ? "—" : `US$ ${usd.toFixed(4)}`;
}

function formatStarted(iso: string): string {
	return new Date(iso).toLocaleString(undefined, {
		dateStyle: "medium",
		timeStyle: "medium",
	});
}

/** A `rule_hit` event's rule id (`{rule_id, ...}` payload), else its type. */
function ruleName(payload: Record<string, unknown>): string {
	return typeof payload.rule_id === "string" ? payload.rule_id : "rule_hit";
}

/**
 * The conversation's turns ("Swip Staff Conversación" design): a list of
 * turns on the left and the selected turn's full "why" (D13) on the right --
 * the NLU result, rules hit, tool calls with their results, sources, the
 * policy version, one line per LLM call, the turn's own latency/cost and the
 * Langfuse link, shown only when the run was traced (ADR-006 no-op tracing
 * hook means most turns have none). Every value here is the masked audit
 * payload the server already built (R5); there is no chain-of-thought field
 * (ADR-024), so nothing here reads or renders one.
 */
export function TurnTimeline({ turns }: TurnTimelineProps) {
	const { t } = useI18n();
	const [selected, setSelected] = useState(0);

	if (turns.length === 0) {
		return (
			<div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted-foreground">
				{t("staff.timeline.empty")}
			</div>
		);
	}

	const index = Math.min(selected, turns.length - 1);
	const turn = turns[index];

	return (
		<div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
			<aside className="flex flex-col overflow-hidden rounded-2xl border border-border bg-card lg:sticky lg:top-[88px] lg:max-h-[calc(100vh-112px)]">
				<div className="flex items-center justify-between border-b border-border px-[18px] py-4">
					<span className={EYEBROW}>{t("staff.timeline.turns")}</span>
					<span className="rounded-full bg-[#0F3440] px-2.5 py-px text-xs font-semibold text-cyan tabular-nums">
						{turns.length}
					</span>
				</div>
				<div className="flex flex-col gap-1 overflow-y-auto p-2">
					{turns.map((row, rowIndex) => {
						const current = rowIndex === index;
						return (
							<button
								key={row.turn_id}
								type="button"
								data-testid="turn-item"
								aria-current={current ? "true" : undefined}
								onClick={() => setSelected(rowIndex)}
								className={cn(
									"flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-foreground transition-colors duration-250 hover:bg-[#16264A]",
									current
										? "border-cyan bg-[#16264A]"
										: "border-transparent bg-transparent",
								)}
							>
								<span
									className={cn(
										"grid size-8 flex-none place-items-center rounded-[10px] text-sm font-semibold tabular-nums",
										current ? "bg-cyan text-bg" : "bg-[#0F3440] text-cyan",
									)}
								>
									{rowIndex + 1}
								</span>
								<span className="flex min-w-0 flex-col leading-snug">
									<span className="text-[15px] font-semibold">
										{t("staff.timeline.turn", {
											index: String(rowIndex + 1),
										})}
									</span>
									<span className="truncate text-xs text-muted-foreground">
										{formatStarted(row.started_at)}
									</span>
								</span>
							</button>
						);
					})}
				</div>
			</aside>

			<section className="min-w-0">
				<TurnDetail
					turn={turn}
					index={index}
					isFirst={index === 0}
					isLast={index === turns.length - 1}
					onPrev={() => setSelected(index - 1)}
					onNext={() => setSelected(index + 1)}
				/>
			</section>
		</div>
	);
}

type TurnDetailProps = {
	turn: TurnTimelineRow;
	index: number;
	isFirst: boolean;
	isLast: boolean;
	onPrev: () => void;
	onNext: () => void;
};

function TurnDetail({
	turn,
	index,
	isFirst,
	isLast,
	onPrev,
	onNext,
}: TurnDetailProps) {
	const { t, lang } = useI18n();
	const none = <p className={EMPTY_TEXT}>{t("staff.packet.none")}</p>;
	const sources = [...new Set(turn.sources)];

	return (
		<article
			data-testid="turn-details"
			className="overflow-hidden rounded-2xl border border-border bg-card"
		>
			<div className="flex items-center gap-4 border-b border-border px-[22px] py-[18px]">
				<span className="grid size-9 flex-none place-items-center rounded-[10px] bg-cyan text-[15px] font-semibold text-bg tabular-nums">
					{index + 1}
				</span>
				<h2
					data-testid="turn-summary"
					className="flex-1 font-heading text-xl font-bold"
				>
					{t("staff.timeline.turn", { index: String(index + 1) })}{" "}
					<span className="font-sans text-base font-normal text-muted-foreground">
						· {formatStarted(turn.started_at)}
					</span>
				</h2>
				<div className="flex gap-1.5">
					<button
						type="button"
						aria-label={t("staff.timeline.prev")}
						onClick={onPrev}
						disabled={isFirst}
						className={NAV_BUTTON}
					>
						<ChevronLeft className="size-4" />
					</button>
					<button
						type="button"
						aria-label={t("staff.timeline.next")}
						onClick={onNext}
						disabled={isLast}
						className={NAV_BUTTON}
					>
						<ChevronRight className="size-4" />
					</button>
				</div>
			</div>

			<div
				className="flex flex-col gap-[22px] px-[22px] pt-6 pb-[26px]"
				data-testid="turn-why"
			>
				{(turn.customer_text_masked || turn.bot_text_masked) && (
					<div className="flex flex-col gap-2.5 rounded-[14px] border border-border bg-[#0B1328] p-[18px]">
						{turn.customer_text_masked && (
							<div className="flex max-w-[75%] flex-col items-end gap-1 self-end">
								<span className={EYEBROW}>
									{t("staff.timeline.customer_message")}
								</span>
								<p
									data-testid="turn-customer-text"
									className="rounded-[16px_16px_4px_16px] bg-[#0F3440] px-3.5 py-2.5 text-[15px] text-pretty"
								>
									{turn.customer_text_masked}
								</p>
							</div>
						)}
						{turn.bot_text_masked && (
							<div className="flex max-w-[75%] flex-col items-start gap-1 self-start">
								<span className={cn(EYEBROW, "flex items-center gap-1.5")}>
									<span
										aria-hidden="true"
										className="grid size-[18px] place-items-center rounded-full border border-cyan bg-[#0F3440] font-heading text-[10px] tracking-normal text-cyan"
									>
										C
									</span>
									{t("staff.timeline.cardy_reply")}
								</span>
								<p
									data-testid="turn-reply-text"
									className="rounded-[16px_16px_16px_4px] border border-border bg-card px-3.5 py-2.5 text-[15px] text-pretty"
								>
									{turn.bot_text_masked}
								</p>
							</div>
						)}
					</div>
				)}

				<dl className="m-0 grid grid-cols-1 gap-x-6 md:grid-cols-[200px_minmax(0,1fr)]">
					<Row label={t("staff.timeline.nlu")}>
						{turn.nlu ? (
							<pre
								data-testid="turn-nlu"
								className="m-0 overflow-x-auto rounded-[10px] border border-border bg-[#0B1328] px-4 py-3.5 font-mono text-[13px] leading-relaxed text-foreground"
							>
								{JSON.stringify(turn.nlu, null, 2)}
							</pre>
						) : (
							none
						)}
					</Row>

					<Row label={t("staff.timeline.rules_hit")}>
						{turn.rules.length === 0 ? (
							none
						) : (
							<ul className="flex flex-col gap-1.5">
								{turn.rules.map((rule, ruleIndex) => (
									<li
										// biome-ignore lint/suspicious/noArrayIndexKey: rule events carry no stable id
										key={`${rule.at}-${ruleIndex}`}
										data-testid="turn-rule"
										className={cn(
											MONO,
											"self-start rounded-md border border-border bg-[#0B1328] px-2.5 py-[3px]",
										)}
									>
										{ruleName(rule.payload)}
									</li>
								))}
							</ul>
						)}
					</Row>

					<Row label={t("staff.timeline.tools")}>
						{turn.tools.length === 0 ? (
							none
						) : (
							<ul className="flex flex-col gap-1.5">
								{turn.tools.map((tool, toolIndex) => {
									const isCall = tool.type === "tool_call";
									return (
										<li
											// biome-ignore lint/suspicious/noArrayIndexKey: tool events carry no stable id
											key={`${tool.type}-${toolIndex}`}
											data-testid="turn-tool"
											className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-2.5"
										>
											<span
												className={cn(
													"rounded-full border px-2 py-0.5 text-center font-mono text-xs font-semibold",
													isCall
														? "border-cyan text-cyan"
														: "border-ok text-ok",
												)}
											>
												{tool.type}
											</span>
											<code
												className={cn(
													MONO,
													"text-foreground [overflow-wrap:anywhere]",
												)}
											>
												{JSON.stringify(tool.payload)}
											</code>
										</li>
									);
								})}
							</ul>
						)}
					</Row>

					<Row label={t("staff.timeline.sources")}>
						{sources.length === 0 ? (
							none
						) : (
							<ul className="flex flex-col gap-1.5">
								{sources.map((source) => (
									<li
										key={source}
										data-testid="turn-source"
										className={cn(MONO, "flex items-center gap-2")}
									>
										<span
											aria-hidden="true"
											className="size-1.5 rounded-[2px] bg-cyan"
										/>
										{source}
									</li>
								))}
							</ul>
						)}
					</Row>

					<Row label={t("staff.timeline.policy_version")}>
						{turn.policy_version ? (
							<span data-testid="turn-policy-version" className={MONO}>
								{turn.policy_version}
							</span>
						) : (
							none
						)}
					</Row>

					<Row label={t("staff.timeline.llm_calls")}>
						{turn.llm_calls.length === 0 ? (
							none
						) : (
							<ul className="flex flex-col gap-1.5">
								{turn.llm_calls.map((call, callIndex) => (
									<li
										// biome-ignore lint/suspicious/noArrayIndexKey: a step can repeat across retries
										key={`${call.step}-${call.attempt}-${callIndex}`}
										data-testid="turn-llm-call"
										className="flex flex-wrap items-center gap-2 text-sm"
									>
										<span className="font-semibold">{call.step}</span>
										<Dot />
										<span className={MONO}>{call.model_id}</span>
										<Dot />
										<span className={cn(MONO, "text-muted-foreground")}>
											{call.prompt_version}
										</span>
										<Dot />
										<span className="tabular-nums">
											{formatMs(call.latency_ms, lang)}
										</span>
										{call.cost_usd !== null && (
											<>
												<Dot />
												<span className="text-gold tabular-nums">
													{formatUsd(call.cost_usd)}
												</span>
											</>
										)}
									</li>
								))}
							</ul>
						)}
					</Row>
				</dl>

				<div className="flex flex-wrap items-center gap-4 border-t border-border pt-[18px]">
					<div className={STAT} data-testid="turn-latency">
						<span className={EYEBROW}>{t("staff.timeline.turn_latency")}</span>
						<span className="text-[22px] font-semibold tabular-nums">
							{formatMs(turn.latency_ms, lang)}
						</span>
					</div>
					<div className={STAT} data-testid="turn-cost">
						<span className={EYEBROW}>{t("staff.timeline.turn_cost")}</span>
						<span className="text-[22px] font-semibold tabular-nums">
							{formatUsd(turn.cost_usd)}
						</span>
					</div>
					<div className="flex-1" />
					{turn.langfuse_url && (
						<a
							href={turn.langfuse_url}
							target="_blank"
							rel="noopener noreferrer"
							data-testid="turn-langfuse-link"
							className="inline-flex items-center gap-2 rounded-full border border-cyan px-[18px] py-2.5 text-sm font-semibold whitespace-nowrap text-cyan transition-transform duration-250 hover:translate-x-[3px] hover:border-foreground hover:text-foreground"
						>
							{t("staff.timeline.langfuse_link")}
							<ArrowUpRight className="size-3.5" />
						</a>
					)}
				</div>
			</div>
		</article>
	);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
	return (
		<>
			<dt className={ROW_TERM}>{label}</dt>
			<dd className={ROW_DATA}>{children}</dd>
		</>
	);
}

function Dot() {
	return (
		<span aria-hidden="true" className="text-border">
			·
		</span>
	);
}
