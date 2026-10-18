/** Types the admin app shows, from the API's OpenAPI document (src/api/schema.gen.ts). */
import type { components } from "./schema.gen";

type S = components["schemas"];

/**
 * Pydantic writes every field in API responses, defaults included, but the JSON Schema marks
 * fields with defaults as optional. This makes them required again for the response types.
 */
type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

export type AuthState = S["AuthState"];
export type AuthUser = S["AuthUser"];
export type AuthProviders = S["AuthProviders"];
export type MagicLinkSent = S["MagicLinkSent"];

export type Turn = DeepRequired<S["Turn"]>;
export type Phase = S["Phase"];
export type InterviewType = S["InterviewType"];
export type Difficulty = S["Difficulty"];
export type Mode = S["Mode"];
export type SessionRecord = DeepRequired<S["SessionRecord"]>;
export type Usage = DeepRequired<S["UsageOut"]>;

/** GET /health. The API types it as a plain object, so the fields the admin app reads are here. */
export interface Health {
  status: "ok" | "degraded";
  version: string;
  model_profile: string;
  checks: Record<string, string>;
}
