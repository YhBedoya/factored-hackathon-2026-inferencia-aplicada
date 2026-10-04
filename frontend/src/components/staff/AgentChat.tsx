import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, getStaffTranscript, postAgentMessage } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import { type MessagePayload, openAgentConversationStream } from "@/lib/sse";
import { cn } from "@/lib/utils";
import { newId } from "@/lib/uuid";

type AgentChatProps = {
	conversationId: string;
	// The handoff reference, shown next to the title as the server sent it.
	reference: string;
};

type AgentTranscriptMessage = Pick<MessagePayload, "role" | "text"> & {
	id: string;
};

// The live stream's state: nothing is shown until it first opens.
type StreamState = "connecting" | "live" | "reconnecting";

// "Swip Staff Caso" design: the customer and Cardy speak from the left, the
// agent from the right (in cyan), and a system note is a centered pill.
const BUBBLE: Record<
	Exclude<MessagePayload["role"], "system">,
	{ row: string; bubble: string; label: string }
> = {
	customer: {
		row: "items-start",
		bubble: "rounded-[16px_16px_16px_4px] border border-border bg-card",
		label: "text-muted-foreground",
	},
	bot: {
		row: "items-start",
		bubble: "rounded-[16px_16px_16px_4px] bg-cyan-deep",
		label: "text-cyan",
	},
	agent: {
		row: "items-end",
		bubble: "rounded-[16px_16px_4px_16px] bg-cyan text-bg",
		label: "text-cyan",
	},
};

/**
 * The claimed conversation's view (D6, `04` §3 events). It first loads the
 * messages so far (`GET /staff/conversations/{id}/messages`), so the agent
 * sees what the customer and Cardy already said, then follows the live
 * stream, which carries the same `message` shape (`role: bot | customer |
 * agent | system`). An agent's own reply comes back over this same stream
 * once relayed, so the composer never appends it optimistically -- only the
 * server is the source of truth for the transcript.
 */
export function AgentChat({ conversationId, reference }: AgentChatProps) {
	const { t } = useI18n();
	const [messages, setMessages] = useState<AgentTranscriptMessage[]>([]);
	const [value, setValue] = useState("");
	const [sending, setSending] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const [stream, setStream] = useState<StreamState>("connecting");
	const cleanupRef = useRef<(() => void) | null>(null);
	const logRef = useRef<HTMLDivElement | null>(null);

	useEffect(() => {
		let cancelled = false;
		cleanupRef.current?.();
		setMessages([]);
		setStream("connecting");

		function follow() {
			cleanupRef.current = openAgentConversationStream(conversationId, {
				onMessage: (payload) => {
					setMessages((prev) => [
						...prev,
						{ role: payload.role, text: payload.text, id: newId() },
					]);
				},
				onError: () => {},
				onReconnecting: () => setStream("reconnecting"),
				onOpen: () => setStream("live"),
			});
		}

		// The stream opens only after the history lands, so a live message is
		// never rendered above the older ones it follows.
		getStaffTranscript(conversationId)
			.then((history) => {
				if (cancelled) {
					return;
				}
				setMessages(
					history.map((message) => ({
						role: message.role,
						text: message.text,
						id: newId(),
					})),
				);
				follow();
			})
			.catch(() => {
				if (!cancelled) {
					follow();
				}
			});

		return () => {
			cancelled = true;
			cleanupRef.current?.();
			cleanupRef.current = null;
		};
	}, [conversationId]);

	// Keep the newest message in view as the transcript grows.
	// biome-ignore lint/correctness/useExhaustiveDependencies: runs on each new message
	useEffect(() => {
		const log = logRef.current;
		if (log) {
			log.scrollTop = log.scrollHeight;
		}
	}, [messages]);

	async function handleSend() {
		const text = value.trim();
		if (!text) {
			return;
		}
		setSending(true);
		setErrorCode(null);
		try {
			await postAgentMessage(conversationId, text);
			setValue("");
		} catch (error) {
			setErrorCode(error instanceof ApiError ? error.code : "generic");
		} finally {
			setSending(false);
		}
	}

	return (
		<div className="flex flex-col gap-3" data-testid="agent-chat">
			<div className="flex items-center justify-between gap-3">
				<h2 className="text-base font-semibold">
					{t("staff.chat.title")} ·{" "}
					<span className="font-mono text-sm font-medium whitespace-nowrap text-muted-foreground">
						{reference}
					</span>
				</h2>
				{stream !== "connecting" && (
					<span
						data-testid="agent-chat-stream"
						className="flex items-center gap-2 text-xs text-muted-foreground"
					>
						<span
							aria-hidden="true"
							className={cn(
								"size-2 rounded-full",
								stream === "live" ? "bg-ok" : "bg-gold",
							)}
						/>
						{t(
							stream === "live" ? "staff.chat.live" : "staff.chat.reconnecting",
						)}
					</span>
				)}
			</div>
			<div
				ref={logRef}
				className="flex h-[60vh] max-h-96 flex-col gap-3 overflow-y-auto rounded-2xl border border-border bg-surface p-4 lg:max-h-none"
			>
				{messages.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						{t("staff.chat.empty")}
					</p>
				) : (
					messages.map((message) =>
						message.role === "system" ? (
							<p
								key={message.id}
								data-testid="agent-chat-message-system"
								className="self-center rounded-full border border-border px-3 py-1 text-center text-xs text-muted-foreground"
							>
								{message.text}
							</p>
						) : (
							<div
								key={message.id}
								data-testid={`agent-chat-message-${message.role}`}
								className={cn("flex flex-col gap-1", BUBBLE[message.role].row)}
							>
								<span
									className={cn(
										"px-1 text-xs font-semibold",
										BUBBLE[message.role].label,
									)}
								>
									{t(`staff.chat.role.${message.role}` as TKey)}
								</span>
								<p
									className={cn(
										"max-w-[80%] px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]",
										BUBBLE[message.role].bubble,
									)}
								>
									{message.text}
								</p>
							</div>
						),
					)
				)}
			</div>
			<form
				className="flex gap-2"
				onSubmit={(event) => {
					event.preventDefault();
					void handleSend();
				}}
			>
				<Input
					data-testid="agent-chat-input"
					value={value}
					placeholder={t("staff.chat.placeholder")}
					onChange={(event) => setValue(event.target.value)}
					disabled={sending}
					className="h-11 rounded-full border-border bg-surface px-4"
				/>
				<Button
					type="submit"
					data-testid="agent-chat-send"
					disabled={sending || value.trim().length === 0}
					className="h-11 rounded-full px-[22px] font-semibold"
				>
					{t(sending ? "staff.chat.sending" : "staff.chat.send")}
				</Button>
			</form>
			{errorCode && (
				<p role="alert" className="text-sm text-alert">
					{t("errors.generic")}
				</p>
			)}
		</div>
	);
}
