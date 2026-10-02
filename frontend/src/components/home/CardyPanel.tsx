import { useEffect, useRef, useState } from "react";

import { ChatView } from "@/components/chat/ChatView";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

export type CardyPanelState = "closed" | "open" | "minimized";

// Side panel under the home's top bar (full screen under `sm`). `prefill`
// only drops text into the composer; the customer presses send (D10), so
// nothing here posts. Minimizing only hides the chat: it stays mounted, so
// the conversation and its stream survive, and a reply that lands meanwhile
// puts a dot on the launcher. Closing unmounts it, and the next open starts
// a new conversation with Cardy's welcome (`fresh`). A reload starts over too.
export function CardyPanel({
	state,
	prefill,
	onOpen,
	onMinimize,
	onClose,
}: {
	state: CardyPanelState;
	prefill: string | undefined;
	onOpen: () => void;
	onMinimize: () => void;
	onClose: () => void;
}) {
	const { t } = useI18n();
	const panelRef = useRef<HTMLElement>(null);
	const [unread, setUnread] = useState(false);
	const minimized = state === "minimized";

	// Back from minimized, the cursor returns to the composer. The first open
	// is covered by `Composer`'s own focus on mount.
	useEffect(() => {
		if (state === "open") {
			setUnread(false);
			panelRef.current
				?.querySelector<HTMLInputElement>('[data-testid="composer-input"]')
				?.focus();
		}
	}, [state]);

	return (
		<>
			{state !== "open" && (
				<button
					type="button"
					data-testid="cardy-launcher"
					className="fixed right-7 bottom-7 z-20 flex cursor-pointer items-center gap-2.5 rounded-full border border-cyan bg-card py-2 pr-[18px] pl-2 text-[15px] font-semibold whitespace-nowrap shadow-[0_12px_32px_rgba(0,0,0,.5)] hover:bg-muted"
					onClick={onOpen}
				>
					<span
						aria-hidden="true"
						className="relative grid size-8 place-items-center rounded-full bg-cyan/20 font-heading text-cyan"
					>
						C
						{unread && (
							<span
								data-testid="cardy-unread"
								className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full bg-gold ring-2 ring-card"
							/>
						)}
					</span>
					{t("home.cardy.launcher")}
					{unread && <span className="sr-only">{t("home.cardy.unread")}</span>}
				</button>
			)}
			{state !== "closed" && (
				<aside
					ref={panelRef}
					data-testid="cardy-panel"
					aria-label={t("home.cardy.panel")}
					hidden={minimized}
					className="fixed inset-0 z-30 flex flex-col bg-background sm:top-[69px] sm:right-0 sm:bottom-0 sm:left-auto sm:w-105 sm:border-l sm:border-border"
				>
					{/* The chat's own name row says "Cardy" (or the agent's name), so the
					    panel adds only its minimize and close buttons to that row. */}
					<ChatView
						prefill={prefill}
						className="min-h-0 flex-1"
						fresh
						onReply={() => {
							if (minimized) {
								setUnread(true);
							}
						}}
						headerAction={
							<div className="flex items-center gap-1">
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={onMinimize}
								>
									{t("home.cardy.minimize")}
								</Button>
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={onClose}
								>
									{t("home.cardy.close")}
								</Button>
							</div>
						}
					/>
				</aside>
			)}
		</>
	);
}
