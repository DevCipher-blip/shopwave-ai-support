import { describe, expect, it } from "vitest";
import { parseSseBuffer } from "./sse";

describe("parseSseBuffer", () => {
  it("splits complete events and keeps the unfinished tail", () => {
    const { events, rest } = parseSseBuffer('event: log\ndata: {"a":1}\n\nevent: response\ndata: {"te');
    expect(events).toEqual([{ event: "log", data: '{"a":1}' }]);
    expect(rest).toBe('event: response\ndata: {"te');
  });

  it("joins multi-line data and handles CRLF line endings", () => {
    const { events } = parseSseBuffer("event: log\r\ndata: one\r\ndata: two\r\n\r\n");
    expect(events).toEqual([{ event: "log", data: "one\ntwo" }]);
  });

  it("skips keep-alive comments and defaults the event name", () => {
    const { events } = parseSseBuffer(": ping - 2026-11-10\n\ndata: hello\n\n");
    expect(events).toEqual([{ event: "message", data: "hello" }]);
  });
});
