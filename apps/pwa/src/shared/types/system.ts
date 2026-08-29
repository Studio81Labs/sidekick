export interface SystemInfo {
  status: string;
  environment?: "local" | "staging" | "production";
  parser_provider: string;
}
