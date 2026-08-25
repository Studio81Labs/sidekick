import { ChevronDown, RefreshCcw, Search, X } from "lucide-react";

import "./HistoryPanel.css";
import {
  cardToCode,
  cardToDisplay,
  isRedSuit,
} from "../../../shared/lib/cardPresentation";
import {
  ButtonControl,
  TextInput,
} from "../../../shared/components/FormControls";
import {
  historyAction,
  historyCards,
  type HistoryItem,
  relativeTimeLabel,
} from "../lib/historyPresentation";
import { screenshotLabel } from "../../screenshots/lib/screenshotPresentation";
import { ScreenshotRailItem } from "../../queue/components/ScreenshotRailItem";
import { StateMessage } from "../../../shared/components/StateMessage";
import { StatusBadge } from "../../../shared/components/StatusBadge";
import type { JobRecord } from "../../../shared/types/jobs";

export interface HistoryPanelProps {
  busy: boolean;
  items: readonly HistoryItem[];
  loading: boolean;
  onClearSearch: () => void;
  onLoadOlder: () => void;
  onManageJob: (job: JobRecord) => void;
  onOpenItem: (item: HistoryItem) => void;
  onOpenSearch: () => void;
  onRefresh: () => void;
  onSearch: () => void;
  onSearchInputChange: (value: string) => void;
  searchActive: boolean;
  searchInput: string;
  searchOpen: boolean;
  searchTotal: number;
  total: number;
}

export function HistoryPanel({
  busy,
  items,
  loading,
  onClearSearch,
  onLoadOlder,
  onManageJob,
  onOpenItem,
  onOpenSearch,
  onRefresh,
  onSearch,
  onSearchInputChange,
  searchActive,
  searchInput,
  searchOpen,
  searchTotal,
  total,
}: HistoryPanelProps) {
  const controlsDisabled = loading || busy;
  const remaining = Math.max(0, total - items.length);

  return (
    <section className="history-panel" aria-label="Session history">
      <div className="rail-section-heading history-heading">
        <span>
          {searchActive
            ? `History \u00b7 ${searchTotal} ${searchTotal === 1 ? "match" : "matches"}`
            : "History \u00b7 reopen"}
        </span>
        <span className="history-heading-actions">
          <StatusBadge density="compact">Auto-saved</StatusBadge>
          <ButtonControl
            variant="secondary"
            iconOnly
            className={
              searchOpen
                ? "history-search-toggle active"
                : "history-search-toggle"
            }
            onClick={searchOpen ? onClearSearch : onOpenSearch}
            disabled={controlsDisabled}
            title={searchOpen ? "Close history search" : "Search saved history"}
            aria-label={
              searchOpen ? "Close history search" : "Search saved history"
            }
          >
            {searchOpen ? (
              <X size={12} aria-hidden="true" />
            ) : (
              <Search size={12} aria-hidden="true" />
            )}
          </ButtonControl>
          <ButtonControl
            variant="secondary"
            iconOnly
            className="history-refresh"
            onClick={onRefresh}
            disabled={controlsDisabled}
            title={
              searchActive ? "Refresh history search" : "Refresh saved history"
            }
            aria-label={
              searchActive ? "Refresh history search" : "Refresh saved history"
            }
          >
            <RefreshCcw size={12} aria-hidden="true" />
          </ButtonControl>
        </span>
      </div>
      {searchOpen ? (
        <form
          className="history-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSearch();
          }}
        >
          <label className="sr-only" htmlFor="history-search-query">
            History search query
          </label>
          <TextInput
            density="compact"
            id="history-search-query"
            type="search"
            value={searchInput}
            onChange={(event) => onSearchInputChange(event.target.value)}
            placeholder="Cards, street, action..."
            maxLength={100}
            disabled={controlsDisabled}
            autoComplete="off"
            autoFocus
          />
          <ButtonControl
            type="submit"
            iconOnly
            disabled={controlsDisabled || searchInput.trim().length === 0}
            title="Run history search"
            aria-label="Run history search"
          >
            <Search size={12} aria-hidden="true" />
          </ButtonControl>
        </form>
      ) : null}
      {items.length > 0 ? (
        <div className="history-list">
          {items.map((item, index) => {
            const cards = historyCards(item.job);
            const action = historyAction(item.job);
            const hasTitle = Boolean(item.job.title);
            return (
              <ScreenshotRailItem
                className="history-item"
                key={`${item.id}-${item.savedAt}`}
                manageLabel={`Manage history item ${index + 1}: ${item.job.original_filename}`}
                onManage={() => onManageJob(item.job)}
                onOpen={() => onOpenItem(item)}
                openClassName="history-item-open"
                openLabel={`Reopen history item ${index + 1}`}
              >
                <span className="history-cards">
                  {cards.length > 0 ? (
                    cards.map((card) => (
                      <span
                        key={cardToCode(card)}
                        className={isRedSuit(card) ? "red-card" : ""}
                      >
                        {cardToDisplay(card)}
                      </span>
                    ))
                  ) : (
                    <small>No cards</small>
                  )}
                </span>
                <span className="history-meta">
                  <strong className={hasTitle ? "history-title" : ""}>
                    {hasTitle ? screenshotLabel(item.job) : action}
                  </strong>
                  <small>
                    {hasTitle
                      ? `${relativeTimeLabel(item.savedAt)} \u00b7 ${action}`
                      : relativeTimeLabel(item.savedAt)}
                  </small>
                </span>
                <span className="history-result">
                  {item.job.recommendation
                    ? `${Math.round(item.job.recommendation.confidence * 100)}%`
                    : item.job.status.slice(0, 1).toUpperCase()}
                </span>
              </ScreenshotRailItem>
            );
          })}
          {remaining > 0 ? (
            <ButtonControl
              variant="secondary"
              className="history-load-older"
              onClick={onLoadOlder}
              disabled={controlsDisabled}
              aria-label="Load older history"
            >
              <ChevronDown size={12} aria-hidden="true" />
              <span>{loading ? "Loading..." : `Load ${remaining} older`}</span>
            </ButtonControl>
          ) : null}
        </div>
      ) : (
        <StateMessage className="history-empty" framed size="compact">
          {loading
            ? "Loading saved history..."
            : searchActive
              ? "No saved hands match this search."
              : "Cleared reviewed hands will appear here."}
        </StateMessage>
      )}
    </section>
  );
}
