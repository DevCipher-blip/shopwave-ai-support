import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchStats, subscribeAdminStream } from "./api";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("admin API client", () => {
  it("sends the bearer token and surfaces HTTP status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchStats("secret-token").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ Authorization: "Bearer secret-token" });
  });

  it("reads log events from a stream split mid-event", async () => {
    const body = streamOf('event: log\ndata: {"type":"decision","decis', 'ion":"deny"}\n\n: ping\n\n');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));

    const logs: unknown[] = [];
    await new Promise<void>((resolve) => {
      subscribeAdminStream("t", (log) => { logs.push(log); resolve(); }, () => resolve());
    });
    expect(logs).toEqual([{ type: "decision", decision: "deny" }]);
  });

  it("reports a rejected stream through onError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    const err = await new Promise((resolve) => subscribeAdminStream("t", () => undefined, resolve));
    expect(err).toBeInstanceOf(ApiError);
  });
});
