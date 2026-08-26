const API_BASE_URL =
  typeof import.meta.env.VITE_API_BASE_URL === "string" &&
  import.meta.env.VITE_API_BASE_URL.length > 0
    ? import.meta.env.VITE_API_BASE_URL
    : import.meta.env.DEV
      ? "http://localhost:8000"
      : "";

export class ApiResponseError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;
  readonly requestId: string | null;

  constructor(
    message: string,
    status: number,
    retryAfterSeconds: number | null = null,
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiResponseError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
    this.requestId = requestId;
  }
}

const FIELD_LABELS: Record<string, string> = {
  action_context: "Action context",
  board_cards: "Board cards",
  current_bet: "Current bet",
  effective_stack: "Effective stack",
  facing_action: "Facing action",
  hero_cards: "Hero cards",
  hero_position: "Hero position",
  hero_stack: "Hero stack",
  opponent_commitment_total: "Total opponent commitments",
  opponent_position: "Opponent position",
  opponent_stack: "Opponent stack",
  opponent_wager: "Opponent wager total",
  opponents_at_current_bet: "Opponents at the current wager",
  players_in_hand: "Players in hand",
  postflop_action_history: "Current-street action history",
  pot_size: "Pot",
  preflop_action_history: "Preflop action history",
  preflop_open_size: "Opening size",
  preflop_opener_position: "Opening position",
  street: "Street",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fieldLabel(value: string): string {
  const normalized = value.trim();
  if (FIELD_LABELS[normalized]) {
    return FIELD_LABELS[normalized];
  }
  const words = normalized.replace(/[_-]/g, " ").trim();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : "Field";
}

function joinReadable(items: string[]): string {
  if (items.length < 2) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

function validationIssueMessage(value: Record<string, unknown>): string | null {
  if (typeof value.msg !== "string" || !value.msg.trim()) {
    return null;
  }
  const location = Array.isArray(value.loc)
    ? value.loc.filter(
        (part): part is string =>
          typeof part === "string" && !["body", "path", "query"].includes(part),
      )
    : [];
  const label =
    location.length > 0 ? fieldLabel(location[location.length - 1] ?? "") : "";
  const message = value.msg.trim();
  if (label && message.toLowerCase() === "field required") {
    return `${label} is required`;
  }
  return label ? `${label}: ${message}` : message;
}

function structuredMessage(value: unknown, depth = 0): string | null {
  if (depth > 5 || value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string") {
    const message = value.trim();
    if (!message) return null;
    const structuredStart = [message.indexOf("{"), message.indexOf("[")]
      .filter((index) => index >= 0)
      .sort((left, right) => left - right)[0];
    if (structuredStart !== undefined) {
      const structuredValue = message.slice(structuredStart);
      try {
        const decoded = structuredMessage(
          JSON.parse(structuredValue),
          depth + 1,
        );
        if (decoded) {
          const prefix = message
            .slice(0, structuredStart)
            .replace(/[:\s]+$/, "");
          return prefix ? `${prefix}: ${decoded}` : decoded;
        }
      } catch {
        return message;
      }
    }
    return message;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const validationMessages = value.flatMap((item) => {
      const message = isRecord(item) ? validationIssueMessage(item) : null;
      return message ? [message] : [];
    });
    if (
      validationMessages.length === value.length &&
      validationMessages.length > 0
    ) {
      return validationMessages.join(". ");
    }
    const messages = value.flatMap((item) => {
      const message = structuredMessage(item, depth + 1);
      return message ? [message] : [];
    });
    return messages.length > 0 ? joinReadable(messages) : null;
  }
  if (!isRecord(value)) {
    return null;
  }

  if (Array.isArray(value.missing_fields)) {
    const fields = [
      ...new Set(
        value.missing_fields.flatMap((field) =>
          typeof field === "string" && field.trim() ? [fieldLabel(field)] : [],
        ),
      ),
    ];
    if (fields.length > 0) {
      const readableFields = fields.map((field, index) =>
        index === 0 ? field : `${field[0].toLowerCase()}${field.slice(1)}`,
      );
      return `Complete the required table details before requesting a recommendation: ${joinReadable(readableFields)}. Edit the listed fields, then approve the state again.`;
    }
  }
  for (const key of ["detail", "message", "error", "title"]) {
    if (key in value) {
      const message = structuredMessage(value[key], depth + 1);
      if (message) return message;
    }
  }
  const validationMessage = validationIssueMessage(value);
  if (validationMessage) return validationMessage;

  const entries = Object.entries(value).flatMap(([key, item]) => {
    const message = structuredMessage(item, depth + 1);
    return message ? [`${fieldLabel(key)}: ${message}`] : [];
  });
  return entries.length > 0 ? entries.join(". ") : null;
}

export function humanReadableMessage(value: unknown, fallback: string): string {
  return structuredMessage(value) ?? fallback;
}

const MAX_PLAIN_TEXT_ERROR_LENGTH = 512;

function readablePlainTextError(
  response: Response,
  body: string,
): string | null {
  const message = body.trim();
  const contentType = response.headers.get("Content-Type")?.toLowerCase() ?? "";
  if (
    !message ||
    message.length > MAX_PLAIN_TEXT_ERROR_LENGTH ||
    contentType.includes("text/html") ||
    message.startsWith("<") ||
    /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(message) ||
    /<(?:!doctype|html|head|body|title|h[1-6]|div|p)\b/i.test(message)
  ) {
    return null;
  }
  if (contentType && !contentType.startsWith("text/plain")) {
    return null;
  }
  return message;
}

function retryAfterSeconds(response: Response): number | null {
  const value = response.headers.get("Retry-After")?.trim();
  if (!value) {
    return null;
  }
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.ceil(seconds);
  }
  const retryAt = Date.parse(value);
  if (Number.isNaN(retryAt)) {
    return null;
  }
  return Math.max(0, Math.ceil((retryAt - Date.now()) / 1_000));
}

function withRetryGuidance(message: string, retryAfter: number | null): string {
  if (retryAfter === null) {
    return message;
  }
  const unit = retryAfter === 1 ? "second" : "seconds";
  return `${message} Try again in ${retryAfter} ${unit}.`;
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const fallback =
      response.statusText.trim() || `Request failed (HTTP ${response.status})`;
    let detail = fallback;
    try {
      const body = await response.text();
      let payload: unknown = null;
      if (body.trim()) {
        try {
          payload = JSON.parse(body);
        } catch {
          payload = readablePlainTextError(response, body);
        }
      }
      detail = humanReadableMessage(payload, fallback);
    } catch {
      detail = fallback;
    }
    const retryAfter = retryAfterSeconds(response);
    throw new ApiResponseError(
      withRetryGuidance(detail, retryAfter),
      response.status,
      retryAfter,
      response.headers.get("X-Request-ID"),
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}
