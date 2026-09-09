/**
 * The one page the app ships. Its metadata is what a shared link renders as, and nothing else
 * in the test suite ever loads it — so the template's placeholders sat in production untested.
 *
 * @vitest-environment node
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const html = readFileSync(
  fileURLToPath(new URL("../../index.html", import.meta.url)),
  "utf8",
);

describe("index.html", () => {
  it("keeps the league's title", () => {
    expect(html).toContain("<title>Ultimate Guillotine League</title>");
  });

  it("carries no scaffold placeholders", () => {
    expect(html).not.toContain("Your Name or Company Name");
    expect(html).not.toContain("@yourtwitterhandle");
    // There is nothing to join: the board is read-only and the league is invite-only.
    expect(html).not.toContain("Join the Ultimate Guillotine League");
  });

  it("describes the read-only board in every description tag", () => {
    const descriptions = [
      ...html.matchAll(/(?:name|property)="(?:og:|twitter:)?description"\s+content="([^"]+)"/g),
    ].map((match) => match[1]);
    expect(descriptions).toHaveLength(3);
    for (const description of descriptions) {
      expect(description).toContain("Ultimate Guillotine League");
      expect(description).toContain("projections");
    }
  });
});
