import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, getStaffTranscript, postAgentMessage } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import { type MessagePayload, openAgentConversationStream } from "@/lib/sse";

type AgentChatProps = {
	conversationId: string;
};

type AgentTranscriptMessage = Pick<MessagePayload, "role" | "text"> & {
	id: string;
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
export function AgentChat({ conversationId }: AgentChatProps) {
	const { t } = useI18n();
	const [messages, setMessages] = useState<AgentTranscriptMessage[]>([]);
	const [value, setValue] = useState("");
	const [sending, setSending] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const cleanupRef = useRef<(() => void) | null>(null);

	useEffect(() => {
		let cancelled = false;
		cleanupRef.current?.();
		setMessages([]);

		function follow() {
			cleanupRef.current = openAgentConversationStream(conversationId, {
				onMessage: (payload) => {
					setMessages((prev) => [
						...prev,
						{ role: payload.role, text: payload.text, id: crypto.randomUUID() },
					]);
				},
				onError: () => {},
				onReconnecting: () => {},
				onOpen: () => {},
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
						id: crypto.randomUUID(),
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
		<div className="flex flex-col gap-2" data-testid="agent-chat">
			<h3 className="text-sm font-medium">{t("staff.chat.title")}</h3>
			<div className="flex max-h-96 flex-col gap-2 overflow-y-auto rounded-md border p-3 lg:h-[60vh] lg:max-h-none">
				{messages.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						{t("staff.chat.empty")}
					</p>
				) : (
					messages.map((message) => (
						<p
							key={message.id}
							data-testid={`agent-chat-message-${message.role}`}
							className="text-sm"
						>
							<span className="font-medium">
								{t(`staff.chat.role.${message.role}` as TKey)}:
							</span>{" "}
							{message.text}
						</p>
					))
				)}
			</div>
			<div className="flex gap-2">
				<Input
					data-testid="agent-chat-input"
					value={value}
					onChange={(event) => setValue(event.target.value)}
					disabled={sending}
				/>
				<Button
					type="button"
					data-testid="agent-chat-send"
					disabled={sending || value.trim().length === 0}
					onClick={() => void handleSend()}
				>
					{t("staff.chat.send")}
				</Button>
			</div>
			{errorCode && (
				<p role="alert" className="text-sm text-alert">
					{t("errors.generic")}
				</p>
			)}
		</div>
	);
}
