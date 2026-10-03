import { useI18n } from "@/lib/i18n";

/** Short "includes simulated data" chip for the page header (D6, D7). */
export function MockBadge({ show }: { show: boolean }) {
	const { t } = useI18n();
	if (!show) {
		return null;
	}
	return (
		<span
			data-testid="analytics-mock-badge"
			className="rounded-full border border-input px-2 py-0.5 text-xs text-muted-foreground"
		>
			{t("staff.analytics.mock_badge")}
		</span>
	);
}

/** The simulated-data disclaimer at the foot of the page, one line (full text in the title) (D6, D7). */
export function MockFooter({ show }: { show: boolean }) {
	const { t } = useI18n();
	if (!show) {
		return null;
	}
	return (
		<p
			data-testid="analytics-mock-footer"
			title={t("staff.analytics.mock_footer")}
			className="truncate text-[11px] text-muted-foreground"
		>
			{t("staff.analytics.mock_footer")}
		</p>
	);
}
