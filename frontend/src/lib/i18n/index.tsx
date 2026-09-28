import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useMemo,
	useState,
} from "react";

import es from "./es.json";
import pt from "./pt.json";

export type Lang = "es" | "pt";
export type TKey = keyof typeof es;

const DICTIONARIES: Record<Lang, Record<TKey, string>> = { es, pt };

const STORAGE_KEY = "swip.lang";

// Cardy replies in the customer's language (brand.md "Language rules" #7).
// The UI chrome defaults the same way, from the browser locale, but the
// customer can override it with the ES | PT toggle, persisted here.
function detectLang(): Lang {
	const stored = window.localStorage.getItem(STORAGE_KEY);
	if (stored === "es" || stored === "pt") {
		return stored;
	}
	return navigator.language.toLowerCase().startsWith("pt") ? "pt" : "es";
}

function interpolate(template: string, vars?: Record<string, string>): string {
	if (!vars) {
		return template;
	}
	return template.replace(
		/\{(\w+)\}/g,
		(match, name: string) => vars[name] ?? match,
	);
}

type I18nContextValue = {
	lang: Lang;
	setLang: (lang: Lang) => void;
	t: (key: TKey, vars?: Record<string, string>) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
	const [lang, setLangState] = useState<Lang>(detectLang);

	const setLang = useCallback((next: Lang) => {
		window.localStorage.setItem(STORAGE_KEY, next);
		setLangState(next);
	}, []);

	const t = useCallback(
		(key: TKey, vars?: Record<string, string>) =>
			interpolate(DICTIONARIES[lang][key], vars),
		[lang],
	);

	const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);

	return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
	const ctx = useContext(I18nContext);
	if (!ctx) {
		throw new Error("useI18n must be used within an I18nProvider");
	}
	return ctx;
}
