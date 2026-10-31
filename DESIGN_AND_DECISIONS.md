# Architecture, Design Decisions & Technical Walkthrough

**Candidate:** Sachin Kaware  
**Company:** YottaFlex AI Recruitment Drive  
**Document Purpose:** Pillar 04 Submission — "Make Your Reasoning Visible" & Technical Interview Walkthrough Guide  

---

## 1. Problem Decomposition & Mental Model

### The Business Challenge
In real-world data pipelines, identity data arrives from multiple operational touchpoints (CRM, E-Commerce platforms, billing engines, support portals). These records lack universal global keys, contain formatting discrepancies (casing, whitespace, punctuation), suffer from missing or invalid attributes, and occasionally share identifiers across distinct real-world persons (e.g. household shared emails).

### Our Mental Model: A 4-Stage State Machine
We model the entity resolution lifecycle not as a single monolithic script, but as a formal state machine with strict stage boundaries:

```
                  ┌───────────────────────────────┐
                  │      Raw Input Batch CSV      │
                  └──────────────┬────────────────┘
                                 │
                     [1. INGESTION & HASHING]
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │       dbo.source_records      │
                  └──────────────┬────────────────┘
                                 │
                     [2. QUALITY CLASSIFICATION]
                                 │
         ┌───────────────────────┼────────────────────────┐
         │                       │                        │
         ▼                       ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│     REJECTED     │    │    UNRESOLVED    │    │      VALID       │
│ Missing keys,    │    │ No email and     │    │ Eligible for     │
│ malformed email, │    │ no phone         │    │ identity         │
│ conflicting dups │    │                  │    │ resolution       │
└──────────────────┘    └──────────────────┘    └────────┬─────────┘
                                                         │
                                               [3. ENTITY RESOLUTION]
                                                         │
                         ┌───────────────────────────────┼──────────────────────────────┐
                         ▼                               ▼                              ▼
              ┌─────────────────────┐         ┌─────────────────────┐        ┌─────────────────────┐
              │      CONFLICT       │         │       MAPPED        │        │     NEW_ENTITY      │
              │ Shared email with   │         │ Matched via:        │        │ No match found.     │
              │ differing identities│         │ • exact_email       │        │ Mint CAN-XXXX       │
              │ (Quarantined)       │         │ • rule_name_phone   │        │                     │
              └─────────────────────┘         └─────────────────────┘        └─────────────────────┘
                                                         │
                                              [4. RECONCILIATION AUDIT]
                                                         │
                                                         ▼
                                              Mathematical Invariant:
                                                  Discrepancy == 0
```

---

## 2. Core Assumptions

1. **Email Uniqueness Standard**: An email address uniquely identifies an individual **unless** conflicting evidence (distinct name or phone number) exists within the same batch.
2. **Deterministic Precedence**: Exact identifier links (email) take precedence over composite multi-attribute rules (Name + Phone).
3. **Data Quality Primacy**: Malformed records (missing keys, invalid email syntax) must be halted before matching algorithms run to avoid poisoning the canonical identity graph.
4. **Conservation Law**: No record may be silently dropped, overwritten, or unaccounted for. Every single input record must be classified into exactly one of six exhaustive, mutually exclusive categories.

---

## 3. Key Technical Decisions & Trade-Offs

### Decision 1: Pure Local-First SQLite vs. External Database Server
- **Context**: The repository originally used Microsoft SQL Server via `pyodbc`.
- **Options Considered**:
  1. *Dockerized PostgreSQL / MSSQL*: Requires Docker daemon, container configuration, network port bindings, and connection wait scripts.
  2. *In-Memory Only (Dicts/Pandas)*: Zero persistence; impossible to inspect tables or retain run history.
  3. *SQLite with Write-Ahead Logging (WAL)* (Selected): Native to Python standard library, zero external installation, creates a portable `data/pipeline.db` file, enforces foreign keys and unique constraints, and supports ACID transactions.
- **Trade-Off**: SQLite does not support high-concurrency multi-writer distributed topologies. For an enterprise batch pipeline with single-process orchestration, this trade-off is optimal for reliability, speed, and ease of evaluation.

### Decision 2: In-Memory Inverted Index vs. SQL Lookups
- **Context**: Matching thousands of records against existing canonical records.
- **Decision**: Read existing canonical entities once at batch startup, construct in-memory Python dictionaries:
  - `email_index: Dict[str, str]` (Normalized Email $\rightarrow$ Canonical ID)
  - `name_phone_index: Dict[Tuple[str, str], str]` ((Normalized Name, Normalized Phone) $\rightarrow$ Canonical ID)
- **Trade-Off**: Uses slightly more memory ($~10$ MB for 100,000 records). In return, resolution time drops from $O(N^2)$ to $O(N)$, sustaining **~9,200 records/sec**.

### Decision 3: Eager Conflict Quarantine vs. "First-Wins" Blind Merging
- **Context**: Records `C201` (Asha Kulkarni, `shared@gmail.com`) and `C202` (Neha Joshi, `shared@gmail.com`) arrive together.
- **Options Considered**:
  1. *Blind Merge*: Assign both to the same canonical entity.
  2. *Heuristic Winner*: Assign to whoever has the earlier timestamp.
  3. *Quarantine to `mapping_conflicts`* (Selected): Treat ambiguity as an operational exception. Flag initial pair as `email_collision`, third+ occurrences as `multiple_candidates`, and write to `mapping_conflicts` with `status='OPEN'`.
- **Trade-Off**: Requires downstream human operator review or secondary verification. Prevents irreversible corruption of customer identity records.

### Decision 4: Deterministic Matching vs. Probabilistic Scoring (Fuzzy / Fellegi-Sunter)
- **Context**: Handling typographical variations.
- **Decision**: Enforce exact normalized string comparisons (`lower()`, `strip()`, Title Case, digit-only phones) plus rule-based conjunctions.
- **Trade-Off**: Pure deterministic matching rejects minor typos (e.g. `sachin.jadhav` vs `sachin.jadhv`). However, for a 0–3 years scope and compliance-focused MDM, deterministic matching is 100% explainable, mathematically auditable, and eliminates false-positive merges.

---

## 4. Edge Cases Matrix & Handling Strategy

The pipeline explicitly handles all scenarios mandated by the specification:

| Edge Case / Scenario | Pipeline Stage | Detection Mechanism | Resolution Outcome |
| :--- | :--- | :--- | :--- |
| **Malformed Email** (e.g. `invalid-email`, `@missing.com`) | Validation | RFC Regex syntax check | `REJECTED / invalid_email` $\rightarrow$ quarantined |
| **Missing Primary Key** (Missing `source_id` or `source_system`) | Validation | Null / whitespace check | `REJECTED / missing_source_id` $\rightarrow$ quarantined |
| **Duplicate Source Key (Identical)** | Validation | State dictionary tracking `(sys, id)` with matching data | `DUPLICATE / duplicate_source_key` $\rightarrow$ quarantined |
| **Duplicate Source Key (Conflicting)** | Validation | State dictionary tracking `(sys, id)` with conflicting data | `REJECTED / conflicting_duplicate_source_key` (both rejected) |
| **No Identifiers** (No email and no phone) | Validation | Null check on both identifiers | `UNRESOLVED / no_identifiers` $\rightarrow$ quarantined |
| **One-to-Many Email Collision** (Distinct names/phones sharing email) | Resolution Pre-Pass | Grouping records by normalized email | `CONFLICT / email_collision` or `multiple_candidates` |
| **Identical Duplicate Batch / Re-run** | Ingestion | SHA-256 hash comparison against `pipeline_runs` | `SKIPPED` (idempotent, no duplicate entries created) |
| **Empty Input Batch** | Ingestion / Validation | Row count check | Returns empty structured report, `0` records processed |
| **Schema Mismatch / Extra Columns** | Ingestion | Column set comparison against expected schema | Raises explicit `ValueError` before database operations |

---

## 5. How We Know the Solution Works

We prove correctness through four independent layers of evidence:

### Proof Layer 1: The Conservation Law
In every run, the pipeline computes the record balance:
$$\text{Accounted} = \text{New Entities} + \text{Deterministic Mapped} + \text{Conflicts} + \text{Unresolved} + \text{Duplicates} + \text{Rejects}$$
$$\text{Discrepancy} = \text{Total Input Records} - \text{Accounted}$$
If $\text{Discrepancy} \neq 0$, the pipeline flags `DISCREPANCY DETECTED` and fails. In our runs:
$$\text{Total Input (13)} = 3 + 3 + 3 + 1 + 1 + 2 = 13 \quad (\text{Discrepancy} = 0)$$

### Proof Layer 2: Ground-Truth Parity Test (100% Accuracy)
The automated integration test (`tests/test_end_to_end.py`) asserts **row-by-row equivalence** between the pipeline output and `data/expected/expected_results.csv`:
- All 13 outcomes match exactly.
- All 13 match types match exactly.
- All 13 source system and source ID mappings match exactly.

### Proof Layer 3: Comprehensive 28-Test Suite
- 13 unit tests for normalization (lowercasing, whitespace collapsing, international phone codes `+91`, `+1`, null representations).
- 7 unit tests for validation rules (missing keys, syntax, duplicates).
- 7 unit tests for resolution logic (new entities, exact email, normalized email, composite rules, collision detection).
- 1 end-to-end integration test.
- **Execution time:** `0.35s` for all 28 tests.

### Proof Layer 4: Empirical Scalability Benchmarks
- Tested across synthetic volumes of 500, 2,500, and 10,000 records.
- Sustains throughput of **~9,200 records/second**.

---

## 6. Interview Walkthrough Cheat Sheet (15-Minute Guide)

When walking interviewers through the project, structure your presentation as follows:

```
[MINUTES 0-3]  THE PROBLEM & ARCHITECTURE
• "We built an end-to-end entity resolution pipeline to solve customer identity fragmentation."
• "It ingests multi-source data, standardizes attributes, applies deterministic multi-pass matching,
   quarantines conflicts, and maintains full mapping audit history."
• "Show them the 4-stage pipeline diagram in README.md."

[MINUTES 3-7]  THE CODEWALK: 4 CLEAN STAGES
• Stage 1 (src/ingestion.py): "Notice the SHA-256 file hashing. If the same batch is loaded twice,
   it skips execution for idempotency, unless --force is passed."
• Stage 2 (src/validation.py): "We enforce a strict data-quality filter. Missing keys or invalid emails
   are quarantined immediately into data_quality_rejects. Records with no identifiers go to unresolved_mappings."
• Stage 3 (src/resolution.py): "Notice the pre-pass collision detection. When multiple people share an email,
   we don't guess — we quarantine them into mapping_conflicts. Valid records then resolve in O(N) time
   via in-memory inverted hash indexes."
• Stage 4 (src/reconciliation.py): "Every execution produces a Markdown audit report and asserts our
   conservation law: Discrepancy must equal zero."

[MINUTES 7-10] LIVE DEMO
• Terminal 1: Run `python run_pipeline.py` -> Show BALANCED summary.
• Terminal 2: Run `python run_tests.py` -> Show 28 passed tests in 0.35s.
• Terminal 3: Run `python -m src.benchmark` -> Show ~9,200 rec/sec performance.

[MINUTES 10-13] TECHNICAL TRADE-OFFS & AI TRANSPARENCY
• "We made an intentional decision to eliminate external database servers (MSSQL) in favor of
   Python's built-in SQLite WAL mode, ensuring this runs cleanly on any reviewer's machine."
• "We used Antigravity AI for scaffolding tests, Faker data generators, and regex patterns,
   while exercising human judgment on conflict quarantine design, O(N) indexing, and zero-dependency storage."

[MINUTES 13-15] QUESTIONS & EXTENSIONS
• Address limitations: "If we had 10M+ records, we would introduce phonetic blocking (Double Metaphone)
   and distribute the stages across PySpark or Ray while maintaining our target canonical storage."
```

