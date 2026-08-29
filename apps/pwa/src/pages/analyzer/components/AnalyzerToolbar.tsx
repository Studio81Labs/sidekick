import {
  CircleHelp,
  FlaskConical,
  Info,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

import "./AnalyzerToolbar.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import { SummaryMetric } from "../../../shared/components/SummaryMetric";

export interface AnalyzerToolbarProps {
  administrativeUnlocked: boolean;
  busy: boolean;
  historyTotal: number;
  onConfigurePipeline: () => void;
  onOpenAdministrativeTools: () => void;
  onOpenBenchmark: () => void;
  onOpenHelp: () => void;
  onOpenInfo: () => void;
  queueCount: number;
}

export function AnalyzerToolbar({
  administrativeUnlocked,
  busy,
  historyTotal,
  onConfigurePipeline,
  onOpenAdministrativeTools,
  onOpenBenchmark,
  onOpenHelp,
  onOpenInfo,
  queueCount,
}: AnalyzerToolbarProps) {
  return (
    <section className="toolbar" aria-label="Analyzer controls">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          A
        </div>
        <div>
          <h1>Poker Training Analyzer</h1>
          <p>
            Administrator OCR test console for Texas Hold&apos;em screenshots
          </p>
        </div>
      </div>
      <div className="toolbar-stats" aria-label="Session status">
        <SummaryMetric
          className="toolbar-stat"
          label="in queue"
          value={queueCount}
        />
        <i aria-hidden="true" />
        <SummaryMetric
          className="toolbar-stat"
          label="reviewed"
          value={historyTotal}
        />
        <i aria-hidden="true" />
        <ButtonControl
          variant="secondary"
          iconOnly
          className={
            administrativeUnlocked
              ? "header-icon-button active"
              : "header-icon-button"
          }
          onClick={onOpenAdministrativeTools}
          aria-pressed={administrativeUnlocked}
          title="Administrator tools"
          aria-label="Administrator tools"
        >
          <ShieldCheck size={18} aria-hidden="true" />
        </ButtonControl>
        <ButtonControl
          variant="secondary"
          iconOnly
          className="header-icon-button"
          onClick={onConfigurePipeline}
          disabled={busy}
          title="Analysis plugins"
          aria-label="Configure analysis plugins"
        >
          <SlidersHorizontal size={18} aria-hidden="true" />
        </ButtonControl>
        <ButtonControl
          variant="secondary"
          iconOnly
          className="header-icon-button"
          onClick={onOpenHelp}
          title="How to use"
          aria-label="How to use Poker Training Analyzer"
        >
          <CircleHelp size={18} aria-hidden="true" />
        </ButtonControl>
        <ButtonControl
          variant="secondary"
          iconOnly
          className="header-icon-button"
          onClick={onOpenInfo}
          title="About this app"
          aria-label="About this app"
        >
          <Info size={18} aria-hidden="true" />
        </ButtonControl>
        <ButtonControl
          variant="secondary"
          iconOnly
          className="header-icon-button"
          onClick={onOpenBenchmark}
          disabled={busy}
          title="Parser benchmark"
          aria-label="Parser benchmark"
        >
          <FlaskConical size={18} aria-hidden="true" />
        </ButtonControl>
      </div>
    </section>
  );
}
