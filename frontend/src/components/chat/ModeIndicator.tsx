import { useI18n } from "@/lib/i18n";

type ModeIndicatorProps = {
	mode: "bot" | "human";
	agentDisplayName: string | null;
};

/**
 * The chat header name: "Cardy" by default, the agent's own `display_name`
 * once a human has taken the case over (D4-B D13, `04` §3 `mode`).
 * `agentDisplayName` reaches here already formatted server-side (R4); this
 * component never edits it, only chooses whether to show it.
 */
export function ModeIndicator({ mode, agentDisplayName }: ModeIndicatorProps) {
	const { t } = useI18n();
	const name =
		mode === "human" && agentDisplayName
			? agentDisplayName
			: t("chat.bot_name");
	return (
		<div
			data-testid="mode-indicator"
			className="px-4 py-2 font-heading text-cyan"
		>
			{name}
		</div>
	);
}
