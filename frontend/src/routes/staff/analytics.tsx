import { useQuery } from "@tanstack/react-query";
import {
	createFileRoute,
	Link,
	redirect,
	useNavigate,
} from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { LanguageToggle } from "@/components/layout/LanguageToggle";
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
import { StaffLogo } from "@/components/staff/StaffNav";
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

	// One viewport at lg and up (no page scroll): header line, KPI strip, a
	// 12 x 2 panel grid that takes the remaining height, footer. Below lg the
	// panels stack and the page scrolls; `min-h` lets a very short window
	// scroll instead of crushing the charts.
	return (
		<div className="flex w-full flex-1 flex-col gap-3 px-4 py-3 lg:h-svh lg:min-h-[640px] lg:flex-none lg:overflow-hidden">
			<div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
				<div className="flex flex-wrap items-center gap-3.5">
					<StaffLogo />
					<Link
						to="/staff"
						data-testid="analytics-back"
						className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
					>
						<ArrowLeft
							aria-hidden="true"
							className="size-4"
							strokeWidth={2.5}
						/>
						{t("staff.analytics.back")}
					</Link>
					<h1 className="font-heading text-xl text-foreground">
						{t("staff.analytics.title")}
					</h1>
					<MockBadge show={data?.includes_mock ?? false} />
				</div>
				<div className="flex flex-wrap items-center gap-3">
					<AnalyticsFilters
						value={search}
						applied={data?.filters}
						onChange={(next) => navigate({ search: next })}
					/>
					<LanguageToggle />
				</div>
			</div>
			<SummaryTiles {...block} />
			<div className="grid gap-3 lg:min-h-0 lg:flex-1 lg:grid-cols-12 lg:grid-rows-2">
				<div className="min-h-64 lg:col-span-4 lg:min-h-0">
					<OutcomesPerDayChart {...block} />
				</div>
				<div className="min-h-64 lg:col-span-5 lg:min-h-0">
					<IntentsChart {...block} />
				</div>
				<div className="min-h-64 lg:col-span-3 lg:min-h-0">
					<EscalationsChart {...block} />
				</div>
				<div className="min-h-64 lg:col-span-4 lg:min-h-0">
					<CostChart {...block} />
				</div>
				<div className="min-h-64 lg:col-span-2 lg:min-h-0">
					<SentimentChart {...block} />
				</div>
				<div className="min-h-64 lg:col-span-6 lg:min-h-0">
					<RecentInteractionsTable {...block} />
				</div>
			</div>
			<MockFooter show={data?.includes_mock ?? false} />
		</div>
	);
}
