import { ChevronDown } from "lucide-react";
import { type ReactNode, useId } from "react";

import { type TKey, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export type Outcome = "resolved" | "clarified" | "abstained" | "handoff";
export type Queue = "atencion" | "cobranza" | "fraudes" | "reclamos";
/** `none` (no handoff), `any`, or one queue (D7-A D19). */
export type Escalation = "none" | "any" | Queue;

/**
 * The URL-held slice of `GET /staff/conversations`'s query (D7-A D19).
 * `limit`/`offset` stay out of the URL: this screen has no pager yet, only
 * the closed-enum and date-range filters. Every field is optional so the
 * route's `validateSearch` can drop an absent one from the URL instead of
 * writing `key=null`.
 */
export type ConversationSearchFilters = {
	language?: "es" | "pt";
	country?: "MX" | "CO" | "AR";
	intent?: string;
	outcome?: Outcome;
	escalation?: Escalation;
	date_from?: string;
	date_to?: string;
};

type ConversationFiltersProps = {
	value: ConversationSearchFilters;
	onChange: (next: ConversationSearchFilters) => void;
};

const LANGUAGES = ["es", "pt"] as const;
const COUNTRIES = ["MX", "CO", "AR"] as const;
export const OUTCOMES: Outcome[] = [
	"resolved",
	"clarified",
	"abstained",
	"handoff",
];
export const QUEUES: Queue[] = ["atencion", "cobranza", "fraudes", "reclamos"];
// Only the intents a case actually lands on today; the full 25-item NLU
// catalog would swamp the picker with values no conversation ever has.
export const INTENTS = [
	"card_status",
	"balance_due",
	"decline_explain",
	"transaction_search",
	"pending_reversal_explain",
	"card_block",
	"card_unlock",
	"unrecognized_charge",
	"replacement_request",
	"human_request",
];

// An active filter gets a cyan border ("Swip Staff Conversaciones" design).
const CONTROL =
	"h-10 rounded-[10px] border bg-bg text-sm font-semibold text-foreground [color-scheme:dark] focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none";

function controlBorder(active: boolean) {
	return active ? "border-cyan" : "border-border";
}

type FieldProps = {
	label: string;
	className?: string;
	/** Renders the control, given the id its label points at. */
	children: (id: string) => ReactNode;
};

function Field({ label, className, children }: FieldProps) {
	const id = useId();
	return (
		<div className={cn("flex flex-col gap-1.5", className)}>
			<label
				htmlFor={id}
				className="text-xs font-semibold tracking-[0.06em] text-muted-foreground uppercase"
			>
				{label}
			</label>
			{children(id)}
		</div>
	);
}

type SelectProps = {
	id: string;
	testId: string;
	value: string | undefined;
	onChange: (value: string | undefined) => void;
	children: ReactNode;
};

function Select({ id, testId, value, onChange, children }: SelectProps) {
	return (
		<span className="relative flex">
			<select
				id={id}
				data-testid={testId}
				className={cn(
					CONTROL,
					controlBorder(Boolean(value)),
					"w-full cursor-pointer appearance-none pr-9 pl-3.5",
				)}
				value={value ?? ""}
				onChange={(event) => onChange(event.target.value || undefined)}
			>
				{children}
			</select>
			<ChevronDown
				aria-hidden="true"
				className="pointer-events-none absolute top-1/2 right-3 size-3 -translate-y-1/2 text-muted-foreground"
				strokeWidth={2.5}
			/>
		</span>
	);
}

/**
 * The filter bar: language, country, intent, outcome, escalation and a date
 * range. Every value lives in the caller's URL search params (the route's
 * `validateSearch`), never local state, so a filter change is a
 * `navigate({ search })` and the list stays a plain, shareable `GET` of the
 * current URL. Options are the closed catalogs the API accepts (D7-A D19);
 * showing a fixed enum's raw or dictionary form is not the server-formatted
 * text R4 is about (same call `InboxList` and `PacketView` make for `queue`).
 */
export function ConversationFilters({
	value,
	onChange,
}: ConversationFiltersProps) {
	const { t } = useI18n();
	const all = t("staff.conversations.filter.all");
	const anyActive = Object.values(value).some(Boolean);

	return (
		<section
			aria-label={t("staff.conversations.filters")}
			className="flex flex-wrap items-end gap-3 rounded-2xl border border-border bg-card px-[18px] py-4"
		>
			<Field
				label={t("staff.conversations.filter.language")}
				className="min-w-[110px]"
			>
				{(id) => (
					<Select
						id={id}
						testId="filter-language"
						value={value.language}
						onChange={(language) =>
							onChange({
								...value,
								language: language as ConversationSearchFilters["language"],
							})
						}
					>
						<option value="">{all}</option>
						{LANGUAGES.map((lang) => (
							<option key={lang} value={lang}>
								{t(`lang.${lang}`)}
							</option>
						))}
					</Select>
				)}
			</Field>

			<Field
				label={t("staff.conversations.filter.country")}
				className="min-w-[110px]"
			>
				{(id) => (
					<Select
						id={id}
						testId="filter-country"
						value={value.country}
						onChange={(country) =>
							onChange({
								...value,
								country: country as ConversationSearchFilters["country"],
							})
						}
					>
						<option value="">{all}</option>
						{COUNTRIES.map((country) => (
							<option key={country} value={country}>
								{country}
							</option>
						))}
					</Select>
				)}
			</Field>

			<Field
				label={t("staff.conversations.filter.intent")}
				className="min-w-[230px]"
			>
				{(id) => (
					<Select
						id={id}
						testId="filter-intent"
						value={value.intent}
						onChange={(intent) => onChange({ ...value, intent })}
					>
						<option value="">{all}</option>
						{INTENTS.map((intent) => (
							<option key={intent} value={intent}>
								{intent}
							</option>
						))}
					</Select>
				)}
			</Field>

			<Field
				label={t("staff.conversations.filter.outcome")}
				className="min-w-[160px]"
			>
				{(id) => (
					<Select
						id={id}
						testId="filter-outcome"
						value={value.outcome}
						onChange={(outcome) =>
							onChange({ ...value, outcome: outcome as Outcome | undefined })
						}
					>
						<option value="">{all}</option>
						{OUTCOMES.map((outcome) => (
							<option key={outcome} value={outcome}>
								{t(`staff.conversations.outcome.${outcome}` as TKey)}
							</option>
						))}
					</Select>
				)}
			</Field>

			<Field
				label={t("staff.conversations.filter.escalation")}
				className="min-w-[160px]"
			>
				{(id) => (
					<Select
						id={id}
						testId="filter-escalation"
						value={value.escalation}
						onChange={(escalation) =>
							onChange({
								...value,
								escalation: escalation as Escalation | undefined,
							})
						}
					>
						<option value="">{all}</option>
						<option value="none">
							{t("staff.conversations.escalation.none")}
						</option>
						<option value="any">
							{t("staff.conversations.escalation.any")}
						</option>
						{QUEUES.map((queue) => (
							<option key={queue} value={queue}>
								{t(`staff.queue.${queue}` as TKey)}
							</option>
						))}
					</Select>
				)}
			</Field>

			<Field label={t("staff.conversations.filter.date_from")}>
				{(id) => (
					<input
						id={id}
						type="date"
						data-testid="filter-date-from"
						className={cn(
							CONTROL,
							controlBorder(Boolean(value.date_from)),
							"px-3",
						)}
						value={value.date_from ?? ""}
						onChange={(event) =>
							onChange({ ...value, date_from: event.target.value || undefined })
						}
					/>
				)}
			</Field>

			<Field label={t("staff.conversations.filter.date_to")}>
				{(id) => (
					<input
						id={id}
						type="date"
						data-testid="filter-date-to"
						className={cn(
							CONTROL,
							controlBorder(Boolean(value.date_to)),
							"px-3",
						)}
						value={value.date_to ?? ""}
						onChange={(event) =>
							onChange({ ...value, date_to: event.target.value || undefined })
						}
					/>
				)}
			</Field>

			{anyActive && (
				<button
					type="button"
					data-testid="filter-clear"
					onClick={() => onChange({})}
					className="h-10 cursor-pointer rounded-full px-4 text-sm font-semibold whitespace-nowrap text-cyan hover:text-foreground"
				>
					{t("staff.conversations.filter.clear")}
				</button>
			)}
		</section>
	);
}
