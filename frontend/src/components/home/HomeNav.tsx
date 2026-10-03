import { LanguageToggle } from "@/components/layout/LanguageToggle";
import { useLogout } from "@/components/layout/useLogout";
import { useI18n } from "@/lib/i18n";

import { NotificationsMenu } from "./NotificationsMenu";

// The home's own top bar ("Swip Panel" design); `AppShell` hides its header
// on `/home`, so the language toggle and logout live here instead.
export function HomeNav({
	name,
	onAsk,
}: {
	name: string | undefined;
	onAsk: (prompt: string) => void;
}) {
	const { t } = useI18n();
	const handleLogout = useLogout();
	return (
		<nav
			aria-label={t("home.nav.label")}
			className="sticky top-0 z-20 border-b border-border bg-bg/95 backdrop-blur-md"
		>
			<div className="mx-auto flex h-[68px] max-w-[1280px] items-center gap-10 px-10">
				<span className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight">
					<span aria-hidden="true" className="size-2.5 rounded-[3px] bg-cyan" />
					Swip
				</span>
				<div className="flex-1" />
				<div className="flex items-center gap-3">
					<LanguageToggle />
					<NotificationsMenu onAsk={onAsk} />
					{name && (
						<div className="flex items-center gap-2.5 rounded-full border border-border py-1 pr-3.5 pl-1">
							<span
								aria-hidden="true"
								className="grid size-[34px] place-items-center rounded-full bg-cyan font-heading text-[15px] text-bg"
							>
								{name.charAt(0).toUpperCase()}
							</span>
							<span className="text-[15px] font-semibold">{name}</span>
						</div>
					)}
					<button
						type="button"
						data-testid="logout"
						onClick={handleLogout}
						className="cursor-pointer px-1 py-2 text-sm font-semibold text-muted-foreground hover:text-foreground"
					>
						{t("shell.logout")}
					</button>
				</div>
			</div>
		</nav>
	);
}
