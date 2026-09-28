import { useI18n } from "@/lib/i18n";

/** One "Cardy is typing" indicator, shown for any `status` until the next `message` (D12). */
export function StatusIndicator() {
	const { t } = useI18n();

	return (
		<div
			data-testid="status-indicator"
			className="self-start text-sm text-muted-foreground italic"
		>
			{t("chat.typing")}
		</div>
	);
}
