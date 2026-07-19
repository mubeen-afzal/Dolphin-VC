Track 2 Implementation Audit
Verdict
Your instinct is right: this is not sufficient for the full Hack-Nation Track 2 challenge yet. It is a solid, unusually well-engineered backend foundation, but it does not implement the challenge’s core winning loop: discover founders → resolve/enrich them → screen them with real evidence → diligence contradictions → produce an investor-ready decision in a usable interface.
I verified Docker Compose configuration statically. The local unit test command could not run because pytest is not installed in this environment, so test success is unconfirmed.
Brief area	Status
Inbound application + 24-hour clock	Partial
Outbound founder discovery	Not end-to-end
Persistent Founder Score	Model exists; not fed by ingestion
Three independent axes	Present; overly shallow
Claim-level trust/evidence	Present; not externally verified
Investment memo and human decision	Partial
Investor-grade UX	Missing
Self-correction / sourcing graph	Mostly placeholder

What Is Correct
The architecture correctly separates Founder Score from opportunity scores and does not average the three screening axes.
Inbound PDF/PPTX upload, source locators, claim persistence, SLA timestamps, human decision audit, tenant isolation, and error handling are real foundations.
The code visibly marks missing memo data rather than inventing it, which matches the brief well.
The seed demonstrates the desired data model, but it manually creates the founder, scores, opportunity, claim, and memo rather than proving the product pipeline creates them.
Critical Gaps
Outbound sourcing stops at raw signals. Harvesting inserts Signal records but never consumes connector identity hints, resolves people/companies, creates Founder Score events, creates outbound opportunities, or starts screening. The most important track requirement is therefore disconnected. See [pipeline.py (line 58)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/pipeline.py:58) and [github.py (line 24)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/connectors/github.py:24).

“Memory” is only a schema. KBChunk, ChannelEdge, and Outreach models exist, but there is no application code creating those records. The channel graph always returns no edges, and the outreach endpoint can only approve/send an already-existing record. See [operations.py (line 27)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/routers/operations.py:27).

Inbound applicants do not become founders. Submitting a deck creates a stub company and opportunity, but not a Person, founder affiliation, or founder-score event. As a result, the inbound Founder axis defaults to a generic 50 with 0.20 confidence, making a genuine high-confidence “invest” recommendation effectively unreachable. See [applications.py (line 72)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/applications.py:72) and [pipeline.py (line 306)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/pipeline.py:306).

The intelligence layer is a heuristic, not investor reasoning. Claim extraction covers only ARR, customer count, TAM, and growth-rate regexes; product is simply the first sufficiently long deck line. The three axes are then mostly claim counts, and Market is always neutral. See [extraction.py (line 22)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/extraction.py:22) and [pipeline.py (line 327)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/pipeline.py:327).

Trust is designed but not exercised. The trust formula supports corroboration and contradictions, but the pipeline assigns every extracted claim one self-reported deck source. It performs no external verification or contradiction detection. The LLM gateway also has no callers. See [trust.py (line 40)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/score/trust.py:40).

The thesis is only partly enforced. Sectors, stage, geography, and must-haves are considered; check size, ownership target, risk appetite, configured weights, and deal breakers are stored but unused. See [thesis.py (line 11)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/backend/app/services/score/thesis.py:11).

No frontend exists. The repository explicitly ships only a backend API. That fails the brief’s 15% “Notion-level approachable, Bloomberg-level analytical” UX criterion. See [README.md (line 117)](/Users/zeeshanali/Documents/Hackathons/Hack-Nation/Dolphin-VC/README.md:117).

Scope-Completion Plan
Build one unified ingestion service that turns inbound decks and outbound signals into canonical person/company records, deduplicates them, stores source evidence, appends founder-score events, and creates/updates an opportunity.

Split the generic job handler into genuine source, screen, diligence, and decision stages. A website-only application must actually be fetched and analyzed; it currently only stores the URL.

Replace count-based scoring with evidence-backed drivers for each independent axis, including a cold-start workflow based on work samples and structured founder input. Keep missing data as uncertainty rather than a negative signal.

Add claim verification: corroborate or contradict deck claims with at least two independent sources, display freshness/confidence, and produce explicit next-diligence questions.

Apply every configured thesis field, and make natural-language search operate over founder evidence and opportunity data rather than fixed aliases and keyword matching.

Build the demo frontend: investor dashboard, discovered-founder queue, candidate dossier, evidence/contradiction panel, three-axis trend view, and decision-ready memo.

Keep the demo controlled: 8–12 curated candidates, one inbound founder, one cold-start founder, one contradiction case, and several outbound signals. This will demonstrate the full loop far better than attempting broad live scraping.

Add acceptance tests for outbound signal-to-opportunity conversion, identity deduplication, cold-start handling, contradiction detection, thesis enforcement, evidence-backed natural-language search, and the final 24-hour decision flow.

Bottom line: retain this backend, but treat it as the foundation—not the finished hackathon submission. The highest-priority work is outbound-to-founder resolution plus a polished investor UI; without those, judges will see a backend/API prototype rather than the VC Brain described in the brief.