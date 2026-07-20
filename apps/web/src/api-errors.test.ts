import { ApiError, localizedApiError, responseError } from "./api-errors";

function equal(actual: unknown, expected: unknown): void {
  if (actual !== expected) throw new Error(`Expected ${String(expected)}, got ${String(actual)}`);
}

const messages: Record<string, string> = {
  "error.fetch": "无法连接后端服务。",
  "error.requestValidation": "提交的信息格式不正确，请检查标记的字段。",
  "error.validation.string_too_long": "有一项内容过长。",
};
const t = (key: string) => messages[key] ?? key;

async function run(): Promise<void> {
  const next = await responseError(new Response(JSON.stringify({
    error: {
      code: "request_validation_failed",
      message: "The request contains invalid fields.",
      fields: [{ path: "api_key", code: "string_too_long", message: "The value is too long." }],
    },
  }), { status: 422, statusText: "Unprocessable Entity" }));
  equal(next instanceof ApiError, true);
  equal(next.message, "The request contains invalid fields.");
  equal(next.code, "request_validation_failed");
  equal(next.fields[0]?.path, "api_key");
  equal(localizedApiError(next, t, "操作失败"), "提交的信息格式不正确，请检查标记的字段。 有一项内容过长。");

  const legacyString = await responseError(new Response(JSON.stringify({ detail: "legacy message" }), { status: 400 }));
  equal(legacyString.message, "legacy message");

  const marker = "SENSITIVE_INPUT_MARKER";
  const legacyArray = await responseError(new Response(JSON.stringify({
    detail: [{ loc: ["body", "api_key"], msg: "invalid value", input: marker }],
  }), { status: 422 }));
  equal(legacyArray.message, "invalid value");
  equal(legacyArray.message.includes(marker), false);

  const hostileEnvelope = await responseError(new Response(JSON.stringify({
    error: {
      code: "request_validation_failed",
      message: marker,
      fields: [{ path: "api_key", code: "string_too_long", message: marker }],
    },
  }), { status: 422 }));
  equal(localizedApiError(hostileEnvelope, t, "操作失败").includes(marker), false);

  const nonJson = await responseError(new Response("not-json", { status: 500, statusText: "Server Error" }));
  equal(nonJson.message, "Server Error");
  const empty = await responseError(new Response(null, { status: 500, statusText: "Server Error" }));
  equal(empty.message, "Server Error");
}

void run();
