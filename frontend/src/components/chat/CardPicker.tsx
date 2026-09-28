import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { PickerOption } from "@/lib/sse";

type CardPickerProps = {
	options: PickerOption[];
	/** Sends the clicked label as ordinary text, exactly as if typed (D5). */
	onSelect: (label: string) => void;
};

/** `ui.card_picker`: one button per code-formatted option (R4, D3). */
export function CardPicker({ options, onSelect }: CardPickerProps) {
	const [clicked, setClicked] = useState(false);

	function handleClick(label: string) {
		setClicked(true);
		onSelect(label);
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
