# Open Problem Collector — Proof of Concept Spec

## Purpose

A Python pipeline that collects open scientific problems from multiple sources — review articles, workshop reports, and (eventually) conference video transcripts — extracts them, decomposes them into concrete sub-questions, and builds a structured, searchable database of what science doesn't know yet.

This is a **sibling project** to the Hypothesis Scanner. The scanner finds specific unvalidated predictions in computational papers ("our model predicts X"). The collector finds broader stated gaps and open questions ("it remains unknown whether Y") and decomposes them into testable components.

### How this differs from the Hypothesis Scanner

| Dimension | Hypothesis Scanner | Open Problem Collector |
|-----------|-------------------|----------------------|
| **Signal** | Specific predictions in computational papers | Stated gaps, open questions, future directions |
| **Source format** | Preprint abstracts + full text | Reviews, workshop reports, video transcripts |
| **Directness** | Prediction → experiment (1 step) | Open problem → decompose → sub-questions (2 steps) |
| **Overlap** | Narrow: "our model predicts compound X inhibits target Y" | Broad: "the mechanism of X remains poorly understood" |

---

## Proof of Concept Scope

### Phase 1: Text-Based Sources (this spec)

Two source types, chosen because they reuse ~70% of the scanner infrastructure:

**1. Review articles from preprint servers**
- bioRxiv, arXiv (same sources as scanner, different paper type)
- Reviews contain concentrated open questions — a single review can yield 5-20 stated gaps
- Filter: look for papers with "review" in title/abstract or tagged as review/meta-analysis

**2. Workshop and roadmap reports**
- NIH, NSF, DOE, NAS workshop reports and strategic plans
- These are literally curated lists of open problems, written by panels of experts
- Published as PDFs on agency websites, irregularly formatted
- Smaller volume (50-100 relevant reports/year) but extremely high signal density

**3. Conference abstract books** (stretch goal for PoC)
- Scientific societies publish abstract books as PDFs for annual meetings
- "Future directions" language in abstracts signals open problems
- ASM, ACS, ASCB, ASBMB

### Sample Run

- **Review articles**: 3 weeks of reviews from bioRxiv + arXiv (same date range as scanner sample: Jan 20 – Feb 9, 2026)
- **Workshop reports**: Manually curated seed set of ~20 recent NIH/NSF workshop reports (2024-2026)
- **Expected volume**:
  - Reviews: ~150-300 papers (reviews are ~5-8% of bioRxiv submissions)
  - Workshop reports: 20 documents (manually selected)
- **Estimated cost**: ~$5-10
- **Runtime**: ~2-3 hours

### What we're measuring

- How many distinct open problems per review article vs. per workshop report
- What % of extracted open problems decompose into concrete, specific sub-questions
- Whether the decomposition step produces specific questions or vague aspirations
- Signal quality by source: which source type produces the most useful output per dollar spent
- Duplication rate: how often the same problem appears across multiple sources

---

## Pipeline Stages

### Stage 1: Source Ingestion

#### 1a: Review Articles

**Tool**: `paperscraper` (same as scanner)

**Process**: Pull metadata from bioRxiv and arXiv, then filter for review-type papers.

Review detection heuristics:
```python
REVIEW_SIGNALS = [
    # Title-level signals (high confidence)
    r"\breview\b",
    r"\bsurvey\b",
    r"\boverview\b",
    r"\bperspective\b",
    r"\broadmap\b",
    r"\bstate of the art\b",
    r"\bstate-of-the-art\b",
    r"\bcurrent landscape\b",
    r"\brecent advances\b",
    r"\bemerging trends\b",
    r"\bopen questions\b",
    r"\bopen problems\b",
    r"\bgrand challenges\b",
    r"\bfuture directions\b",
    r"\bcritical assessment\b",
]

# bioRxiv sometimes tags papers as "review" in category metadata
# arXiv doesn't have a review tag, so rely on title/abstract matching
```

**Category filtering**: Same arXiv categories as the scanner (q-bio.*, physics.chem-ph, physics.bio-ph, cond-mat.mtrl-sci, cond-mat.soft). For bioRxiv, no category filter needed — reviews in any category are potentially useful.

**Expected yield**: ~150-300 review papers from 3 weeks across both sources.

**Cost**: $0

#### 1b: Workshop Reports

**Tool**: Manual curation + PDF download

**Process**: Workshop reports don't have a unified API. Initial approach is manual:

1. Maintain a YAML registry of known report sources:
```yaml
workshop_sources:
  - name: "NIH Workshop Reports"
    base_url: "https://www.nih.gov/research-training/medical-research-initiatives"
    scrape_strategy: manual
    notes: "Search NIH Reporter, NHLBI events page, individual IC pages"

  - name: "NSF Workshop Reports"
    base_url: "https://www.nsf.gov/publications/"
    scrape_strategy: manual
    notes: "Search NSF PAR (Public Access Repository)"

  - name: "DOE BER Workshop Reports"
    base_url: "https://science.osti.gov/ber"
    scrape_strategy: manual

  - name: "NAS Consensus Studies"
    base_url: "https://www.nationalacademies.org/our-work"
    scrape_strategy: manual
    notes: "Free PDFs available for most reports"

  - name: "Royal Society Open Questions"
    base_url: "https://royalsociety.org/journals/publishing-activities/open-questions-competition/"
    scrape_strategy: manual
    notes: "Annual competition — open questions in biology"
```

2. For the PoC, manually download ~20 recent reports covering:
   - Synthetic biology / bioengineering
   - Antimicrobial resistance
   - AI for science / computational biology
   - Materials science / catalysis
   - Genomics / gene editing

3. Extract text from PDFs using `pymupdf` or `pdfplumber`.

**Output**: Normalized format:
```json
{
  "source_id": "nih-workshop-amr-2025",
  "source_type": "workshop_report",
  "title": "...",
  "authors": ["..."],
  "organization": "NIH/NIAID",
  "date_published": "2025-06-15",
  "url": "https://...",
  "sections": {
    "executive_summary": "...",
    "recommendations": "...",
    "open_questions": "...",
    "full_text": "..."
  }
}
```

**Cost**: $0 (manual labor aside)

#### 1c: Conference Abstract Books

**Tool**: PDF download + text extraction

**Process**: Download abstract books from society meeting websites. These are typically large PDFs (100-500 pages) with one abstract per entry.

Target meetings (PoC):
- ASM Microbe (American Society for Microbiology)
- ACS Spring/Fall (American Chemical Society)
- ASBMB Annual Meeting

Parse individual abstracts using heuristic section detection (abstract number, title, author block, body text pattern).

**Expected yield**: ~50-200 abstracts per meeting that contain "future directions" language.

**Cost**: $0

---

### Stage 2: Open Problem Signal Filter

**Input**: Text from all sources (review sections, workshop report text, abstracts)

**Process**: Scan for language indicating open problems, knowledge gaps, and unresolved questions.

**Category A — Explicit open questions** (high confidence):
```
"it remains unknown"
"it is not yet understood"
"it is unclear whether"
"remains to be determined"
"remains to be elucidated"
"remains poorly understood"
"remains an open question"
"an unresolved question"
"a major challenge is"
"a key challenge"
"a critical gap"
"knowledge gap"
"significant gap in our understanding"
"poorly characterized"
"has not been systematically studied"
"no systematic study"
"future work should"
"future studies should"
"future research should"
"future experiments should"
"warrants further investigation"
"deserves further study"
"important open problem"
"outstanding question"
```

**Category B — Future directions / recommendations** (medium confidence, contextual):
```
"we recommend that"
"we propose that future"
"a promising avenue"
"a promising direction"
"an exciting opportunity"
"would benefit from"
"could be addressed by"
"should be investigated"
"needs to be tested"
"would be valuable to"
"has yet to be"
"largely unexplored"
"underexplored"
"understudied"
"limited data"
"lack of experimental evidence"
```

**Category C — Workshop-specific language** (for workshop reports):
```
"priority research area"
"research priority"
"recommended research"
"recommended experiment"
"research opportunity"
"critical need"
"should be prioritized"
"high-priority"
"bottleneck"
"barrier to progress"
"enabling technology needed"
```

**Negative filters** — skip passages about:
```
"funding mechanism"
"workforce development"
"training program"
"data sharing policy"
"ethical considerations"
"regulatory framework"
```
(These are valid concerns but not scientific questions.)

**Output**: Filtered passages with:
- Source metadata
- `signal_category`: "A", "B", or "C"
- `matched_phrases`: list of phrases that triggered
- `context_text`: the paragraph or passage containing the signal (not just the sentence)

**Expected yield**: Reviews average ~8-15 signal hits per paper. Workshop reports average ~20-40. Total: ~2,000-5,000 passages from all sources.

**Cost**: $0

---

### Stage 3: LLM Extraction and Decomposition

**Model**: Claude Sonnet (claude-sonnet-4-5-20250929)

Using Sonnet (not Haiku) because the extraction is more complex than a binary classification. We need the model to identify the problem, assess its scope, and decompose it into concrete sub-questions.

**Input**: Filtered passages from Stage 2, batched per source document

**Prompt**:
```
You are extracting open scientific problems from a document.

Given the following text passages (from a review article or workshop report),
extract each distinct open problem, knowledge gap, or unresolved question.

For each problem, provide:

1. The open problem or question as stated
2. The scientific domain (e.g., "protein engineering", "antimicrobial resistance",
   "gene regulation", "catalysis", "genomics")
3. The scope: "narrow" (a single specific question), "medium" (decomposes into
   2-5 sub-questions), or "broad" (requires a research program)
4. If the scope is medium or narrow, decompose into specific sub-questions that
   could each be answered by a single study or experiment
5. For each sub-question, describe what kind of evidence or experiment would
   answer it
6. What disciplines or expertise areas are relevant

Ignore problems that are purely:
- Computational/algorithmic ("better models are needed")
- Policy/regulatory ("guidelines should be updated")
- Infrastructure ("more sequencing capacity is needed")
- Too broad to decompose ("the field needs a paradigm shift")

Respond with JSON only:
{
  "source_id": "...",
  "problems": [
    {
      "problem_statement": "the stated open problem",
      "domain": "scientific domain",
      "subdomain": "more specific area",
      "scope": "narrow|medium|broad",
      "sub_questions": [
        {
          "question": "specific sub-question",
          "evidence_needed": "what kind of study or experiment would answer this",
          "disciplines": ["relevant", "fields"],
          "estimated_complexity": "simple|medium|complex"
        }
      ],
      "original_text": "quote from source supporting this extraction",
      "related_keywords": ["key", "terms", "for", "searching"],
      "notes": "any caveats"
    }
  ],
  "meta": {
    "total_problems_found": 5,
    "decomposable_count": 3,
    "non_decomposable_reasons": ["too broad", "purely computational"]
  }
}
```

**Batching strategy**: For review articles, send the full discussion/conclusion section (or the entire paper if section detection fails). For workshop reports, send the recommendations/open questions sections. Cap at ~8K tokens input per call to control costs.

**Output**: Structured JSON per source document with extracted open problems and sub-questions.

**Expected yield**:
- ~150-300 review papers × ~3-5 decomposable problems each = ~500-1,500 sub-questions
- ~20 workshop reports × ~10-15 decomposable problems each = ~200-300 sub-questions
- Total: ~700-1,800 sub-questions

**Cost**:
- Review articles: ~250 papers × (4,000 input + 800 output tokens)
  - Input: 1M tokens × $3/M = $3.00
  - Output: 200K tokens × $15/M = $3.00
  - Subtotal: ~$6.00
- Workshop reports: ~20 reports × (6,000 input + 1,200 output tokens)
  - Input: 120K tokens × $3/M = $0.36
  - Output: 24K tokens × $15/M = $0.36
  - Subtotal: ~$0.72
- **Total: ~$6.72**

---

### Stage 4: Full-Text Download (for reviews only)

Same as scanner Stage 4. Download PDFs of review articles that passed the signal filter in Stage 2, extract text, attempt section detection.

Workshop reports are already downloaded manually in Stage 1b.

**Expected volume**: ~150-300 review articles.

**Cost**: $0

**Notes**: Many reviews on bioRxiv are longer than primary research articles (20-40 pages). Text extraction from review PDFs is generally cleaner than from primary papers because reviews have fewer figures and equations.

---

### Stage 5: Deduplication and Clustering

The same open problem gets mentioned in multiple reviews and workshop reports. A clustering step prevents the database from being full of near-duplicate entries.

**Process**:
1. **Exact dedup**: Hash-based on normalized problem statement text
2. **Semantic clustering**: TF-IDF + cosine similarity for the PoC (simple, no GPU needed). Optionally upgrade to sentence-transformer embeddings + HDBSCAN later.
3. **Merge**: For each cluster, keep the best-stated version and track all source documents

**Output**: Deduplicated list of open problems, each with:
- Canonical problem statement (best version from cluster)
- All source documents that mention it
- Mention count (proxy for community consensus on importance)
- All sub-questions from all sources (merged)
- Domain and subdomain tags

**Cost**: $0 (local computation)

---

### Stage 6: Output

**Database schema**:

```sql
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    source_type TEXT,  -- "review_article", "workshop_report", "conference_abstract"
    title TEXT,
    authors TEXT,  -- JSON array
    organization TEXT,  -- for workshop reports
    date_published TEXT,
    url TEXT,
    server TEXT,  -- "biorxiv", "arxiv", "nih", "nsf", etc.
    category TEXT,
    signal_hits INTEGER,
    processed_at TEXT
);

CREATE TABLE open_problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_statement TEXT,
    domain TEXT,
    subdomain TEXT,
    scope TEXT,  -- "narrow", "medium", "broad"
    mention_count INTEGER,
    source_ids TEXT,  -- JSON array of source IDs
    related_keywords TEXT,  -- JSON array
    cluster_id TEXT,
    created_at TEXT
);

CREATE TABLE sub_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER REFERENCES open_problems(id),
    question TEXT,
    evidence_needed TEXT,
    disciplines TEXT,  -- JSON array
    estimated_complexity TEXT,
    source_id TEXT REFERENCES sources(id)
);

CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT,
    source_types TEXT,  -- JSON array
    date_range_start TEXT,
    date_range_end TEXT,
    sources_ingested INTEGER,
    signal_passages INTEGER,
    problems_extracted INTEGER,
    problems_after_dedup INTEGER,
    sub_questions_extracted INTEGER,
    total_cost REAL,
    config TEXT
);
```

**JSON feed**:

```json
{
  "generated_at": "2026-02-09T...",
  "pipeline_run_id": 1,
  "summary": {
    "sources_scanned": 270,
    "signal_passages": 3200,
    "problems_extracted": 850,
    "problems_after_dedup": 450,
    "sub_questions": 1100
  },
  "problems": [
    {
      "problem_statement": "The substrate specificity determinants of serine integrases remain poorly characterized",
      "domain": "protein engineering",
      "subdomain": "site-specific recombination",
      "scope": "medium",
      "mention_count": 3,
      "sources": [
        {"id": "10.1101/...", "type": "review_article", "title": "..."},
        {"id": "nih-workshop-synbio-2025", "type": "workshop_report", "title": "..."}
      ],
      "sub_questions": [
        {
          "question": "Which residues in the zinc ribbon domain determine att site preference?",
          "evidence_needed": "Mutagenesis study with integration assays across a panel of att site variants",
          "disciplines": ["protein biochemistry", "molecular biology"],
          "estimated_complexity": "medium"
        },
        {
          "question": "Do different integrase orthologs show distinct att site promiscuity profiles?",
          "evidence_needed": "Comparative in vitro integration assay with purified orthologs",
          "disciplines": ["comparative biochemistry"],
          "estimated_complexity": "medium"
        }
      ],
      "related_keywords": ["serine integrase", "Bxb1", "att site", "recombination specificity"]
    }
  ]
}
```

---

## Project Structure

```
open-problem-collector/
├── README.md
├── requirements.txt
├── config.yaml
├── .env.example
│
├── pipeline/
│   ├── __init__.py
│   ├── ingest_reviews.py        # Stage 1a: review article ingestion
│   ├── ingest_workshops.py      # Stage 1b: workshop report ingestion
│   ├── ingest_abstracts.py      # Stage 1c: conference abstract ingestion (stretch)
│   ├── signal_filter.py         # Stage 2: open problem signal detection
│   ├── problem_extractor.py     # Stage 3: LLM extraction + decomposition
│   ├── fulltext.py              # Stage 4: PDF download + text extraction
│   ├── dedup.py                 # Stage 5: deduplication + clustering
│   └── output.py                # Stage 6: SQLite + JSON export
│
├── config/
│   ├── signal_phrases.yaml      # Open problem signal phrases
│   └── workshop_registry.yaml   # Known workshop report sources + URLs
│
├── run_poc.py                   # Orchestrator for PoC run
├── run_pipeline.py              # Orchestrator for full/incremental runs
│
├── data/
│   ├── workshops/               # Manually downloaded workshop report PDFs
│   ├── reviews/                 # Downloaded review PDFs
│   ├── abstracts/               # Conference abstract book PDFs
│   ├── results/
│   │   ├── collector.db         # SQLite database
│   │   └── problems_feed.json   # JSON feed
│   └── logs/
│
└── tests/
    ├── test_signal_filter.py
    ├── test_review_detection.py
    ├── test_dedup.py
    └── fixtures/
```

---

## Dependencies

```
paperscraper>=0.3.5              # Review article ingestion (shared with scanner)
anthropic>=0.40.0
pymupdf>=1.24.0                  # PDF text extraction
pdfplumber>=0.11.0               # Alternative PDF extraction (better for tables)
pyyaml>=6.0
python-dotenv>=1.0
scikit-learn>=1.5.0              # TF-IDF + cosine similarity for dedup
```

Optional (for ML-based clustering):
```
sentence-transformers>=3.0.0     # Semantic embeddings for problem clustering
hdbscan>=0.8.0                   # Density-based clustering
```

---

## Configuration

```yaml
sources:
  reviews:
    enabled: true
    servers: ["biorxiv", "arxiv"]
    arxiv_categories:
      - "q-bio.BM"
      - "q-bio.GN"
      - "q-bio.MN"
      - "q-bio.QM"
      - "physics.chem-ph"
      - "physics.bio-ph"
  workshops:
    enabled: true
    registry: "config/workshop_registry.yaml"
  conference_abstracts:
    enabled: false  # stretch goal for PoC

llm:
  extractor_model: "claude-sonnet-4-5-20250929"
  max_concurrent_requests: 5
  retry_attempts: 3
  max_input_tokens_per_call: 8000

dedup:
  method: "tfidf"  # "tfidf" or "embedding"
  similarity_threshold: 0.85

budget:
  max_sonnet_calls: 500
  spending_alert_threshold: 15.00
```

---

## Cost Summary (PoC Run)

| Stage | Description | Cost |
|-------|-------------|------|
| 1a | Review article ingestion (paperscraper APIs) | $0 |
| 1b | Workshop report ingestion (manual PDF download) | $0 |
| 2 | Open problem signal filter | $0 |
| 3 | LLM extraction + decomposition (~270 docs, Sonnet) | ~$6.72 |
| 4 | Full-text download (~250 review PDFs) | $0 |
| 5 | Deduplication + clustering | $0 |
| 6 | Output generation | $0 |
| **Total** | | **~$6.72** |

---

## Success Criteria for PoC

1. **Signal quality**: Do the open problem signal phrases catch genuine knowledge gaps, or do they also catch filler language? Target: >60% of flagged passages contain a real open problem.

2. **Extraction quality**: Are the extracted problems specific enough to decompose? Target: >50% of problems yield at least one sub-question with a concrete description of what evidence would answer it.

3. **Decomposition utility**: Are the sub-questions specific enough that someone reading them would know what to do? Or are they restatements of the parent problem? Target: >60% of sub-questions are meaningfully more specific than their parent problem.

4. **Source comparison**: Do workshop reports outperform reviews on a per-document basis? (Expected: yes, by a large margin per document, but reviews win on volume.)

5. **Deduplication effectiveness**: What's the duplication rate? If 50% of problems are near-duplicates across sources, the clustering step is essential. If <10%, it's overkill for now.

---

## Phase 2: Conference Video Transcripts (Future Expansion)

### Why conference talks

Researchers are most candid about open problems in talks — they say things in a seminar that they'd never write in a paper. The Q&A portions are especially rich: audience questions often surface the community's real concerns and the speaker's honest assessment of limitations.

### Sources

**High-signal YouTube channels with scientific talk recordings:**

| Channel / Source | Content Type | Volume | Transcript Availability |
|-----------------|-------------|--------|------------------------|
| iBiology | Research seminars by leading biologists | 600+ videos | YouTube auto-captions |
| HHMI / Janelia | Research talks, colloquia | Hundreds | YouTube auto-captions |
| Keystone Symposia | Conference talks (some public) | Varies | YouTube auto-captions |
| ASM | Meeting recordings | Varies | YouTube auto-captions |
| ACS | Webinars, meeting highlights | Varies | YouTube auto-captions |
| NIH VideoCast | Seminars, workshops, lectures | Thousands | Often has manual captions |
| Cold Spring Harbor Laboratory | Meeting talks (some public) | Limited | YouTube auto-captions |
| Broad Institute | Research talks | Hundreds | YouTube auto-captions |
| EMBL | Seminars | Hundreds | YouTube auto-captions |

### Pipeline for video sources

```
┌──────────────────────────────────────────────────────────┐
│ Stage V1: Video Discovery                                │
│                                                          │
│ - YouTube Data API v3 to list videos from target channels│
│ - Filter by: date range, title keywords, duration        │
│   (skip <5 min clips, keep 20-60 min talks)              │
│ - youtube-channel-transcript-api for batch channel pulls │
│                                                          │
│ Cost: Free (YouTube API quota)                           │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Stage V2: Transcript Acquisition                         │
│                                                          │
│ Option A: youtube-transcript-api (preferred)             │
│   - Pulls existing auto-generated or manual captions     │
│   - No compute cost, no audio download needed            │
│   - Quality: variable. Auto-captions are ~85-95%         │
│     accurate for clear English scientific speech         │
│   - Falls back to Option B if no captions available      │
│                                                          │
│ Option B: Whisper transcription (fallback)               │
│   - Download audio with yt-dlp                           │
│   - Transcribe with OpenAI Whisper API ($0.006/min)      │
│     or local Whisper model (free but needs GPU)          │
│   - Higher accuracy than auto-captions                   │
│   - 1-hour talk = ~$0.36 via API                         │
│                                                          │
│ Cost: $0 (Option A) or ~$0.36/talk (Option B)            │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Stage V3: Transcript Segmentation                        │
│                                                          │
│ Scientific talks have a predictable structure:           │
│   - Introduction (background, motivation)                │
│   - Methods/Results (data presentation)                  │
│   - Discussion/Conclusion (interpretation)               │
│   - Future Directions (open problems — HIGH SIGNAL)      │
│   - Q&A (audience questions — HIGHEST SIGNAL)            │
│                                                          │
│ Segment detection via:                                   │
│   - Timestamp-based heuristics (Q&A usually last 20%)    │
│   - Text signals: "in conclusion", "future work",        │
│     "questions?", "thank you", audience interruptions    │
│   - LLM-based segmentation (Haiku, cheap)                │
│                                                          │
│ Cost: ~$0.05/talk (Haiku segmentation)                   │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Stage V4: Open Problem Extraction                        │
│                                                          │
│ Same LLM extraction as Stage 3 of the main pipeline,     │
│ but applied to transcript segments.                      │
│                                                          │
│ Key difference: transcript text is messier than papers.  │
│ The prompt needs to handle:                              │
│   - Disfluencies ("um", "you know", "sort of")           │
│   - Implicit questions ("we don't really know if...")     │
│   - Audience Q&A format (question → answer pairs)        │
│   - Speaker hedging vs. genuine uncertainty               │
│                                                          │
│ Focus extraction on:                                     │
│   - Discussion/conclusion segments                       │
│   - Q&A segments (especially unanswered questions)       │
│   - Any segment containing open problem signal phrases   │
│                                                          │
│ Cost: ~$0.15/talk (Sonnet on selected segments)          │
└──────────────────────────────────────────────────────────┘
```

### Estimated cost at scale (video pipeline)

| Scale | Videos | Transcript cost | Extraction cost | Total |
|-------|--------|----------------|----------------|-------|
| PoC (1 channel) | ~50 talks | $0 (auto-captions) | ~$7.50 | ~$7.50 |
| Pilot (5 channels) | ~300 talks | $0-$100 | ~$45 | ~$50-$150 |
| Full (all sources) | ~2,000 talks | $0-$700 | ~$300 | ~$300-$1,000 |

### Technical considerations for video pipeline

- **youtube-transcript-api** is the cheapest path — it pulls existing captions without downloading audio. For scientific talks on institutional channels, auto-captions are usually decent because the audio is clean and the speaker is using a microphone.

- **Whisper fallback** is only needed for: videos without captions (rare on institutional channels), videos where auto-captions are unusable (heavy accents, poor audio), or when you need timestamps for segment detection.

- **Speaker diarization** matters for Q&A — you need to separate the speaker's answer from the questioner's question. Whisper doesn't do this natively. `pyannote-audio` or Gladia's API can add it, but adds complexity and cost. For the PoC, just treat Q&A as a single block.

- **Rate limiting**: YouTube's transcript API is undocumented and may block rapid requests. Add delays and respect de facto rate limits. The YouTube Data API v3 has explicit quotas (10,000 units/day by default).

---

## Phase 3: Additional Future Expansions

### 3a: Open Peer Review Platforms

- **eLife**: Publishes editor assessments and reviewer comments openly. Reviewer comments frequently flag limitations and open questions. Accessible via eLife API.
- **F1000Research**: All peer review is open. Reviewer reports often state explicitly what additional experiments are needed.
- **Review Commons**: Preprint reviews, publicly available.

These are extremely high signal — reviewers are literally paid to identify gaps — and the text is structured and accessible via APIs.

### 3b: Twitter/Bluesky Science Threads

- Researchers post "hot takes" and open questions informally
- Tools: `snscrape`, Bluesky API
- Extremely high noise, but catches very current thinking
- Would need aggressive filtering (only academic accounts, only threads with >N engagement, keyword matching)
- Probably not worth building until the text-based pipeline is validated

### 3c: Preprint Comment Threads

- bioRxiv and medRxiv support public comments
- Low volume (most papers get 0-2 comments) but the comments that exist are often substantive
- bioRxiv's comment API (if it exists) or scraping

### 3d: Grant Abstracts

- NIH Reporter provides searchable database of funded grants
- Specific Aims sections describe exactly what questions are being asked
- This tells you what's *being worked on*, not what's *open* — but the gap between funded and unfunded questions is itself interesting
- NIH Reporter API is free and well-documented

---

## Open Questions

- **Review detection accuracy**: The title-based heuristics for identifying review articles will miss reviews with creative titles and may catch some primary research papers that use "review" casually. Need to evaluate and potentially add an LLM classification step.

- **Workshop report format variability**: NIH, NSF, and NAS reports all use different formats. The text extraction and section detection will need per-source tuning. Some reports bury their recommendations in appendices.

- **Decomposition quality**: The key question is whether "remains poorly understood" can be reliably decomposed into concrete sub-questions. If the LLM's sub-questions are consistently too vague ("further study is needed"), the decomposition step needs a different prompt strategy — possibly a two-stage approach where the first pass identifies the problem and the second pass specifically designs sub-questions.

- **Shared infrastructure with scanner**: How tightly coupled should these pipelines be? Options range from a monorepo with shared modules to two independent projects. The PoC runs independently; if both validate, refactor into shared infrastructure.

- **Community curation**: Should high-quality open problems be surfaced for community discussion or voting? A curated "what does science not know?" database has value independent of any downstream use.

- **Author engagement**: For problems from review articles, the review author has already done the synthesis work and may be interested in seeing their identified gaps addressed. Different outreach angle than the scanner.

- **Temporal tracking**: The same open problem may persist for years or get resolved. Tracking when a problem *stops* appearing in reviews is a signal that it's been answered. This requires longitudinal runs and cross-referencing with new literature.
