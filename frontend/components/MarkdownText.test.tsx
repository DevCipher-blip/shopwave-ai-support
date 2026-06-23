import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownText } from "./MarkdownText";

describe("MarkdownText", () => {
  it("renders bold text, lists and order numbers", () => {
    const { container } = render(
      <MarkdownText text={"Refund of **$89.99** approved.\n- order ORD-10015\n- 5–7 business days"} />
    );
    expect(screen.getByText("$89.99").tagName).toBe("STRONG");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByText("ORD-10015")).toHaveProperty("className", expect.stringContaining("font-mono"));
  });

  it("does not interpret HTML in agent output", () => {
    const { container } = render(<MarkdownText text={'<img src=x onerror="alert(1)">'} />);
    expect(container.querySelector("img")).toBeNull();
  });
});
