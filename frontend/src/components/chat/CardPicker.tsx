import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
import type { PickerOption } from "@/lib/sse";

type CardPickerProps = {
	options: PickerOption[];
	/** Sends the clicked label as ordinary text, exactly as if typed (D5). */
	onSelect: (label: string) => void;
	/** Replacement-after-block mode: checkboxes plus submit/decline. */
	multi?: boolean;
	/** Posts the checked `card_id`s (empty on decline), never as text. */
	onCardSelect?: (cardIds: string[]) => void;
};

/**
 * `ui.card_picker`: one button per code-formatted option (R4, D3); with
 * `multi`, one checkbox per card and a submit/decline pair. Labels are built
 * server-side and never re-formatted here.
 */
export function CardPicker({
	options,
	onSelect,
	multi,
	onCardSelect,
}: CardPickerProps) {
	const { t } = useI18n();
	const [clicked, setClicked] = useState(false);
	const [picked, setPicked] = useState<string[]>([]);

	function handleClick(label: string) {
		setClicked(true);
		onSelect(label);
	}

	function toggle(cardId: string) {
		setPicked((prev) =>
			prev.includes(cardId)
				? prev.filter((id) => id !== cardId)
				: [...prev, cardId],
		);
	}

	function finish(cardIds: string[]) {
		setClicked(true);
		onCardSelect?.(cardIds);
	}

	if (multi) {
		return (
			<div className="mt-2 flex flex-col gap-2">
				{options.map((option) => (
					<label key={option.label} className="flex items-center gap-2 text-sm">
						<input
							type="checkbox"
							data-testid="card-picker-option"
							disabled={clicked}
							checked={
								option.card_id != null && picked.includes(option.card_id)
							}
							onChange={() => option.card_id && toggle(option.card_id)}
						/>
						{option.label}
					</label>
				))}
				<div className="flex gap-2">
					<Button
						type="button"
						size="sm"
						data-testid="card-picker-submit"
						disabled={clicked}
						onClick={() => finish(picked)}
					>
						{t("card_picker.submit")}
					</Button>
					<Button
						type="button"
						variant="outline"
						size="sm"
						data-testid="card-picker-decline"
						disabled={clicked}
						onClick={() => finish([])}
					>
						{t("card_picker.decline")}
					</Button>
				</div>
			</div>
		);
	}

	return (
		<div className="mt-2 flex flex-wrap gap-2">
			{options.map((option) => (
				<Button
					key={option.label}
					type="button"
					variant="outline"
					size="sm"
					data-testid="card-picker-option"
					disabled={clicked}
					onClick={() => handleClick(option.label)}
				>
					{option.label}
				</Button>
			))}
		</div>
	);
}
