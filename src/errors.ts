/**
 * Custom error classes for typed error handling across the codebase.
 */

/** Raised when cass.toml is missing, invalid, or has missing required fields. */
export class ConfigError extends Error {
  readonly code = "CONFIG_ERROR" as const;
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/** Raised when an external API (Canvas, GitHub) returns an error or times out. */
export class ApiError extends Error {
  readonly code = "API_ERROR" as const;
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Raised when a referenced resource (assignment, module, quiz, student) cannot be found. */
export class NotFoundError extends Error {
  readonly code = "NOT_FOUND" as const;
  constructor(
    public readonly resource: string,
    public readonly identifier: string,
  ) {
    super(`${resource} not found: ${identifier}`);
    this.name = "NotFoundError";
  }
}
