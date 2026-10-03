import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { conversationStore, logout } from "@/lib/api";

// Shared with `login.tsx`'s post-login `invalidateQueries` call, so the
// shell picks up the new session without a reload.
export const ME_QUERY_KEY = ["me"] as const;

// One logout for every place that offers it (`AppShell`'s header and the
// banking home's own nav): end the session, forget the chat, and land on `/`.
export function useLogout() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	return async () => {
		await logout();
		conversationStore.clear();
		queryClient.setQueryData(ME_QUERY_KEY, null);
		await navigate({ to: "/" });
	};
}
