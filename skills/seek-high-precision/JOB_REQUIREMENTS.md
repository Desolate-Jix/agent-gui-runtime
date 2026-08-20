# SEEK Job Requirements

This file is the dedicated job-screening policy for the SEEK high-precision skill.
When this file conflicts with older run notes, this file wins.

The runtime must treat this file as a gate before Quick Apply and as required context before any final-submit audit.

## Candidate Target

The candidate is targeting early-career software roles in New Zealand.

Preferred role families:

- Software Engineer / Developer.
- Full-stack, frontend, backend, and web application roles.
- Automation, integration, API, and business systems roles.
- AI application / AI engineering roles with a software implementation focus.
- Junior data/software roles when programming work is central.

Known candidate strengths:

- Master of IT.
- JavaScript, React, frontend, SQL, API, Python, automation, and AI projects.
- New Zealand work rights from reviewed profile evidence.
- Can start immediately or within around 1-2 weeks when asked.

Do not invent or overstate:

- Years of commercial experience.
- Java, Angular, Vue, MySQL, DevOps, cloud, leadership, or senior ownership experience.
- Relocation willingness.
- Salary expectations.
- Security clearance, police check, or background-check answers.
- Any work-rights detail beyond reviewed evidence.

## Screening Labels

Every job must receive exactly one screening label before Apply is opened:

- `hard_skip`
- `needs_review`
- `allowed_to_score`

Only `allowed_to_score` jobs may proceed to automated scoring. A later scoring step may produce:

- `strong_apply`
- `maybe_apply`
- `skip_after_scoring`

`needs_review` must not become `strong_apply` unless the user explicitly approves that exact job.

## Hard Skip Rules

Mark `hard_skip` and do not enter Quick Apply when any rule below is true.

### Experience Hard Skip

Hard skip if the job explicitly requires a minimum of 2 years or more professional, commercial, or relevant experience.

Examples:

- `2+ years`
- `2 years experience`
- `minimum 2 years`
- `at least 2 years`
- `3+ years`
- `5+ years`
- `7+ years`
- `10+ years`
- `2-4 years`
- `3-5 years`
- `5-7 years`

Ranges are hard skip only when the lower bound is at least 2.

### Seniority Hard Skip

Hard skip if the title or description indicates a clearly non-entry-level role.

Examples:

- Senior / Principal / Staff / Lead role with explicit years requirement.
- Senior / Principal / Staff / Lead role with architecture ownership.
- Role requiring mentoring juniors as a core duty.
- Role requiring team leadership, technical leadership, roadmap ownership, or deep ownership of production systems.
- Role requiring extensive, deep, proven, or expert commercial experience.

### Relevance Hard Skip

Hard skip if the job is not professionally aligned with the candidate target.

Examples:

- Non-software IT support role with little or no development work.
- Sales, marketing, finance, admin, or customer-service role without a software development focus.
- Hardware, embedded, or electrical role unless software development is central and the skill match is strong.
- Role dominated by senior DevOps, infrastructure, cybersecurity, data engineering, or architecture skills not evidenced in the candidate profile.

### Location Hard Skip

Do not hard skip solely because the location is outside Auckland.

Hard skip only when both are true:

- The location is outside Auckland.
- The role is not strongly aligned with the candidate profile.

## Needs Review Rules

Mark `needs_review` and do not enter Quick Apply unless the user explicitly approves that exact job.

### Experience Review

Needs review:

- `1-2 years`
- `1-3 years`
- `1+ year`
- `1 year commercial experience`
- Junior commercial experience wording when it is required but not clearly optional.
- `Some commercial experience required` when no year count is given.
- Senior-looking title with no explicit years and no clear leadership or architecture evidence.
- Intermediate title.
- Graduate role that still asks for commercial experience.

Important distinction:

- `1-2 years` is review, not hard skip, because the lower bound is 1.
- `2+ years`, `2 years`, or `minimum 2 years` is hard skip.

### Location Review

Needs review:

- Any non-Auckland role that is otherwise relevant but not an obvious strong match.
- Christchurch, Wellington, Hamilton, Tauranga, Dunedin, or other New Zealand cities when relocation or onsite expectations are unclear.
- Hybrid or onsite roles outside Auckland.
- Remote New Zealand roles when location expectations are unclear.

Non-Auckland roles may continue only when the role is highly aligned with the candidate profile.

### Answer-Risk Review

Needs review when the application asks about:

- Java, Angular, AngularJS, Vue, MySQL, DevOps, cloud, CI/CD, leadership, or other skills not clearly evidenced.
- Years of experience.
- Relocation.
- Salary.
- Citizenship, residency, security clearance, police check, or background check.
- Driver licence or travel requirements.
- Availability beyond known immediate / around 1-2 weeks availability.

Unsupported `Yes` answers are forbidden.

## Allowed To Score

Mark `allowed_to_score` only when all are true:

- No hard-skip rule is triggered.
- No needs-review rule is triggered.
- The role is professionally relevant.
- The role appears entry-level or early-career compatible.

Allowed examples:

- Graduate.
- Junior.
- Entry-level.
- Early-career.
- Internship.
- Trainee.
- Associate developer.
- No-years-mentioned developer role with no senior ownership signals.

Allowed role types:

- Software / web / frontend / backend / full-stack.
- API / integration / automation.
- AI application developer role with software implementation.
- Business systems developer role when the required stack is close to the candidate profile.

## Scoring Policy

Only `allowed_to_score` jobs may receive automated scoring.

Positive signals:

- Auckland location.
- Junior / graduate / entry-level wording.
- Strong overlap with JavaScript, React, frontend, SQL, API, Python, automation, or AI application work.
- Clear software development responsibilities.
- Reasonable start-date expectations.
- Work rights compatible with reviewed evidence.

Negative signals:

- Outside Auckland.
- Contract, fixed-term, or short duration.
- Weak skill overlap.
- Required stack includes multiple unsupported skills.
- Vague seniority.
- Heavy business analyst, support, infrastructure, DevOps, or leadership focus.
- Employer questions require unsupported claims.

Scoring labels:

- `strong_apply`: entry-level compatible, professionally aligned, strong skill overlap, full detail read, no unsupported mandatory answers, no non-Auckland or contract risk requiring review.
- `maybe_apply`: relevant but has moderate risk, partial skill match, or location / contract / requirement details need judgment. Do not enter Apply without user approval.
- `skip_after_scoring`: not worth applying after reading details due to weak relevance, weak skill match, poor location fit, or hidden seniority risk.

## Apply Policy

Opening an application entry is separate from final submit.

On SEEK, label semantics are strict:

- `Quick apply` is the SEEK internal application entry.
- `Apply` is treated as an external / company-site application entry by default.
- For the current SEEK internal-flow tests, open only `Quick apply`. Do not click plain `Apply`.

The runtime may open SEEK Quick apply only when:

- Screening label is `allowed_to_score`.
- Scoring label is `strong_apply`.
- Full job detail has been read.
- Current live replay produced the match decision.
- No hard-skip or needs-review rule is active.
- The job is not an external ATS application.
- The visible entry button label is `Quick apply`.

Do not enter Apply for:

- `hard_skip`
- `needs_review`
- `maybe_apply`
- `skip_after_scoring`
- External ATS / company website applications.
- Plain `Apply` buttons on SEEK.
- Any job where the current live match decision is missing.

## Employer Questions

Before answering any employer question, create an answer audit.

Each answer must be one of:

- `safe_known`
- `needs_user_review`
- `unsupported`
- `blocked_sensitive`

Rules:

- Never answer `Yes` to a skill unless candidate evidence supports it.
- Never claim years of experience unless explicitly evidenced.
- Never claim relocation willingness unless the user approved that exact job/location.
- Work rights may be answered only from known work-rights evidence.
- Availability may be answered only from known availability evidence.
- Any `unsupported`, `needs_user_review`, or `blocked_sensitive` answer blocks final submit.

## Final Submit Policy

Final Submit / Send Application / Complete Application is always blocked unless all requirements below are met:

- `final_submit_decision_v1`
- Current live job identity.
- Current live match decision.
- Full job detail evidence.
- Skill-match evidence.
- Employer-question answer audit.
- Risk flags.
- Explicit user approval for that exact job.

The runtime must never autonomously click Final Submit.
No policy in this file allows relaxing the final-submit block.

## Required Evidence Before Apply Entry

```json
{
  "job_identity": {
    "title": "",
    "company": "",
    "location": "",
    "employment_type": "",
    "work_type": "",
    "contract_duration": "",
    "job_url_or_id": ""
  },
  "screening_decision": {
    "label": "hard_skip | needs_review | allowed_to_score",
    "reasons": [],
    "experience_gate": "",
    "location_gate": "",
    "relevance_gate": ""
  },
  "match_decision": {
    "label": "strong_apply | maybe_apply | skip_after_scoring",
    "generated_from_current_live_replay": true,
    "evidence_trace_path": ""
  },
  "risk_flags": []
}
```

## Required Evidence Before Final Submit

```json
{
  "final_submit_decision_v1": {
    "allow_final_submit": false,
    "explicit_user_approval_for_exact_job": false,
    "block_reasons": [],
    "job_identity": {},
    "match_decision": {},
    "skill_match_evidence": {},
    "application_answers_audit": [],
    "risk_flags": []
  }
}
```

`allow_final_submit` must remain `false` unless the user explicitly approves the exact job after reviewing the structured audit.
