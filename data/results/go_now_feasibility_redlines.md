# Go-Now Feasibility Redline Review (Step 1)

Date: 2026-02-11
Scope: `opc-go-001`, `opc-go-002` from `go_now_lab_packets.json`
Method: feasibility criteria + pre-RFQ execution review (study design, throughput, QC, timeline, permitting, and deliverable clarity)

## Executive Outcome

Both experiments remain **GO with redlines**, but each requires scope tightening before RFQ dispatch.

- `opc-go-001`: Go if staged as a two-wave campaign with explicit event yield gates.
- `opc-go-002`: Go if the first wave narrows to fewer loci/configurations and defines an insertion verification plan up front.

## Redlines by Experiment

### `opc-go-001` Transformation-Competence Editing

1. **[High] Candidate locus scope is too broad for first pass**
- Current: 8-12 loci with 3-4 multiplex constructs.
- Redline: Wave 1 should use 4-6 loci and max 2 multiplex constructs plus one non-targeting control.
- Why: reduces construct/regeneration failure coupling and improves attribution.

2. **[High] Success criterion does not enforce absolute minimum event yield**
- Current: relative lift targets (>=2x) but no absolute event floor.
- Redline: add hard minimum: at least 8 independent PCR-positive events per construct-genotype arm.

3. **[Medium] Replication/unit-of-analysis ambiguity**
- Current: embryo counts are specified, but primary statistical unit is not explicit.
- Redline: define independent event as analysis unit; embryos are denominator for transformation efficiency.

4. **[Medium] Molecular QC package is underspecified for edited loci confirmation**
- Current: amplicon sequencing + PCR/qPCR copy checks.
- Redline: require per-event edit genotype table (target locus, zygosity state if applicable, on-target edit class, transgene status).

5. **[Medium] Regeneration penalty criterion needs denominator definition**
- Current: "No major regeneration penalty (>25% drop)".
- Redline: specify compared against matched genotype + non-targeting control under same batch.

6. **[Medium] Permit/logistics assumptions not in handoff**
- Current: permit risk noted globally.
- Redline: require bidder to state who handles USDA/APHIS interstate movement paperwork and chain-of-custody documentation.

### `opc-go-002` Safe-Harbor + Insulator Validation

1. **[High] Initial design matrix is too large for a first external run**
- Current: 3 loci x (no-insulator + 2 insulators) + random integration arm.
- Redline: Wave 1 should be 2 loci x (no-insulator + 1 insulator) + random integration comparator.

2. **[High] Targeted insertion confirmation requirements need to be explicit before quote**
- Current: insertion fidelity/copy number listed as readouts.
- Redline: require junction-PCR (5' and 3'), copy number assay, and locus confirmation for all candidate events before expression assay enrollment.

3. **[Medium] Event-count floor per arm is absent**
- Current: target >=12 events per condition.
- Redline: set quote commitments for expected delivered independent events and explicit attrition assumptions.

4. **[Medium] Expression stability endpoint needs predefined tissue/timepoint panel**
- Current: tissues/generation mentioned broadly.
- Redline: define minimum panel (e.g., callus + leaf in T0; at least one tissue in T1) before execution.

5. **[Medium] Comparator statistical threshold lacks test specification**
- Current: CV reduction and rank correlation targets given.
- Redline: require bidder to return raw data table and pre-agreed analysis script-ready schema (line-level ratiometric values, batch IDs, tissue IDs).

6. **[Low] Fitness neutrality endpoint needs operationalization**
- Current: listed as secondary.
- Redline: specify at least one growth metric and acceptable delta vs matched control.

## Must-Close Questions for Lab Feasibility Call

1. What is your expected independent-event yield per construct for sorghum and/or switchgrass under our target genotypes?
2. Which steps are fixed-price vs variable (construct complexity, long T-DNA, targeted insertion failure retries)?
3. What is your attrition model from infected explants to PCR-positive independent events to assay-ready lines?
4. Can you commit to delivery of event-level QC tables (junction PCR, copy number, edit genotype) as a contractual deliverable?
5. Which permits and shipping constraints are your responsibility versus ours?
6. What is the earliest realistic first-data date (not just first-plantlet date)?

## Go/No-Go Gate for RFQ Award

Proceed only if at least one bidder can commit to all of the following:

1. Event-yield commitment consistent with minimum independent-event floors.
2. QC deliverables at event level (not summary-only).
3. Timeline to first analyzable data within 8 months for `opc-go-001` and 10 months for `opc-go-002`.
4. Transparent cost model with explicit assumptions and change-order triggers.
