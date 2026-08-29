import "./ImportFirstNotice.css";
import "./InputSourcePanel.css";

export function ImportFirstNotice() {
  return (
    <section className="input-panel import-first-notice" aria-label="Input">
      <div className="input-panel-heading">
        <h2>Input</h2>
      </div>
      <p>
        Screenshot upload and live capture are administrator-only parser test
        tools and are not part of the player workflow. Player analysis is based
        on imported hand histories.
      </p>
    </section>
  );
}
