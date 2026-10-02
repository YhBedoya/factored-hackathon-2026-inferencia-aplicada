import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import type { MeResponse } from "@/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { ApiError, login } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

const DOCUMENT_TYPES = ["DNI", "CC", "CE", "Pasaporte"] as const;

// The only error codes `/auth/login` can answer with (D11/`04` §3 "Login and
// `/me`"). Anything else falls back to `errors.generic` -- never a raw code
// or the submitted document number reaches the screen.
const KNOWN_LOGIN_ERROR_CODES = new Set([
	"invalid_credentials",
	"too_many_attempts",
]);

function loginErrorMessage(
	t: ReturnType<typeof useI18n>["t"],
	code: string,
): string {
	if (KNOWN_LOGIN_ERROR_CODES.has(code)) {
		return t(`errors.${code}` as TKey);
	}
	return t("errors.generic");
}

function useLoginSchema() {
	const { t } = useI18n();
	return useMemo(
		() =>
			z.object({
				document_type: z.enum(DOCUMENT_TYPES),
				document_number: z.string().min(1, t("errors.required")),
				password: z.string().min(1, t("errors.required")),
			}),
		[t],
	);
}

type LoginFormValues = z.infer<ReturnType<typeof useLoginSchema>>;

export type LoginFormProps = {
	/** Called with the fresh session's `MeResponse` once `/auth/login` succeeds. */
	onSuccess: (me: MeResponse) => void;
};

/**
 * The document + password form (`04` §3 "Login"). `LoginDialog` renders it
 * as the landing's login pop-up; `SessionExpiredModal` (D8) renders the same form
 * inside a dialog, so each caller decides what "logged in" means for it --
 * navigate to `/chat`, or compare identities and replay a held request.
 */
export function LoginForm({ onSuccess }: LoginFormProps) {
	const { t } = useI18n();
	const schema = useLoginSchema();
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const {
		control,
		register,
		handleSubmit,
		formState: { errors },
	} = useForm<LoginFormValues>({
		resolver: zodResolver(schema),
		defaultValues: { document_type: "DNI", document_number: "", password: "" },
	});

	async function onSubmit(values: LoginFormValues) {
		setSubmitError(null);
		setSubmitting(true);
		try {
			const me = await login(values);
			onSuccess(me);
		} catch (error) {
			const code = error instanceof ApiError ? error.code : "generic";
			setSubmitError(loginErrorMessage(t, code));
		} finally {
			setSubmitting(false);
		}
	}

	return (
		<form
			className="flex flex-col gap-4"
			onSubmit={(event) => {
				void handleSubmit(onSubmit)(event);
			}}
		>
			<div className="flex flex-col gap-1.5">
				<Label htmlFor="document_type">{t("login.document_type")}</Label>
				<Controller
					control={control}
					name="document_type"
					render={({ field }) => (
						<Select value={field.value} onValueChange={field.onChange}>
							<SelectTrigger
								id="document_type"
								data-testid="login-document-type"
								className="w-full"
							>
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								{DOCUMENT_TYPES.map((documentType) => (
									<SelectItem key={documentType} value={documentType}>
										{t(`login.document_type_options.${documentType}` as TKey)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					)}
				/>
			</div>

			<div className="flex flex-col gap-1.5">
				<Label htmlFor="document_number">{t("login.number")}</Label>
				<Input
					id="document_number"
					data-testid="login-document-number"
					autoComplete="username"
					{...register("document_number")}
				/>
				{errors.document_number && (
					<p className="text-sm text-alert">{errors.document_number.message}</p>
				)}
			</div>

			<div className="flex flex-col gap-1.5">
				<Label htmlFor="password">{t("login.password")}</Label>
				<Input
					id="password"
					type="password"
					data-testid="login-password"
					autoComplete="current-password"
					{...register("password")}
				/>
				{errors.password && (
					<p className="text-sm text-alert">{errors.password.message}</p>
				)}
			</div>

			{submitError && (
				<p data-testid="login-error" role="alert" className="text-alert">
					{submitError}
				</p>
			)}

			<Button type="submit" data-testid="login-submit" disabled={submitting}>
				{t("login.submit")}
			</Button>
		</form>
	);
}
