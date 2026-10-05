import { type FormEvent, useEffect, useState } from "react";

import type { ProfileFormView } from "@/client";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	getProfileForm,
	postProfileFormCancel,
	postProfileFormSubmit,
} from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

type ProfileFormProps = {
	conversationId: string;
	cardKind: "credit" | "debit";
	/** A view the host already fetched (the mount probe), so the form does not GET twice. */
	initialView?: ProfileFormView;
	/** Send or Cancel went through: the host closes the form and waits for the turn. */
	onClosed: () => void;
};

type Field = "email" | "mobile_phone" | "address" | "occupation" | "income";
type Draft = Record<Field, string>;
type Errors = Partial<Record<Field, TKey>>;

// Mirrors `ProfileFormValues` in `api/v1/conversations.py`; the server stays
// the authority and answers 422 on anything that slips through.
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^\+?[0-9][0-9 ()-]{5,19}$/;
const INCOME = /^\d{1,12}([.,]\d{1,2})?$/;

// The bank stores income as an unconstrained numeric, so the view can carry
// trailing zeros ("32904211.530"). Dropping them keeps the same number but fits
// the two-decimal rule, so an untouched income is neither rejected nor sent as
// a changed value (`apply_profile_changes` compares as `Decimal`).
function normalizeIncome(raw: string): string {
	const text = raw.trim().replace(",", ".");
	return text.includes(".") ? text.replace(/\.?0+$/, "") : text;
}

// The service sends 0 for a NULL bank income; that is "no value", not an income
// the customer could keep (the server needs > 0), so the field starts empty.
function loadedIncome(raw: string | number | null | undefined): string {
	const income = normalizeIncome(String(raw ?? ""));
	return Number(income) > 0 ? income : "";
}

// A null bank value shows as an empty field, never as the text "null".
function orEmpty(value: string | null | undefined): string {
	return value ?? "";
}

function validate(draft: Draft, untouchedIncome: string): Errors {
	const errors: Errors = {};
	const email = draft.email.trim();
	if (!EMAIL.test(email) || email.length > 254) {
		errors.email = "profile_form.error.email";
	}
	if (!PHONE.test(draft.mobile_phone.trim())) {
		errors.mobile_phone = "profile_form.error.phone";
	}
	const address = draft.address.trim();
	if (address.length < 1 || address.length > 300) {
		errors.address = "profile_form.error.required";
	}
	const occupation = draft.occupation.trim();
	if (occupation.length < 1 || occupation.length > 120) {
		errors.occupation = "profile_form.error.required";
	}
	const income = draft.income.trim();
	// An empty loaded income (null in the bank) is never "untouched": it must be filled.
	if (income !== "" && income === untouchedIncome) {
		return errors;
	}
	if (!INCOME.test(income) || Number(income.replace(",", ".")) <= 0) {
		errors.income = "profile_form.error.income";
	}
	return errors;
}

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex flex-col gap-1">
			<Label>{label}</Label>
			<p className="text-sm text-muted-foreground">{value}</p>
		</div>
	);
}

/**
 * `ui.profile_form` (D9-C D11). The form view and everything typed live only in
 * this component's state: never the transcript, storage, a log line or a URL
 * (R5). Send posts `{action: "submit", values}`, Cancel (also the X and Esc)
 * posts `{action: "cancel"}`; the resumed turn's events arrive on the stream.
 */
export function ProfileForm({
	conversationId,
	cardKind,
	initialView,
	onClosed,
}: ProfileFormProps) {
	const { t } = useI18n();
	const [view, setView] = useState<ProfileFormView | null>(null);
	const [draft, setDraft] = useState<Draft | null>(null);
	// The income as loaded: while the field still holds it, it is never re-checked.
	const [untouchedIncome, setUntouchedIncome] = useState<string | null>(null);
	const [errors, setErrors] = useState<Errors>({});
	const [loadFailed, setLoadFailed] = useState(false);
	const [submitError, setSubmitError] = useState(false);
	const [busy, setBusy] = useState(false);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `initialView` is only read on mount.
	useEffect(() => {
		let live = true;
		const apply = (loaded: ProfileFormView) => {
			setView(loaded);
			setUntouchedIncome(
				loadedIncome(loaded.editable.estimated_monthly_income),
			);
			setDraft({
				email: orEmpty(loaded.editable.email),
				mobile_phone: orEmpty(loaded.editable.mobile_phone),
				address: orEmpty(loaded.editable.address),
				occupation: orEmpty(loaded.editable.occupation),
				income: loadedIncome(loaded.editable.estimated_monthly_income),
			});
		};
		if (initialView) {
			apply(initialView);
			return;
		}
		getProfileForm(conversationId)
			.then((loaded) => {
				if (live) apply(loaded);
			})
			.catch(() => {
				if (live) setLoadFailed(true);
			});
		return () => {
			live = false;
		};
	}, [conversationId]);

	async function handleCancel() {
		if (busy) return;
		setBusy(true);
		try {
			await postProfileFormCancel(conversationId);
			onClosed();
		} catch {
			setSubmitError(true);
			setBusy(false);
		}
	}

	async function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (!draft || busy) return;
		const found = validate(draft, untouchedIncome ?? "");
		setErrors(found);
		if (Object.keys(found).length > 0) return;
		setBusy(true);
		setSubmitError(false);
		try {
			await postProfileFormSubmit(conversationId, {
				email: draft.email.trim(),
				mobile_phone: draft.mobile_phone.trim(),
				address: draft.address.trim(),
				occupation: draft.occupation.trim(),
				estimated_monthly_income: normalizeIncome(draft.income),
			});
			onClosed();
		} catch {
			setSubmitError(true);
			setBusy(false);
		}
	}

	function textField(field: Field, label: TKey, type = "text") {
		if (!draft) return null;
		const error = errors[field];
		return (
			<div className="flex flex-col gap-1">
				<Label htmlFor={`profile-form-${field}`}>{t(label)}</Label>
				<Input
					id={`profile-form-${field}`}
					data-testid={`profile-form-${field}`}
					type={type}
					value={draft[field]}
					onChange={(event) =>
						setDraft({ ...draft, [field]: event.target.value })
					}
					// PII: keep the browser from caching what is typed.
					autoComplete="off"
					aria-invalid={!!error}
					disabled={busy}
				/>
				{error && <p className="text-sm text-alert">{t(error)}</p>}
			</div>
		);
	}

	return (
		<Dialog
			open
			onOpenChange={(open) => {
				if (!open) handleCancel();
			}}
		>
			<DialogContent
				data-testid="profile-form"
				className="max-h-dvh overflow-y-auto"
				onInteractOutside={(event) => event.preventDefault()}
			>
				<DialogHeader>
					<DialogTitle>
						{t(`profile_form.title.${view?.card_kind ?? cardKind}`)}
					</DialogTitle>
				</DialogHeader>
				{loadFailed && (
					<p role="alert" className="text-sm text-alert">
						{t("profile_form.error.load")}
					</p>
				)}
				{view && draft && (
					<form onSubmit={handleSubmit} className="flex flex-col gap-3">
						<ReadOnlyRow
							label={t("profile_form.field.full_name")}
							value={view.read_only.full_name}
						/>
						<ReadOnlyRow
							label={t("profile_form.field.document")}
							value={view.read_only.document_masked}
						/>
						<ReadOnlyRow
							label={t("profile_form.field.date_of_birth")}
							value={view.read_only.date_of_birth_display}
						/>
						{textField("email", "profile_form.field.email", "email")}
						{textField(
							"mobile_phone",
							"profile_form.field.mobile_phone",
							"tel",
						)}
						{textField("address", "profile_form.field.address")}
						{textField("occupation", "profile_form.field.occupation")}
						{textField("income", "profile_form.field.estimated_monthly_income")}
						<p className="text-sm text-muted-foreground">
							{t("profile_form.income_hint", {
								currency: view.income_currency,
							})}
						</p>
						{submitError && (
							<p role="alert" className="text-sm text-alert">
								{t("errors.generic")}
							</p>
						)}
						<div className="flex justify-end gap-2">
							<Button
								type="button"
								variant="outline"
								data-testid="profile-form-cancel"
								onClick={handleCancel}
								disabled={busy}
							>
								{t("profile_form.cancel")}
							</Button>
							<Button
								type="submit"
								data-testid="profile-form-submit"
								disabled={busy}
							>
								{t("profile_form.submit")}
							</Button>
						</div>
					</form>
				)}
				{loadFailed && (
					<div className="flex justify-end">
						<Button
							type="button"
							variant="outline"
							data-testid="profile-form-cancel"
							onClick={handleCancel}
							disabled={busy}
						>
							{t("profile_form.cancel")}
						</Button>
					</div>
				)}
			</DialogContent>
		</Dialog>
	);
}
