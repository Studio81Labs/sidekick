export interface PipelineOption {
  id: string;
  label: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface PipelineSelection {
  parser_provider: string;
  parser_layout_profile: string;
}

export interface PipelineCapabilities {
  administrative_ocr_test: { enabled: boolean };
  defaults: PipelineSelection;
  parser_providers: PipelineOption[];
  parser_layout_profiles: PipelineOption[];
  parser_layout_compatibility?: Record<string, string[]>;
}
