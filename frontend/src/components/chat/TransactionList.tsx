import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import type { TxOption } from "@/lib/sse";

type TransactionListProps = {
	options: TxOption[];
	/** Posts the picked `tx_id`s as a `TxSelection` (D4-B D7), never as text. */
	onSelect: (txIds: string[]) => void;
};

/**
 * `ui.transaction_list`: one native checkbox per offered transaction, each
 * label already merchant/money/date/mask-formatted server-side (R4, D13).
 * "Continuar" stays disabled until at least one is picked, and the whole
 * widget disables itself after use, like `CardPicker`.
 */
export function TransactionList({ options, onSelect }: TransactionListProps) {
	const { t } = useI18n();
	const [picked, setPicked] = useState<string[]>([]);
	const [used, setUsed] = useState(false);

	function toggle(txId: string) {
		setPicked((prev) =>
			prev.includes(txId) ? prev.filter((id) => id !== txId) : [...prev, txId],
		);
	}

	function handleContinue() {
		setUsed(true);
		onSelect(picked);
	}

	return (
		<div className="mt-2 flex flex-col gap-2">
			{options.map((option) => (
				<label key={option.tx_id} className="flex items-center gap-2 text-sm">
					<input
						type="checkbox"
						data-testid="transaction-option"
						disabled={used}
						checked={picked.includes(option.tx_id)}
						onChange={() => toggle(option.tx_id)}
					/>
					{option.label}
				</label>
			))}
			<Button
				type="button"
				size="sm"
				data-testid="transaction-list-continue"
				disabled={used || picked.length === 0}
				onClick={handleContinue}
			>
				{t("transactions.continue")}
			</Button>
		</div>
	);
}
