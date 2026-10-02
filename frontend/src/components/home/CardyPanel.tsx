import { ChatView } from "@/components/chat/ChatView";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

// Side panel, full screen under `sm`. `prefill` only drops text into the
// composer; the customer presses send (D10), so nothing here posts. Closing
// unmounts the chat, and each open starts a new conversation with Cardy's
// welcome (`fresh`).
export function CardyPanel({
	open,
	prefill,
	onOpen,
	onClose,
}: {
	open: boolean;
	prefill: string | undefined;
	onOpen: () => void;
	onClose: () => void;
}) {
	const { t } = useI18n();
	return (
		<>
			{!open && (
				<Button
					type="button"
					data-testid="cardy-launcher"
					className="fixed right-4 bottom-4 z-20 shadow-lg"
					onClick={onOpen}
				>
					{t("home.cardy.launcher")}
				</Button>
			)}
			{open && (
				<aside
					data-testid="cardy-panel"
					aria-label={t("home.cardy.panel")}
					className="fixed inset-0 z-30 flex flex-col bg-background sm:inset-y-0 sm:right-0 sm:left-auto sm:w-105 sm:border-l sm:border-border"
				>
					{/* The chat's own name row says "Cardy" (or the agent's name), so the
					    panel adds only its close button to that row. */}
					<ChatView
						prefill={prefill}
						className="min-h-0 flex-1"
						fresh
						headerAction={
							<Button type="button" variant="ghost" size="sm" onClick={onClose}>
								{t("home.cardy.close")}
							</Button>
						}
					/>
				</aside>
			)}
		</>
	);
}
