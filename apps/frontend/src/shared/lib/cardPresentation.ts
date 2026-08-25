import type { Card, Suit } from "../types/poker";

export const SUIT_BY_CODE: Readonly<Record<string, Suit>> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};

export const CODE_BY_SUIT: Readonly<Record<Suit, string>> = {
  clubs: "c",
  diamonds: "d",
  hearts: "h",
  spades: "s",
};

const SYMBOL_BY_SUIT: Readonly<Record<Suit, string>> = {
  clubs: "♣",
  diamonds: "♦",
  hearts: "♥",
  spades: "♠",
};

export function cardToCode(card: Card): string {
  return `${card.rank}${CODE_BY_SUIT[card.suit]}`;
}

export function cardToDisplay(card: Card): string {
  return `${card.rank}${SYMBOL_BY_SUIT[card.suit]}`;
}

export function isRedSuit(card: Card): boolean {
  return card.suit === "hearts" || card.suit === "diamonds";
}
