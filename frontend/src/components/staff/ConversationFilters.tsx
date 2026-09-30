import { type TKey, useI18n } from "@/lib/i18n";
import type {
	ConversationFilters as ConversationFiltersShape,
	ConversationOutcome,
	HandoffReason,
	Intent,
} from "@/lib/traceability";

/**
 * The URL-held slice of `ConversationFilters` (D13). `limit`/`offset` stay
 * out of the URL: this screen has no pager yet, only the closed-enum and
 * date-range filters the spec lists. Every field is optional so the route's
 * `validateSearch` can drop an absent one from the URL instead of writing
 * `key=null`.
 */
export type ConversationSearchFilters = {
	language?: ConversationFiltersShape["language"];
	country?: ConversationFiltersShape["country"];
	intent?: Intent;
	outcome?: ConversationOutcome;
	escalation?: HandoffReason;
	date_from?: string;
	date_to?: string;
};

type ConversationFiltersProps = {
	value: ConversationSearchFilters;
	onChange: (next: ConversationSearchFilters) => void;
};

const LANGUAGES = ["es", "pt"] as const;
const COUNTRIES = ["MX", "CO", "AR"] as const;
const OUTCOMES: ConversationOutcome[] = [
	"resolved",
	"clarified",
	"abstained",
	"handoff",
];
// The full `HandoffReason` catalog (`staff.reason.<slug>`, same dictionary
// `InboxList`/`PacketView` already read from).
const ESCALATIONS: HandoffReason[] = [
	"human_request",
	"clarification_exhausted",
	"legal_regulator",
	"customer_not_active",
	"bank_side_block",
	"action_unverified",
	"unauthorized_access",
	"suspected_fraud",
	"tool_failure",
	"llm_unavailable",
	"priority_claim",
];
// Only the intents a case actually lands on today; the full 25-item NLU
// catalog would swamp the picker with values no conversation ever has.
const INTENTS: Intent[] = [
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

const SELECT_CLASSNAME =
	"h-8 rounded-lg border border-input bg-transparent px-2 text-sm text-foreground";

/**
 * D13's filter bar: language, country, intent, outcome, escalation and a
 * date range. Every value lives in the caller's URL search params (the
 * route's `validateSearch`), never local state, so a filter change is a
 * `navigate({ search })` and the list stays a plain, shareable `GET` of the
 * current URL. Options are the closed catalogs the backend contracts pin
 * (`Intent`, `HandoffReason`); showing a fixed enum's raw or dictionary form
 * is not the server-formatted text R4 is about (same call `InboxList` and
 * `PacketView` already make for `queue`/`reason`).
 */
export function ConversationFilters({
	value,
	onChange,
}: ConversationFiltersProps) {
	const { t } = useI18n();
	const all = t("staff.conversations.filter.all");

	return (
		<div className="flex flex-wrap gap-3">
			<select
				data-testid="filter-language"
				className={SELECT_CLASSNAME}
				value={value.language ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						language: (event.target.value || undefined) as
							| ConversationSearchFilters["language"]
							| undefined,
					})
				}
			>
				<option value="">{all}</option>
				{LANGUAGES.map((lang) => (
					<option key={lang} value={lang}>
						{t(`lang.${lang}`)}
					</option>
				))}
			</select>

			<select
				data-testid="filter-country"
				className={SELECT_CLASSNAME}
				value={value.country ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						country: (event.target.value || undefined) as
							| ConversationSearchFilters["country"]
							| undefined,
					})
				}
			>
				<option value="">{all}</option>
				{COUNTRIES.map((country) => (
					<option key={country} value={country}>
						{country}
					</option>
				))}
			</select>

			<select
				data-testid="filter-intent"
				className={SELECT_CLASSNAME}
				value={value.intent ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						intent: (event.target.value || undefined) as Intent | undefined,
					})
				}
			>
				<option value="">{all}</option>
				{INTENTS.map((intent) => (
					<option key={intent} value={intent}>
						{intent}
					</option>
				))}
			</select>

			<select
				data-testid="filter-outcome"
				className={SELECT_CLASSNAME}
				value={value.outcome ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						outcome: (event.target.value || undefined) as
							| ConversationOutcome
							| undefined,
					})
				}
			>
				<option value="">{all}</option>
				{OUTCOMES.map((outcome) => (
					<option key={outcome} value={outcome}>
						{t(`staff.conversations.outcome.${outcome}` as TKey)}
					</option>
				))}
			</select>

			<select
				data-testid="filter-escalation"
				className={SELECT_CLASSNAME}
				value={value.escalation ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						escalation: (event.target.value || undefined) as
							| HandoffReason
							| undefined,
					})
				}
			>
				<option value="">{all}</option>
				{ESCALATIONS.map((reason) => (
					<option key={reason} value={reason}>
						{t(`staff.reason.${reason}` as TKey)}
					</option>
				))}
			</select>

			<input
				type="date"
				data-testid="filter-date-from"
				className={SELECT_CLASSNAME}
				value={value.date_from ?? ""}
				onChange={(event) =>
					onChange({ ...value, date_from: event.target.value || undefined })
				}
			/>
			<input
				type="date"
				data-testid="filter-date-to"
				className={SELECT_CLASSNAME}
				value={value.date_to ?? ""}
				onChange={(event) =>
					onChange({ ...value, date_to: event.target.value || undefined })
				}
			/>
		</div>
	);
}
