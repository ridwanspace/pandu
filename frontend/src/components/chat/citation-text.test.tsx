import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CitationText, citedMarkers, splitCitationSegments } from "@/components/chat/citation-text";

describe("splitCitationSegments", () => {
  it("splits text around markers", () => {
    expect(splitCitationSegments("See [1] and [12].")).toEqual([
      { type: "text", value: "See " },
      { type: "citation", marker: 1 },
      { type: "text", value: " and " },
      { type: "citation", marker: 12 },
      { type: "text", value: "." },
    ]);
  });

  it("returns a single text segment when there are no markers", () => {
    expect(splitCitationSegments("plain text")).toEqual([{ type: "text", value: "plain text" }]);
  });

  it("ignores non-numeric brackets", () => {
    expect(splitCitationSegments("[abc] [1a]")).toEqual([{ type: "text", value: "[abc] [1a]" }]);
  });
});

describe("citedMarkers", () => {
  it("collects the distinct markers referenced in the text", () => {
    expect(citedMarkers("A [2] B [1] C [2]")).toEqual(new Set([1, 2]));
  });

  it("is empty for text without markers", () => {
    expect(citedMarkers("no citations here").size).toBe(0);
  });
});

describe("CitationText", () => {
  it("renders plain text unchanged", () => {
    render(<CitationText text="Just an answer." />);
    expect(screen.getByText("Just an answer.")).toBeInTheDocument();
  });

  it("renders [n] markers as accessible superscript chips", () => {
    render(<CitationText text="Fact [1] and fact [2]." validMarkers={new Set([1, 2])} />);
    expect(screen.getByRole("button", { name: "Source 1" })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "Source 2" })).toHaveTextContent("2");
    // The raw "[1]" text must be replaced, not duplicated.
    expect(screen.queryByText("[1]", { exact: false })).not.toBeInTheDocument();
  });

  it("leaves markers without a matching citation as literal text", () => {
    render(<CitationText text="Known [1], unknown [9]." validMarkers={new Set([1])} />);
    expect(screen.getByRole("button", { name: "Source 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Source 9" })).not.toBeInTheDocument();
    expect(screen.getByText("[9]", { exact: false })).toBeInTheDocument();
  });

  it("invokes the click handler with the marker number", async () => {
    const user = userEvent.setup();
    const onMarkerClick = vi.fn();
    render(
      <CitationText text="Fact [3]." validMarkers={new Set([3])} onMarkerClick={onMarkerClick} />,
    );
    await user.click(screen.getByRole("button", { name: "Source 3" }));
    expect(onMarkerClick).toHaveBeenCalledWith(3);
  });

  it("treats every marker as valid when no set is provided", () => {
    render(<CitationText text="Streaming [4]" />);
    expect(screen.getByRole("button", { name: "Source 4" })).toBeInTheDocument();
  });
});
