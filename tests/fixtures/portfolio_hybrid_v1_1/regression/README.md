# Regression partition

This directory is reserved for the existing five-screen evidence and additional public or synthetic regression cases. Regression evidence may be used for deterministic interface checks and pre-VISTA diagnostics, but it is not untouched holdout proof.

Exactly five distinct screenshots must carry `source_provenance=existing_five_screen_regression`; that provenance is rejected in holdout. Regression and holdout image paths and byte hashes must be disjoint. Provider projections are sealed-run scoped and must never expose cases from the other partition.

Task 5A does not copy images, launch providers, or create predictions. Task 5B must add reviewed corpus assets and bind every image and private annotation by SHA-256 before any prediction run.

The combined sealed corpus must contain 20–30 distinct screenshots and 100–200 independently reviewed important targets. Every image requires approved privacy/review evidence, and every target requires independent annotator/reviewer identity hashes plus an approved disagreement disposition. Regression reports are diagnostic and the release gate always rejects them.

The corpus and Gold files are canonical UTF-8 JSON contracts (`portfolio_hybrid_v1_1_corpus_records_v1` and `portfolio_hybrid_v1_1_gold_records_v1`). Their records must exactly equal the inline records being sealed and scored; opaque placeholders are invalid.
