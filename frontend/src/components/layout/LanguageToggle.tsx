import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

// D10: the toggle only ever changes the UI chrome. The current value is read
// by whoever calls `createConversation` (T4); it never touches a running
// conversation's language on its own.
export function LanguageToggle() {
	const { lang, setLang, t } = useI18n();

	return (
		<div
			data-testid="lang-toggle"
			className="flex items-center gap-0.5 rounded-lg border border-input p-0.5"
		>
			<Button
				type="button"
				variant={lang === "es" ? "default" : "ghost"}
				size="xs"
				aria-pressed={lang === "es"}
				data-testid="lang-es"
				onClick={() => setLang("es")}
			>
				{t("lang.es")}
			</Button>
			<Button
				type="button"
				variant={lang === "pt" ? "default" : "ghost"}
				size="xs"
				aria-pressed={lang === "pt"}
				data-testid="lang-pt"
				onClick={() => setLang("pt")}
			>
				{t("lang.pt")}
			</Button>
		</div>
	);
}
