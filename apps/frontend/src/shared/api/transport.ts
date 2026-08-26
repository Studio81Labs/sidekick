import { apiUrl, readJson } from "./core";

export interface JsonRequestOptions extends RequestInit {
  signal?: AbortSignal;
}

/** Shared credentialed JSON transport for domain API adapters. */
export async function requestJson<T>(
  path: string,
  options: JsonRequestOptions = {},
): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: options.credentials ?? "include",
  });
  return readJson<T>(response);
}
