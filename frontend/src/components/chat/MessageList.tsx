import { CardPicker } from "@/components/chat/CardPicker";
import { ConfirmCard } from "@/components/chat/ConfirmCard";
import { HandoffBanner } from "@/components/chat/HandoffBanner";
import { QuickReplies } from "@/components/chat/QuickReplies";
import { StatusIndicator } from "@/components/chat/StatusIndicator";
import { TransactionList } from "@/components/chat/TransactionList";
import type { ConfirmationDecision } from "@/lib/api";
import type { UiEvent } from "@/lib/sse";
import { cn } from "@/lib/utils";

export type TranscriptMessage = {
	id: string;
	role: "customer" | "bot" | "agent" | "system";
	text: string;
	/** The agent's `display_name` on an `agent` message (server-sent, R4). */
	author?: string | null;
	/** `ui` events held since the previous message, attached to this one (D12). */
	ui: UiEvent[];
};

type MessageListProps = {
	messages: TranscriptMessage[];
	typing: boolean;
	onWidgetSelect: (label: string) => void;
	onConfirmDecision: (tokenId: string, decision: ConfirmationDecision) => void;
	onTransactionSelect: (txIds: string[]) => void;
};

/**
 * The transcript. `otp_required` and `conversation_closed` are still held
 * per D12, but they render nothing here: the OTP modal and the "new
 * conversation" banner (both in `chat.tsx`) are their only UI.
 */
export function MessageList({
	messages,
	typing,
	onWidgetSelect,
	onConfirmDecision,
	onTransactionSelect,
}: MessageListProps) {
	return (
		<div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
			{messages.map((message) => (
				<div key={message.id} className="flex flex-col">
					{message.role === "agent" && message.author && (
						<span
							data-testid="message-agent-name"
							className="self-start px-1 text-xs text-muted-foreground"
						>
							{message.author}
						</span>
					)}
					<div
						data-testid={`message-${message.role}`}
						className={cn(
							"max-w-[80%] rounded-xl px-3 py-2 text-sm",
							message.role === "bot" && "self-start border border-cyan bg-card",
							message.role === "agent" &&
								"self-start border border-primary bg-card",
							message.role === "customer" &&
								"self-end bg-primary text-primary-foreground",
							message.role === "system" &&
								"self-center bg-transparent text-center text-xs text-muted-foreground",
						)}
					>
						{message.text}
					</div>
					{message.ui.map((event, index) => {
						switch (event.kind) {
							case "card_picker":
								return (
									<CardPicker
										// biome-ignore lint/suspicious/noArrayIndexKey: one turn emits at most one of each kind
										key={index}
										options={event.payload.options}
										onSelect={onWidgetSelect}
									/>
								);
							case "quick_replies":
								return (
									<QuickReplies
										// biome-ignore lint/suspicious/noArrayIndexKey: one turn emits at most one of each kind
										key={index}
										options={event.payload.options}
										onSelect={onWidgetSelect}
									/>
								);
							case "confirm":
								return (
									<ConfirmCard
										// biome-ignore lint/suspicious/noArrayIndexKey: one turn emits at most one of each kind
										key={index}
										payload={event.payload}
										onDecide={onConfirmDecision}
									/>
								);
							case "transaction_list":
								return (
									<TransactionList
										// biome-ignore lint/suspicious/noArrayIndexKey: one turn emits at most one of each kind
										key={index}
										options={event.payload.options}
										onSelect={onTransactionSelect}
									/>
								);
							case "handoff_banner":
								return (
									<HandoffBanner
										// biome-ignore lint/suspicious/noArrayIndexKey: one turn emits at most one of each kind
										key={index}
										payload={event.payload}
									/>
								);
							default:
								return null;
						}
					})}
				</div>
			))}
			{typing && <StatusIndicator />}
		</div>
	);
}
