import { describe, expect, it } from "vitest";
import { formatCurrency, formatDate, newId } from "./utils";

describe("utils", () => {
  it("formats dollars with cents", () => {
    expect(formatCurrency(178.48)).toBe("$178.48");
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("shows a dash for missing dates", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("creates distinct ids without crypto.randomUUID", () => {
    const ids = new Set(Array.from({ length: 50 }, () => newId("msg")));
    expect(ids.size).toBe(50);
  });
});
