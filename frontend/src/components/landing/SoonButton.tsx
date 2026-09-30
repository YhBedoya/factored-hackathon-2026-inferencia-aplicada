import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

// "Abre tu cuenta" / "Pide tu tarjeta" have no destination yet: they render
// as disabled buttons with a visible "Próximamente" badge, never as links.
export function SoonButton({
	label,
	large = false,
}: {
	label: string;
	large?: boolean;
}) {
	const { t } = useI18n();
	return (
		<Button
			type="button"
			disabled
			aria-disabled="true"
			className={
				large
					? "h-12 rounded-full px-7 text-base font-semibold"
					: "h-10 rounded-full px-4 text-sm font-semibold"
			}
		>
			{label}
			<span className="rounded-full bg-background/20 px-2 py-0.5 text-xs">
				{t("landing.soon")}
			</span>
		</Button>
	);
}
