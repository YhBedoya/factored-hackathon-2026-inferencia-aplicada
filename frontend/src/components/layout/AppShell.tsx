import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { DriftStarfield } from "@/components/home/DriftStarfield";
import { Button } from "@/components/ui/button";
import { me } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { LanguageToggle } from "./LanguageToggle";
import { StarryBackground } from "./StarryBackground";
import { ME_QUERY_KEY, useLogout } from "./useLogout";

// The one place every route renders through (`__root.tsx`). It owns the
// chrome that's the same everywhere: the starfield, the language toggle
// and, once `me()` resolves a customer, the greeting and logout. The header
// is skipped on the landing and the banking home, which render their own
// controls; the home also swaps the static starfield for the slow drifting
// one. Route content (landing, login, chat, home) is `children`.
export function AppShell({ children }: { children: ReactNode }) {
	const { t } = useI18n();
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const isLanding = pathname === "/";
	const isHome = pathname === "/home";
	const { data: customer } = useQuery({
		queryKey: ME_QUERY_KEY,
		queryFn: me,
		retry: false,
	});
	const handleLogout = useLogout();

	return (
		<div className="relative min-h-svh">
			{isHome ? <DriftStarfield /> : <StarryBackground />}
			<div className="relative z-10 flex min-h-svh flex-col">
				{!isLanding && !isHome && (
					<header className="flex items-center justify-end gap-4 px-6 py-4">
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
				)}
				<main className="flex flex-1 flex-col">{children}</main>
			</div>
		</div>
	);
}
