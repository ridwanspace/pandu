#!/usr/bin/env bash
# Fetch the Pandu seed corpus: four NIST cybersecurity publications.
#
# NIST Special Publications are works of the US federal government —
# public domain in the United States (17 U.S.C. §105). See CORPUS_LICENSE.md.
#
# NOTE: URLs below are the canonical nvlpubs.nist.gov DOI-style locations at
# the time of writing. If a download fails, verify the current URL on the
# publication page at https://csrc.nist.gov/publications before retrying.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORPUS_DIR="${REPO_ROOT}/backend/evals/corpus"

# A real NIST PDF is megabytes; anything under this is an error/redirect page.
MIN_BYTES=100000

mkdir -p "${CORPUS_DIR}"

fetch() {
    local url="$1"
    local dest="${CORPUS_DIR}/$2"

    if [[ -s "${dest}" ]]; then
        echo "skip   $2 (already present)"
        return
    fi

    echo "fetch  $2"
    curl -fsSL --retry 3 --retry-delay 2 -o "${dest}.part" "${url}"

    local size
    size=$(wc -c < "${dest}.part")
    if (( size < MIN_BYTES )); then
        rm -f "${dest}.part"
        echo "error: $2 is only ${size} bytes — likely not the PDF." >&2
        echo "       Verify the URL at https://csrc.nist.gov/publications" >&2
        exit 1
    fi
    if ! head -c 5 "${dest}.part" | grep -q '%PDF-'; then
        rm -f "${dest}.part"
        echo "error: $2 does not look like a PDF (bad magic bytes)." >&2
        exit 1
    fi

    mv "${dest}.part" "${dest}"
    echo "ok     $2 ($(( size / 1024 )) KiB)"
}

fetch "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf" \
      "nist-sp-800-53r5.pdf"
fetch "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63b.pdf" \
      "nist-sp-800-63b.pdf"
fetch "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r3.pdf" \
      "nist-sp-800-171r3.pdf"
fetch "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf" \
      "nist-csf-2.0.pdf"

echo
echo "Corpus ready in ${CORPUS_DIR}:"
ls -lh "${CORPUS_DIR}"
