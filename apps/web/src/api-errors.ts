export interface ApiValidationField {
  path: string;
  code: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code?: string,
    readonly fields: ApiValidationField[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Translate = (key: string, vars?: Record<string, string | number>) => string;

function validationFields(value: unknown): ApiValidationField[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const field = item as Record<string, unknown>;
    return typeof field.path === "string" && typeof field.code === "string" && typeof field.message === "string"
      ? [{ path: field.path, code: field.code, message: field.message }]
      : [];
  });
}

function legacyDetailMessage(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const message = (item as Record<string, unknown>).msg;
      return typeof message === "string" ? [message] : [];
    }).join("\n");
  }
  if (!value || typeof value !== "object") return "";
  const detail = value as { message?: unknown; blocking_reasons?: unknown; blockers?: unknown; code?: unknown };
  const reasons = Array.isArray(detail.blocking_reasons)
    ? detail.blocking_reasons.filter((item): item is string => typeof item === "string")
    : [];
  if (Array.isArray(detail.blockers)) {
    reasons.push(...detail.blockers.map((item) => {
      if (item && typeof item === "object" && "message" in item && typeof item.message === "string") return item.message;
      return typeof item === "string" ? item : "";
    }).filter(Boolean));
  }
  return [typeof detail.message === "string" ? detail.message : "", ...reasons].filter(Boolean).join("\n");
}

export async function responseError(response: Response): Promise<ApiError> {
  const fallback = response.statusText || "Request failed";
  try {
    const body = await response.json() as Record<string, unknown>;
    if (body.error && typeof body.error === "object") {
      const error = body.error as Record<string, unknown>;
      return new ApiError(
        typeof error.message === "string" && error.message ? error.message : fallback,
        typeof error.code === "string" ? error.code : undefined,
        validationFields(error.fields),
      );
    }
    const detail = legacyDetailMessage(body.detail);
    const detailCode = body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)
      ? (body.detail as Record<string, unknown>).code
      : undefined;
    return new ApiError(detail || fallback, typeof detailCode === "string" ? detailCode : undefined);
  } catch {
    return new ApiError(fallback);
  }
}

export function localizedApiError(error: unknown, t: Translate, fallback: string): string {
  if (!(error instanceof ApiError)) {
    if (error instanceof Error && error.message.toLowerCase().includes("failed to fetch")) return t("error.fetch");
    return error instanceof Error && /[^\x00-\x7F]/.test(error.message) ? error.message : fallback;
  }
  if (error.code === "request_validation_failed") {
    const details = [...new Set(error.fields.map((field) => {
      const key = `error.validation.${field.code}`;
      const translated = t(key);
      return translated === key ? "" : translated;
    }).filter(Boolean))];
    return [t("error.requestValidation"), ...details].join(" ");
  }
  if (error.code) {
    const key = `error.api.${error.code}`;
    const translated = t(key);
    if (translated !== key) return translated;
  }
  return /[^\x00-\x7F]/.test(error.message) ? error.message : fallback;
}
