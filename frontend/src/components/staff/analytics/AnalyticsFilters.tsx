import type { AppliedFilters } from "@/client";
import type { AnalyticsQuery } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type AnalyticsFiltersProps = {
	value: AnalyticsQuery;
	/** The server-resolved filters (D11 defaults), shown while `value` is unset. */
	applied: AppliedFilters | undefined;
	onChange: (next: AnalyticsQuery) => void;
};

const LANGUAGES = ["es", "pt"] as const;
const COUNTRIES = ["MX", "CO", "AR"] as const;
const SOURCES = ["all", "real", "mock"] as const;

// `color-scheme: dark` + an opaque background so the browser draws the open
// option list (and the date picker) dark too, not white with light text.
const CONTROL_CLASSNAME =
	"h-8 rounded-lg border border-input bg-bg px-2 text-sm text-foreground [color-scheme:dark]";

/**
 * The analytics filter bar: a date range, language, country and data source.
 * Same native-control pattern as `ConversationFilters`. The route owns the
 * query; the date inputs fall back to the defaults the server resolved so the
 * bar always shows the range the numbers cover.
 */
export function AnalyticsFilters({
	value,
	applied,
	onChange,
}: AnalyticsFiltersProps) {
	const { t } = useI18n();
	const all = t("staff.analytics.filter.all");

	return (
		<div className="flex flex-wrap items-center gap-2">
			<input
				type="date"
				data-testid="analytics-filter-date-from"
				aria-label={t("staff.analytics.filter.date_from")}
				className={CONTROL_CLASSNAME}
				value={value.date_from ?? applied?.date_from ?? ""}
				onChange={(event) =>
					onChange({ ...value, date_from: event.target.value || undefined })
				}
			/>
			<input
				type="date"
				data-testid="analytics-filter-date-to"
				aria-label={t("staff.analytics.filter.date_to")}
				className={CONTROL_CLASSNAME}
				value={value.date_to ?? applied?.date_to ?? ""}
				onChange={(event) =>
					onChange({ ...value, date_to: event.target.value || undefined })
				}
			/>

			<select
				data-testid="analytics-filter-language"
				aria-label={t("staff.analytics.filter.language")}
				className={CONTROL_CLASSNAME}
				value={value.language ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						language: (event.target.value || undefined) as
							| AnalyticsQuery["language"]
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
				data-testid="analytics-filter-country"
				aria-label={t("staff.analytics.filter.country")}
				className={CONTROL_CLASSNAME}
				value={value.country ?? ""}
				onChange={(event) =>
					onChange({
						...value,
						country: (event.target.value || undefined) as
							| AnalyticsQuery["country"]
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
				data-testid="analytics-filter-source"
				aria-label={t("staff.analytics.filter.source")}
				className={CONTROL_CLASSNAME}
				value={value.source ?? "all"}
				onChange={(event) =>
					onChange({
						...value,
						source: event.target.value as AnalyticsQuery["source"],
					})
				}
			>
				{SOURCES.map((source) => (
					<option key={source} value={source}>
						{t(`staff.analytics.source.${source}`)}
					</option>
				))}
			</select>
		</div>
	);
}
