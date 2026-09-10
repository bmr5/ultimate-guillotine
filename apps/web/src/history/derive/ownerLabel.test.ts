import { describe, expect, it } from "vitest";

import { championDisplay } from "./ownerLabel";

describe("championDisplay", () => {
  it("puts the asterisk after exactly one name", () => {
    expect(championDisplay("Ben R")).toBe("Ben R*");
    expect(championDisplay("Nick Nifty")).toBe("Nick Nifty");
  });
});
