import {
	createConversationApiV1ConversationsPost,
	type LoginRequest,
	loginApiV1AuthLoginPost,
	logoutApiV1AuthLogoutPost,
	type MeResponse,
	meApiV1AuthMeGet,
	postMessageApiV1ConversationsConversationIdMessagesPost,
	refreshApiV1AuthRefreshPost,
} from "@/client";
import { client } from "@/client/client.gen";
import type { Lang } from "@/lib/i18n";

const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";

function readCookie(name: string): string | null {
	const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
	return match ? decodeURIComponent(match[1]) : null;
}

// R1/D11: the session cookie carries `customer_id`; nothing here ever sends
// one. The only thing this interceptor adds is the CSRF double-submit
// header, and only on requests that can have a side effect.
client.interceptors.request.use((request) => {
	if (request.method !== "GET") {
		const token = readCookie(CSRF_COOKIE);
		if (token) {
			request.headers.set(CSRF_HEADER, token);
		}
	}
	return request;
});

/** Typed API error. `code` is the FastAPI `detail` string (`04` error shapes). */
export class ApiError extends Error {
	status: number;
	code: string;

	constructor(status: number, code: string) {
		super(code);
		this.status = status;
		this.code = code;
	}
}

function errorCode(error: unknown): string {
	if (
		error &&
		typeof error === "object" &&
		"detail" in error &&
		typeof (error as { detail: unknown }).detail === "string"
	) {
		return (error as { detail: string }).detail;
	}
	return "generic";
}

// `response` is optional on the generated result type: it is missing only
// when the request never made it to the network (D11 doesn't cover that
// case, so it is treated as a plain, non-retryable error below).
type FetchResult<T> = { data?: T; error?: unknown; response?: Response };

function statusOf(result: FetchResult<unknown>): number {
	return result.response?.status ?? 0;
}

function unwrap<T>(result: FetchResult<T>): T {
	if (result.error !== undefined || !result.response?.ok) {
		throw new ApiError(statusOf(result), errorCode(result.error));
	}
	return result.data as T;
}

// D11: a 401 on anything but login/refresh gets one refresh-and-retry. A
// second 401 means the session is gone, so the customer goes to `/login`.
// `login` and `refresh` never call this (they are the exempt paths).
async function withAuthRetry<T>(
	exec: () => Promise<FetchResult<T>>,
): Promise<FetchResult<T>> {
	const first = await exec();
	if (statusOf(first) !== 401) {
		return first;
	}
	const refresh = await refreshApiV1AuthRefreshPost();
	if (!refresh.response?.ok) {
		window.location.assign("/login");
		return first;
	}
	const second = await exec();
	if (statusOf(second) === 401) {
		window.location.assign("/login");
	}
	return second;
}

export async function login(body: LoginRequest): Promise<MeResponse> {
	const result = await loginApiV1AuthLoginPost({ body });
	return unwrap(result);
}

export async function logout(): Promise<void> {
	const result = await withAuthRetry(() => logoutApiV1AuthLogoutPost());
	unwrap(result);
}

// `null` on 401, with no redirect (T3/T4 use this for the shell/chat guard,
// which decide for themselves what "not logged in" means).
export async function me(): Promise<MeResponse | null> {
	const result = await meApiV1AuthMeGet();
	if (statusOf(result) === 401) {
		return null;
	}
	return unwrap(result);
}

export async function createConversation(lang: Lang): Promise<string> {
	const result = await withAuthRetry(() =>
		createConversationApiV1ConversationsPost({ body: { language: lang } }),
	);
	return unwrap(result).conversation_id;
}

export async function postMessage(
	conversationId: string,
	text: string,
): Promise<string> {
	const result = await withAuthRetry(() =>
		postMessageApiV1ConversationsConversationIdMessagesPost({
			path: { conversation_id: conversationId },
			body: { text },
		}),
	);
	return unwrap(result).turn_id;
}

// The next three wrap the D1 routes proposed in this card's spec (`04` §3).
// They are not in the generated SDK yet: A2/A4 land the real routes, and
// `make client` regenerates typed functions to replace these by hand.
type TurnAccepted = { turn_id: string };

export async function postResume(conversationId: string): Promise<string> {
	const result = await withAuthRetry(() =>
		client.post<{ 202: TurnAccepted }, unknown>({
			url: "/api/v1/conversations/{conversation_id}/messages",
			path: { conversation_id: conversationId },
			body: { resume: "step_up" },
		}),
	);
	return unwrap(result).turn_id;
}

export type ConfirmationDecision = "confirm" | "cancel";

export async function postConfirmation(
	conversationId: string,
	tokenId: string,
	decision: ConfirmationDecision,
): Promise<string> {
	const result = await withAuthRetry(() =>
		client.post<{ 202: TurnAccepted }, unknown>({
			url: "/api/v1/conversations/{conversation_id}/confirmations/{token_id}",
			path: { conversation_id: conversationId, token_id: tokenId },
			body: { decision },
		}),
	);
	return unwrap(result).turn_id;
}

export async function verifyOtp(code: string): Promise<void> {
	const result = await withAuthRetry(() =>
		client.post<{ 204: undefined }, unknown>({
			url: "/api/v1/auth/otp/verify",
			body: { code },
		}),
	);
	unwrap(result);
}

const CONVERSATION_STORAGE_KEY = "swip.conversation_id";

export const conversationStore = {
	get(): string | null {
		return window.sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
	},
	set(conversationId: string): void {
		window.sessionStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
	},
	clear(): void {
		window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
	},
};
