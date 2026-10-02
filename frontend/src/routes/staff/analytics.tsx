import { useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";

import { AnalyticsFilters } from "@/components/staff/analytics/AnalyticsFilters";
import { CostChart } from "@/components/staff/analytics/CostChart";
import { EscalationsChart } from "@/components/staff/analytics/EscalationsChart";
import { IntentsChart } from "@/components/staff/analytics/IntentsChart";
import {
	MockBadge,
	MockFooter,
} from "@/components/staff/analytics/MockDataNotice";
import { OutcomesPerDayChart } from "@/components/staff/analytics/OutcomesPerDayChart";
import { RecentInteractionsTable } from "@/components/staff/analytics/RecentInteractionsTable";
import { SentimentChart } from "@/components/staff/analytics/SentimentChart";
import { SummaryTiles } from "@/components/staff/analytics/SummaryTiles";
import { type AnalyticsQuery, getAnalyticsSummary, staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const LANGUAGES = ["es", "pt"] as const;
const COUNTRIES = ["MX", "CO", "AR"] as const;
const SOURCES = ["all", "real", "mock"] as const;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function pick<T extends string>(
	value: unknown,
	allowed: readonly T[],
): T | undefined {
	return allowed.find((candidate) => candidate === value);
}

function pickDate(value: unknown): string | undefined {
	return typeof value === "string" && DATE_PATTERN.test(value)
		? value
		: undefined;
}

// D14: admin-only. A missing session goes to login; an agent session goes
// back to the inbox (the endpoint would answer 403 anyway, R13).
export const Route = createFileRoute("/staff/analytics")({
	beforeLoad: async () => {
		const staff = await staffMe();
		if (!staff) {
			throw redirect({ to: "/staff/login" });
		}
		if (staff.role !== "admin") {
			throw redirect({ to: "/staff" });
		}
	},
	// Unknown or malformed values are dropped, so a hand-edited URL never
	// reaches the API as a 422.
	validateSearch: (search: Record<string, unknown>): AnalyticsQuery => ({
		date_from: pickDate(search.date_from),
		date_to: pickDate(search.date_to),
		language: pick(search.language, LANGUAGES),
		country: pick(search.country, COUNTRIES),
		source: pick(search.source, SOURCES),
	}),
	component: StaffAnalyticsPage,
});

function StaffAnalyticsPage() {
	const { t } = useI18n();
	const search = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const { data, isLoading, isError } = useQuery({
		queryKey: ["staff", "analytics", search],
		queryFn: () => getAnalyticsSummary(search),
	});
	const block = { summary: data, isLoading, isError };

	return (
		<div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-6 py-10">
			<div className="flex flex-wrap items-center gap-3">
				<h1 className="font-heading text-2xl text-foreground">
					{t("staff.analytics.title")}
				</h1>
				<MockBadge show={data?.includes_mock ?? false} />
			</div>
			<AnalyticsFilters
				value={search}
				applied={data?.filters}
				onChange={(next) => navigate({ search: next })}
			/>
			<SummaryTiles {...block} />
			<OutcomesPerDayChart {...block} />
			<IntentsChart {...block} />
			<EscalationsChart {...block} />
			<SentimentChart {...block} />
			<CostChart {...block} />
			<RecentInteractionsTable {...block} />
			<MockFooter show={data?.includes_mock ?? false} />
		</div>
	);
}
