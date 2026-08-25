import type { JobRecord } from "../../../shared/types/jobs";

export const MAX_SCREENSHOT_TITLE_LENGTH = 120;
export const MAX_SCREENSHOT_NOTES_LENGTH = 1000;
export const MAX_SCREENSHOT_TAGS = 10;
export const MAX_SCREENSHOT_TAG_LENGTH = 32;
export const MAX_SCREENSHOT_TAG_INPUT_LENGTH =
  (MAX_SCREENSHOT_TAG_LENGTH + 2) * MAX_SCREENSHOT_TAGS;

export function screenshotTags(job: Pick<JobRecord, "tags">): string[] {
  return Array.isArray(job.tags)
    ? job.tags.filter((tag): tag is string => typeof tag === "string")
    : [];
}

export function parseScreenshotTags(value: string): string[] {
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const rawTag of value.split(",")) {
    const tag = rawTag.trim();
    if (!tag) {
      continue;
    }
    if (tag.length > MAX_SCREENSHOT_TAG_LENGTH) {
      throw new Error(
        `Tags can be at most ${MAX_SCREENSHOT_TAG_LENGTH} characters`,
      );
    }
    const key = tag.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    tags.push(tag);
  }
  if (tags.length > MAX_SCREENSHOT_TAGS) {
    throw new Error(`Use no more than ${MAX_SCREENSHOT_TAGS} tags`);
  }
  return tags;
}
