/**
 * Minimal Server-Sent Events frame parser.
 *
 * The chat endpoint authenticates with an `X-API-Key` header, which
 * `EventSource` cannot send — so we stream with `fetch` + `ReadableStream`
 * and parse the `event:` / `data:` frames ourselves, following the WHATWG
 * EventSource processing model (line endings: CRLF, LF, or CR; multi-line
 * `data:` joined with `\n`; `:` comment lines ignored).
 */

export interface SSEEvent {
  /** Event type; `"message"` when the stream did not set one. */
  event: string;
  /** Concatenated data lines, joined with `\n`. */
  data: string;
  /** Last seen `id:` field, if any. */
  id?: string;
}

/** Incremental parser: feed decoded text chunks, collect completed events. */
export class SSEParser {
  private buffer = "";
  private eventType = "";
  private dataLines: string[] = [];
  private lastId: string | undefined;

  /** Consume a chunk (may contain partial lines) and return completed events. */
  feed(chunk: string): SSEEvent[] {
    this.buffer += chunk;
    const events: SSEEvent[] = [];
    let pos = 0;

    while (pos < this.buffer.length) {
      let lineEnd = -1;
      let skip = 1;
      for (let i = pos; i < this.buffer.length; i++) {
        const ch = this.buffer[i];
        if (ch === "\n") {
          lineEnd = i;
          break;
        }
        if (ch === "\r") {
          if (i === this.buffer.length - 1) {
            // Ambiguous: a "\n" may follow in the next chunk. Wait for it.
            lineEnd = -1;
          } else {
            lineEnd = i;
            if (this.buffer[i + 1] === "\n") skip = 2;
          }
          break;
        }
      }
      if (lineEnd === -1) break;

      const line = this.buffer.slice(pos, lineEnd);
      pos = lineEnd + skip;
      const event = this.processLine(line);
      if (event) events.push(event);
    }

    this.buffer = this.buffer.slice(pos);
    return events;
  }

  /**
   * Signal end of stream. A buffered trailing `\r` was held back because a
   * `\n` could still have followed; at EOF it is a definite line ending.
   * Any other unterminated partial frame is discarded, per spec.
   */
  end(): SSEEvent[] {
    const events = this.buffer.endsWith("\r") ? this.feed("\n") : [];
    this.buffer = "";
    return events;
  }

  private processLine(line: string): SSEEvent | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null; // comment

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    switch (field) {
      case "event":
        this.eventType = value;
        break;
      case "data":
        this.dataLines.push(value);
        break;
      case "id":
        if (!value.includes("\0")) this.lastId = value;
        break;
      default:
        // "retry" and unknown fields are ignored.
        break;
    }
    return null;
  }

  private dispatch(): SSEEvent | null {
    const eventType = this.eventType;
    this.eventType = "";
    if (this.dataLines.length === 0) return null;
    const data = this.dataLines.join("\n");
    this.dataLines = [];
    return { event: eventType || "message", data, id: this.lastId };
  }
}

/** Iterate SSE events from a streaming response body. */
export async function* readSSE(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEEvent, void, undefined> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.feed(decoder.decode(value, { stream: true }));
    }
    // Flush any bytes buffered in the decoder; an unterminated final frame
    // is discarded, per spec.
    yield* parser.feed(decoder.decode());
    yield* parser.end();
  } finally {
    reader.releaseLock();
  }
}
