export interface AutomationSettings {
  enabled: boolean;
  autoApprove: boolean;
  autoRecommend: boolean;
  allowWarnings: boolean;
}

export const DEFAULT_AUTOMATION_SETTINGS: AutomationSettings = {
  enabled: true,
  autoApprove: true,
  autoRecommend: true,
  allowWarnings: false,
};

export const AUTOMATION_SETTINGS_STORAGE_KEY = "poker-training-automation-v1";

export function readAutomationSettings(): AutomationSettings {
  if (typeof window === "undefined") {
    return DEFAULT_AUTOMATION_SETTINGS;
  }
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(AUTOMATION_SETTINGS_STORAGE_KEY) ?? "null",
    ) as Partial<AutomationSettings> | null;
    if (
      parsed === null ||
      typeof parsed !== "object" ||
      typeof parsed.enabled !== "boolean" ||
      typeof parsed.autoApprove !== "boolean" ||
      typeof parsed.autoRecommend !== "boolean" ||
      typeof parsed.allowWarnings !== "boolean"
    ) {
      return DEFAULT_AUTOMATION_SETTINGS;
    }
    return {
      enabled: parsed.enabled,
      autoApprove: parsed.autoApprove,
      autoRecommend: parsed.autoApprove && parsed.autoRecommend,
      allowWarnings: parsed.allowWarnings,
    };
  } catch {
    return DEFAULT_AUTOMATION_SETTINGS;
  }
}

export function writeAutomationSettings(settings: AutomationSettings): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      AUTOMATION_SETTINGS_STORAGE_KEY,
      JSON.stringify(settings),
    );
  } catch {
    // Browser storage is optional; the current session keeps the chosen settings.
  }
}
