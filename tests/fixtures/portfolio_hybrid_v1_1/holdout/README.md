# Holdout partition

This directory is reserved for untouched public or synthetic holdout cases. Do not inspect holdout predictions, tune prompts, change thresholds, or run any provider before the immutable corpus and private review evidence are sealed.

Task 5A creates interfaces only. Its regression dry-run records zero holdout predictions and cannot be cited as holdout quality evidence.

The sealed holdout must contain at least 10 distinct screenshots and 50 independently reviewed important targets. Its image paths and byte hashes must be disjoint from regression, including the existing five-screen regression-only evidence.

After Task 5B seals the corpus, each holdout prediction must reference the exact sealed run and request, statistical arm, producer revision, provider revisions/evidence, equal budget, shared UIA/OCR policy, and hashed lifecycle cleanup evidence. Promotion additionally requires successful bounded VISTA refinement and an approved post-review result for every scored holdout target.

Requests, scoring, and gating rehash every sealed artifact and image from the benchmark root. The evaluated gate object must exactly match the gate config identity and bytes sealed into the manifest/run; a separately rehashed substitute is invalid.
