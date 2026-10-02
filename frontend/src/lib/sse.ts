// Typed wrapper over the native `EventSource` for `GET /conversations/{id}/stream`
// (D12, `04` §3 "SSE events"). It is a thin listener registry: `EventSource`
// itself owns the connection, the retry backoff and the reconnect, so there
// is nothing to replay here (R11 doesn't apply to a read-only stream).

/** One clickable option, code-formatted server-side (R4). */
export type PickerOption = { label: string };

export type CardPickerPayload = { options: PickerOption[] };
export type CardPickerUiEvent = {
	kind: "card_picker";
	payload: CardPickerPayload;
};

export type QuickRepliesPayload = {
	slot: "block_kind" | "abstain" | "next_step";
	options: PickerOption[];
};
export type QuickRepliesUiEvent = {
	kind: "quick_replies";
	payload: QuickRepliesPayload;
};

/** One confirmation-plan step, exactly as `ui.py`'s `ConfirmStepView` sends it. */
export type ConfirmStepView = {
	tool: string;
	summary_key: string;
	facts: { key: string; value: string | number | null; source: string }[];
};
export type ConfirmPayload = { token_id: string; steps: ConfirmStepView[] };
export type ConfirmUiEvent = { kind: "confirm"; payload: ConfirmPayload };

export type OtpRequiredPayload = { tool: string };
export type OtpRequiredUiEvent = {
	kind: "otp_required";
	payload: OtpRequiredPayload;
};

export type ConversationClosedUiEvent = {
	kind: "conversation_closed";
	payload: Record<string, never>;
};

/** One offered transaction: its id and its code-formatted label (R4, D13). */
export type TxOption = { tx_id: string; label: string };

/** `multi=false` for `decline_explain`'s single-pick offer (D3); `true` for
 * `unrecognized_charge`'s multi-select. */
export type TransactionListPayload = { options: TxOption[]; multi: boolean };
export type TransactionListUiEvent = {
	kind: "transaction_list";
	payload: TransactionListPayload;
};

export type Queue = "atencion" | "cobranza" | "fraudes" | "reclamos";

/**
 * `reference`, `queue_label` and every `case_ids` entry are code-formatted
 * server-side (R4). `case_ids` is empty unless the bot opened claims first.
 */
export type HandoffBannerPayload = {
	handoff_id: string;
	reference: string;
	queue: Queue;
	queue_label: string;
	case_ids: string[];
};
export type HandoffBannerUiEvent = {
	kind: "handoff_banner";
	payload: HandoffBannerPayload;
};

/** The seven `ui` kinds this card renders (`04` §3). */
export type UiEvent =
	| CardPickerUiEvent
	| QuickRepliesUiEvent
	| ConfirmUiEvent
	| OtpRequiredUiEvent
	| ConversationClosedUiEvent
	| TransactionListUiEvent
	| HandoffBannerUiEvent;

export type StatusPayload = { step: string };
export type MessagePayload = {
	role: "bot" | "customer" | "agent" | "system";
	text: string;
	sources: string[];
	agent_display_name?: string | null;
};
export type ErrorPayload = { code: string };
export type DonePayload = { turn_id: string };

/** `04` §3 `mode` event: who is answering right now (D4-B, A emits it). */
export type ModePayload = {
	mode: "bot" | "human";
	agent_display_name: string | null;
};

export type ConversationStreamHandlers = {
	onStatus: (payload: StatusPayload) => void;
	onMessage: (payload: MessagePayload) => void;
	onUi: (event: UiEvent) => void;
	onMode: (payload: ModePayload) => void;
	onError: (payload: ErrorPayload) => void;
	onDone: (payload: DonePayload) => void;
	/** Fires on every drop; `EventSource` reconnects on its own, no replay. */
	onReconnecting: () => void;
	/** Fires once the (re)connection is live, clearing the banner. */
	onOpen: () => void;
};

function parse<T>(event: Event): T {
	return JSON.parse((event as globalThis.MessageEvent).data) as T;
}

/**
 * Opens the stream and wires the event names this card renders. `debug` is
 * intentionally left unhandled: it arrives under its own SSE `event:` name,
 * so the default `message` listener never sees it, and it is simply never
 * delivered anywhere (D12).
 *
 * Returns a cleanup function that closes the connection.
 */
export function openConversationStream(
	conversationId: string,
	handlers: ConversationStreamHandlers,
): () => void {
	const source = new EventSource(
		`/api/v1/conversations/${conversationId}/stream`,
	);

	source.addEventListener("status", (event) => {
		handlers.onStatus(parse<StatusPayload>(event));
	});
	source.addEventListener("message", (event) => {
		handlers.onMessage(parse<MessagePayload>(event));
	});
	source.addEventListener("ui", (event) => {
		handlers.onUi(parse<UiEvent>(event));
	});
	// `error` is a reserved `EventSource` type: a dropped connection dispatches
	// a plain `Event` here, and the server's named `event: error` frame also
	// dispatches *here* (the SSE event name becomes the DOM event type), as a
	// `MessageEvent` with `.data`. `onerror`/`addEventListener` would both fire
	// on every one of these, so there is exactly one listener that branches on
	// the event class instead of two competing handlers (D12, R11 n/a: this is
	// a read-only stream `EventSource` itself retries).
	source.addEventListener("error", (event) => {
		if (event instanceof globalThis.MessageEvent) {
			handlers.onError(parse<ErrorPayload>(event));
		} else {
			handlers.onReconnecting();
		}
	});
	source.addEventListener("done", (event) => {
		handlers.onDone(parse<DonePayload>(event));
	});
	source.addEventListener("mode", (event) => {
		handlers.onMode(parse<ModePayload>(event));
	});

	source.onopen = () => handlers.onOpen();

	return () => source.close();
}

/** The subset of `ConversationStreamHandlers` `AgentChat` actually renders. */
export type AgentConversationStreamHandlers = Pick<
	ConversationStreamHandlers,
	"onMessage" | "onError" | "onReconnecting" | "onOpen"
>;

/**
 * `GET /staff/conversations/{id}/stream` (D6, `04` §3): the same `message`
 * and `error` event shapes as the customer stream, since it is the same
 * conversation's transcript, just viewed from the claimed agent's side
 * (`role` already tells bot/customer/agent apart). The agent view has no use
 * for `status`, `ui` or `mode` (that is exactly what it is), so those event
 * names are simply never listened for here.
 */
export function openAgentConversationStream(
	conversationId: string,
	handlers: AgentConversationStreamHandlers,
): () => void {
	const source = new EventSource(
		`/api/v1/staff/conversations/${conversationId}/stream`,
	);

	source.addEventListener("message", (event) => {
		handlers.onMessage(parse<MessagePayload>(event));
	});
	source.addEventListener("error", (event) => {
		if (event instanceof globalThis.MessageEvent) {
			handlers.onError(parse<ErrorPayload>(event));
		} else {
			handlers.onReconnecting();
		}
	});

	source.onopen = () => handlers.onOpen();

	return () => source.close();
}
