/**
 * The vocabulary every board comparator is written in. Both the team sort and the roster sort
 * need the same three results and the same collator; keeping one copy here means the two orders
 * cannot drift apart, and a reader who learns the names once knows them everywhere.
 */

/**
 * Comparator results, named so null handling reads as intent rather than as sign arithmetic.
 * `Array.prototype.sort` only looks at the sign, so the magnitude is irrelevant.
 */
export const A_BEFORE_B = -1;
export const B_BEFORE_A = 1;
export const TIED = 0;

/**
 * Fixed-locale collator so a name tie-break is the same on the Mac mini, in CI, and in a
 * browser. Bare `localeCompare` follows the host locale, which would make the order depend on
 * the environment for names that differ only by accent or case.
 */
export const NAME_COLLATOR = new Intl.Collator("en");
