import { useEffect, useState } from "react";

import {
  type AutomationSettings,
  readAutomationSettings,
  writeAutomationSettings,
} from "../lib/automationSettings";

export function useAutomationSettings() {
  const [settings, setSettings] = useState(readAutomationSettings);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    writeAutomationSettings(settings);
  }, [settings]);

  function update(
    updater: (current: AutomationSettings) => AutomationSettings,
  ) {
    setSettings(updater);
  }

  function updateAutoApprove(value: boolean) {
    update((current) => ({
      ...current,
      autoApprove: value,
      autoRecommend: value && current.autoRecommend,
    }));
  }

  return {
    dialogOpen,
    setDialogOpen,
    settings,
    update,
    updateAutoApprove,
  };
}
