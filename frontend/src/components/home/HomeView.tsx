import { useState } from "react";

import { useI18n } from "@/lib/i18n";

import { AlertsSection } from "./AlertsSection";
import { BalanceSection } from "./BalanceSection";
import { CardsSection } from "./CardsSection";
import { CardyPanel } from "./CardyPanel";
import { TransactionsSection } from "./TransactionsSection";

export function HomeView() {
	const { t } = useI18n();
	const [open, setOpen] = useState(false);
	const [prefill, setPrefill] = useState<string | undefined>();

	function ask(prompt: string) {
		setPrefill(prompt);
		setOpen(true);
	}

	return (
		<div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 pb-24">
			<h1 className="font-heading text-2xl text-foreground">
				{t("home.title")}
			</h1>
			<AlertsSection onAsk={ask} />
			<CardsSection />
			<BalanceSection />
			<TransactionsSection />
			<CardyPanel
				open={open}
				prefill={prefill}
				onOpen={() => setOpen(true)}
				onClose={() => setOpen(false)}
			/>
		</div>
	);
}
