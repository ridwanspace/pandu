import { describe, expect, it } from "vitest";
import { readSSE, type SSEEvent, SSEParser } from "@/lib/sse";

function feedAll(parser: SSEParser, chunks: string[]): SSEEvent[] {
  return chunks.flatMap((chunk) => parser.feed(chunk));
}

describe("SSEParser", () => {
  it("parses a single event with type and data", () => {
    const events = new SSEParser().feed('event: token\ndata: {"text":"hi"}\n\n');
    expect(events).toEqual([{ event: "token", data: '{"text":"hi"}', id: undefined }]);
  });

  it("defaults the event type to message", () => {
    const events = new SSEParser().feed("data: hello\n\n");
    expect(events).toEqual([{ event: "message", data: "hello", id: undefined }]);
  });

  it("joins multi-line data with newlines", () => {
    const events = new SSEParser().feed("data: line one\ndata: line two\n\n");
    expect(events[0].data).toBe("line one\nline two");
  });

  it("parses multiple events in one chunk", () => {
    const events = new SSEParser().feed("event: token\ndata: a\n\nevent: token\ndata: b\n\n");
    expect(events.map((e) => e.data)).toEqual(["a", "b"]);
  });

  it("handles frames split across chunks at arbitrary points", () => {
    const parser = new SSEParser();
    const events = feedAll(parser, ["event: tok", "en\nda", 'ta: {"text":', '"x"}\n', "\n"]);
    expect(events).toEqual([{ event: "token", data: '{"text":"x"}', id: undefined }]);
  });

  it("supports CRLF and bare CR line endings", () => {
    expect(new SSEParser().feed("event: done\r\ndata: {}\r\n\r\n")).toEqual([
      { event: "done", data: "{}", id: undefined },
    ]);
    // A trailing CR is ambiguous mid-stream (a LF may follow); the final
    // blank line resolves once the next chunk arrives or the stream ends.
    const parser = new SSEParser();
    const events = [...parser.feed("event: done\rdata: {}\r\r"), ...parser.end()];
    expect(events).toEqual([{ event: "done", data: "{}", id: undefined }]);
  });

  it("handles a CRLF split across two chunks", () => {
    const parser = new SSEParser();
    const events = feedAll(parser, ["data: a\r", "\n\r\n"]);
    expect(events).toEqual([{ event: "message", data: "a", id: undefined }]);
  });

  it("ignores comment lines", () => {
    const events = new SSEParser().feed(": keep-alive\ndata: x\n\n");
    expect(events).toEqual([{ event: "message", data: "x", id: undefined }]);
  });

  it("strips exactly one leading space from field values", () => {
    const events = new SSEParser().feed("data:  padded\n\n");
    expect(events[0].data).toBe(" padded");
  });

  it("treats a field without a colon as an empty value", () => {
    const events = new SSEParser().feed("data\n\n");
    expect(events).toEqual([{ event: "message", data: "", id: undefined }]);
  });

  it("does not dispatch when the data buffer is empty", () => {
    const events = new SSEParser().feed("event: sources\n\n");
    expect(events).toEqual([]);
  });

  it("resets the event type between events", () => {
    const events = new SSEParser().feed("event: usage\ndata: u\n\ndata: m\n\n");
    expect(events.map((e) => e.event)).toEqual(["usage", "message"]);
  });

  it("carries the last seen id", () => {
    const events = new SSEParser().feed("id: 7\ndata: x\n\ndata: y\n\n");
    expect(events.map((e) => e.id)).toEqual(["7", "7"]);
  });
});

describe("readSSE", () => {
  it("iterates events from a byte stream, including multi-byte chunk splits", async () => {
    const encoder = new TextEncoder();
    const frames = encoder.encode(
      'event: token\ndata: {"text":"héllo"}\n\nevent: done\ndata: {}\n\n',
    );
    // Split inside the two-byte "é" to prove TextDecoder streaming works.
    const splitAt = 30;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(frames.slice(0, splitAt));
        controller.enqueue(frames.slice(splitAt));
        controller.close();
      },
    });

    const events: SSEEvent[] = [];
    for await (const ev of readSSE(stream)) events.push(ev);

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ event: "token", data: '{"text":"héllo"}' });
    expect(events[1]).toMatchObject({ event: "done", data: "{}" });
  });

  it("discards an unterminated trailing frame", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("data: complete\n\ndata: partial"));
        controller.close();
      },
    });

    const events: SSEEvent[] = [];
    for await (const ev of readSSE(stream)) events.push(ev);

    expect(events).toHaveLength(1);
    expect(events[0].data).toBe("complete");
  });
});
