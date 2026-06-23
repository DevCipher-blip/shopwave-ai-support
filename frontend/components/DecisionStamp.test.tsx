import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DecisionStamp } from "./DecisionStamp";

describe("DecisionStamp", () => {
  it.each([
    ["approve", "Approved"],
    ["deny", "Denied"],
    ["escalate", "Escalated"],
    [null, "Open"],
    ["something-new", "Open"],
  ])("labels %s as %s", (decision, label) => {
    render(<DecisionStamp decision={decision} />);
    expect(screen.getByText(label)).toBeDefined();
  });
});
