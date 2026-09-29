import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, postAgentMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { type MessagePayload, openAgentConversationStream } from "@/lib/sse";

type AgentChatProps = {
	conversationId: string;
};

type AgentTranscriptMessage = MessagePayload & { id: string };

/**
 * The claimed conversation's live view (D6, `04` §3 events). It reuses the
 * same `message` event shape the customer stream carries (`role: bot |
 * customer | agent`): an agent's own reply comes back over this same stream
 * once relayed, so the composer never appends it optimistically -- only the
 * stream is the source of truth for the transcript.
 */
export function AgentChat({ conversationId }: AgentChatProps) {
	const { t } = useI18n();
	const [messages, setMessages] = useState<AgentTranscriptMessage[]>([]);
	const [value, setValue] = useState("");
	const [sending, setSending] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const cleanupRef = useRef<(() => void) | null>(null);

	useEffect(() => {
		cleanupRef.current?.();
		setMessages([]);
		cleanupRef.current = openAgentConversationStream(conversationId, {
			onMessage: (payload) => {
				setMessages((prev) => [
					...prev,
					{ ...payload, id: crypto.randomUUID() },
				]);
			},
			onError: () => {},
			onReconnecting: () => {},
			onOpen: () => {},
		});
		return () => cleanupRef.current?.();
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
			<div className="flex flex-col gap-1 overflow-y-auto">
				{messages.map((message) => (
					<p
						key={message.id}
						data-testid={`agent-chat-message-${message.role}`}
					>
						{message.text}
					</p>
				))}
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
