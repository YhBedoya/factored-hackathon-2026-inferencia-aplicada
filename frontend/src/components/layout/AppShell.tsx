import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { conversationStore, logout, me } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { LanguageToggle } from "./LanguageToggle";
import { StarryBackground } from "./StarryBackground";

// Shared with `login.tsx`'s post-login `invalidateQueries` call, so the
// shell picks up the new session without a reload.
export const ME_QUERY_KEY = ["me"] as const;

// The one place every route renders through (`__root.tsx`). It owns the
// chrome that's the same everywhere: the starfield, the wordmark, the
// language toggle and, once `me()` resolves a customer, the greeting and
// logout. Route content (landing, login, chat) is `children`.
export function AppShell({ children }: { children: ReactNode }) {
	const { t } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { data: customer } = useQuery({
		queryKey: ME_QUERY_KEY,
		queryFn: me,
		retry: false,
	});

	async function handleLogout() {
		await logout();
		conversationStore.clear();
		queryClient.setQueryData(ME_QUERY_KEY, null);
		await navigate({ to: "/login" });
	}

	return (
		<div className="relative min-h-svh">
			<StarryBackground />
			<div className="relative z-10 flex min-h-svh flex-col">
				<header className="flex items-center justify-between gap-4 px-6 py-4">
					<span className="font-heading text-lg text-cyan">
						{t("landing.title")}
					</span>
					<div className="flex items-center gap-3">
						<LanguageToggle />
						{customer && (
							<>
								<span className="text-sm text-muted-foreground">
									{t("shell.greeting", { name: customer.display_name })}
								</span>
								<Button
									type="button"
									variant="outline"
									size="sm"
									data-testid="logout"
									onClick={handleLogout}
								>
									{t("shell.logout")}
								</Button>
							</>
						)}
					</div>
				</header>
				<main className="flex flex-1 flex-col">{children}</main>
			</div>
		</div>
	);
}
