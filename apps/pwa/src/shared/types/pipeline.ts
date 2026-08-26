export interface PipelineOption {
  id: string;
  label: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface PipelineSelection {
  parser_provider: string;
  parser_layout_profile: string;
  recommendation_provider: string;
  recommendation_engine: string | null;
}

export interface PipelineCapabilities {
  defaults: PipelineSelection;
  parser_providers: PipelineOption[];
  parser_layout_profiles: PipelineOption[];
  parser_layout_compatibility?: Record<string, string[]>;
  recommendation_providers: PipelineOption[];
  recommendation_engines: PipelineOption[];
}
