import { zodResolver } from "@hookform/resolvers/zod";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, staffLogin } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/staff/login")({
	component: StaffLoginPage,
});

// The only error codes `POST /auth/staff/login` can answer with (D3, `04`
// §3), same mapping `login.tsx` uses for the customer route. Anything else
// falls back to `errors.generic` -- never a raw code or a submitted
// credential reaches the screen.
const KNOWN_STAFF_LOGIN_ERROR_CODES = new Set([
	"invalid_credentials",
	"too_many_attempts",
]);

function staffLoginErrorMessage(
	t: ReturnType<typeof useI18n>["t"],
	code: string,
): string {
	if (KNOWN_STAFF_LOGIN_ERROR_CODES.has(code)) {
		return t(`errors.${code}` as TKey);
	}
	return t("errors.generic");
}

function useStaffLoginSchema() {
	const { t } = useI18n();
	return useMemo(
		() =>
			z.object({
				username: z.string().min(1, t("errors.required")),
				password: z.string().min(1, t("errors.required")),
			}),
		[t],
	);
}

type StaffLoginFormValues = z.infer<ReturnType<typeof useStaffLoginSchema>>;

function StaffLoginPage() {
	const { t } = useI18n();
	const navigate = useNavigate();
	const schema = useStaffLoginSchema();
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const {
		register,
		handleSubmit,
		formState: { errors },
	} = useForm<StaffLoginFormValues>({
		resolver: zodResolver(schema),
		defaultValues: { username: "", password: "" },
	});

	async function onSubmit(values: StaffLoginFormValues) {
		setSubmitError(null);
		setSubmitting(true);
		try {
			await staffLogin(values);
			await navigate({ to: "/staff" });
		} catch (error) {
			const code = error instanceof ApiError ? error.code : "generic";
			setSubmitError(staffLoginErrorMessage(t, code));
		} finally {
			setSubmitting(false);
		}
	}

	return (
		<div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 py-16">
			<Card>
				<CardHeader>
					<CardTitle>{t("staff.login.title")}</CardTitle>
				</CardHeader>
				<CardContent>
					<form
						className="flex flex-col gap-4"
						onSubmit={(event) => {
							void handleSubmit(onSubmit)(event);
						}}
					>
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="username">{t("staff.login.username")}</Label>
							<Input
								id="username"
								data-testid="staff-login-username"
								autoComplete="username"
								{...register("username")}
							/>
							{errors.username && (
								<p className="text-sm text-alert">{errors.username.message}</p>
							)}
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="password">{t("staff.login.password")}</Label>
							<Input
								id="password"
								type="password"
								data-testid="staff-login-password"
								autoComplete="current-password"
								{...register("password")}
							/>
							{errors.password && (
								<p className="text-sm text-alert">{errors.password.message}</p>
							)}
						</div>

						{submitError && (
							<p
								data-testid="staff-login-error"
								role="alert"
								className="text-alert"
							>
								{submitError}
							</p>
						)}

						<Button
							type="submit"
							data-testid="staff-login-submit"
							disabled={submitting}
						>
							{t("staff.login.submit")}
						</Button>
					</form>
				</CardContent>
			</Card>
		</div>
	);
}
