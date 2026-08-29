import { ShieldAlert } from "lucide-react";

import "./AdministrativeTestBanner.css";
import { ButtonControl } from "../../../shared/components/FormControls";

export interface AdministrativeTestBannerProps {
  busy: boolean;
  onLock: () => void;
}

export function AdministrativeTestBanner({
  busy,
  onLock,
}: AdministrativeTestBannerProps) {
  return (
    <aside
      className="administrative-test-banner"
      role="note"
      aria-label="Administrative OCR test mode"
    >
      <ShieldAlert size={16} aria-hidden="true" />
      <div className="administrative-test-banner-copy">
        <strong>Administrative OCR test</strong>
        <p>
          Parser diagnostics only. Uploads and captures are marked as
          administrative test inputs; they never request recommendations or
          enter training.
        </p>
      </div>
      <ButtonControl
        variant="secondary"
        onClick={onLock}
        disabled={busy}
        aria-label="Lock administrator tools"
      >
        Lock
      </ButtonControl>
    </aside>
  );
}
