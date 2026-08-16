# Corpus licensing

The evaluation and demo corpus used by Pandu (fetched by
`scripts/fetch_corpus.sh` into `backend/evals/corpus/`) consists of
publications of the **National Institute of Standards and Technology
(NIST)**, an agency of the United States Department of Commerce:

| File | Publication |
|---|---|
| `nist-sp-800-53r5.pdf` | NIST SP 800-53 Revision 5 — *Security and Privacy Controls for Information Systems and Organizations* |
| `nist-sp-800-63b.pdf` | NIST SP 800-63B — *Digital Identity Guidelines: Authentication and Lifecycle Management* |
| `nist-sp-800-171r3.pdf` | NIST SP 800-171 Revision 3 — *Protecting Controlled Unclassified Information in Nonfederal Systems and Organizations* |
| `nist-csf-2.0.pdf` | NIST CSWP 29 — *The NIST Cybersecurity Framework (CSF) 2.0* |

## Public-domain status

These documents are **works of the United States federal government**. Under
17 U.S.C. §105, works prepared by officers or employees of the US government
as part of their official duties are not subject to copyright protection in
the United States. They may be reproduced and redistributed freely.

## Acknowledgement

NIST requests acknowledgement when its publications are reused, and this
project gladly provides it:

> Portions of the corpus used by this project are publications of the
> National Institute of Standards and Technology (NIST), U.S. Department of
> Commerce, obtained from https://csrc.nist.gov. NIST does not endorse this
> project. The publications are used unmodified as retrieval source
> material.

The golden question/answer dataset in `backend/evals/` is original work
derived from reading these publications and is covered by this repository's
MIT license (see `LICENSE`).

## Optional secondary corpus (not fetched by default)

For a multilingual/regulatory flavor, the docs describe an optional
secondary corpus of EU law from **EUR-Lex**: the GDPR (Regulation (EU)
2016/679) and the EU AI Act (Regulation (EU) 2024/1689). EUR-Lex content is
reusable under **Creative Commons Attribution 4.0 (CC BY 4.0)** pursuant to
Commission Decision 2011/833/EU, with the required attribution:

> © European Union, https://eur-lex.europa.eu, 1998–2026. Reuse authorised
> under CC BY 4.0. Only European Union legislation printed in the Official
> Journal of the European Union is deemed authentic.

If you add these documents to your corpus, keep this notice with them.
