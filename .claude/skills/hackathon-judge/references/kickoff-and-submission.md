# Kickoff Deck, Judging Criteria & Submission

Source: `docs/official-docs/Datathon_2026_Kickoff.pdf` (24 slides, kickoff on **September 25, 2026**). Text below is what the slides say; the "Timeline" slide (p.6) is an image with no extractable text, so **the exact submission deadline is not in these documents** — say so rather than guessing, and point the team to the organizers' Slack.

## Framing (slides 8–11)

- "Join 750+ engineers in a 2-week challenge"; ~180 teams expected. Participant briefing calls it a **10-Day Sprint**.
- Tagline: **"Don't build a chatbot, build a customer-service system."**
- **Task selection — one focused banking workflow:** 1. Account / Payment Inquiries, 2. Card Support, 3. Transaction Disputes, 4. Credit-Product Info & Eligibility.
- **End-to-end working prototype:** "Build a fully functional production-ready prototype capable of handling complex user interactions beyond a surface-level demo."
- **Multilingual support required:** "Demonstrate robust customer service interactions in both Spanish and Portuguese to serve LATAM banking needs."
- System loop: **Understand → Decide → Act → Verify → Escalate.**
- Key idea: **"AI should not be autonomous just because it can be."**

### Minimum requirements (slide 11)
- Maintain conversational context
- Clarify ambiguous requests
- Retrieve trusted information
- Use tools securely
- Execute appropriate workflows
- Verify that actions actually happened
- Know when NOT to act
- Hand off to a human when needed

### The three required behaviors (slide 11)
| Case | Expected behavior | Slide description |
|---|---|---|
| Normal Case | Automated Resolution | "Handles policy-compliant automated resolution, verified account queries, and authorized self-service transactions seamlessly" |
| Ambiguous / Unsupported | Clarification or Abstention | "Asks clarifying questions or practices safe policy abstention when handling missing parameters or unsupported banking requests" |
| Human-Required | Safe Escalation | "Executes a structured handoff to human representatives, transferring verified facts and open questions **without dumping raw transcripts**" |

## Evaluation & rigor (slides 12–13)

Flow: **Baseline → Proposed System → Held-out Evaluation**

Technical rigor:
- Data Quality & Contracts: strict input schema enforcement
- Reproducible Preparation: deterministic pipeline execution
- Valid Labels: grounded relevance judgments & ground truth
- Leakage Prevention: strict train/eval set isolation
- Appropriate Split: realistic held-out test distributions
- Learned Component: benchmark against a baseline model

Key metrics to measure: **Safe Automated Resolution, Unsafe Outcomes, Cost Efficiency.**

Technical deliverables (six headings, one line each):
| Pillar | Deliverable |
|---|---|
| Data-backed baseline | Justify workflow selection using reproducible logs |
| Grounded AI core | Ground all responses in verified records |
| Controlled automation | Enforce action permissions besides model prompts |
| Data & ML discipline | Repeatable pipelines with strict schema contracts |
| Measured failures | Stress-test held-out cases against injection |
| Route to operation | Deterministic setup with audit execution logs |

## Multi-disciplinary evaluation — "No single skill is mandatory" (slide 14)

| Discipline | Suggested tasks |
|---|---|
| Artificial Intelligence | Production backend and structured JSON handoffs |
| Machine Learning | LLM/RAG orchestration and prompt injection defense |
| Data Engineering | Strong ETL/ELT pipeline and customer record isolation |
| Data Analysis | Demand patterns, and cost-per-resolution ROI |

## "Think beyond the hackathon — make your result a real service" (slide 15)

- **Observability:** tracing, execution records, monitoring
- **Reliability:** bounded retries, safe fallback, tool failure handling
- **Security:** authentication, access controls, data retention
- **Reproducibility:** setup instructions, versioning, repeatable evaluation
- "And be honest about what's missing": capacity limits, data limitations, language coverage, deployment work, remaining risks.
- **Final takeaway:** "Build something that works, prove that it works, and know when it should not act. And show us what it would take to make it real."

## Submission (slide 18)

For a submission to be considered successful:
1. Link to a **public GitHub repository** named `factored-hackathon-2026-[your team's name]`
2. Link to where the tool is **deployed**
3. A **4–6 slide** presentation with details on the tool
4. A **short, mandatory video pitch** demonstrating the working solution and explaining core architectural decisions

Send everything to **hackathon.admin@factored.ai**. "Submit your tool no matter what!!!"

Tooling: free to use any language/tools; suggested resources: Snowflake, AWS, Databricks, Microsoft Azure (slide 19). Mentors available in Slack `#technical-help`.

## Evaluation criteria (slide 20)

"**First and foremost our solution should work**", then:
- **AI Engineering:** backend, frontend and deployment
- **Overall project rationale and documentation**
- **Data Engineering:** how you deal with extraction and transformation of the data
- **Machine Learning:** model selection, optimization, implementation and tracking
- **Data Analytics:** data quality and providing relevant insights from the solution

No weights or point values are published for these criteria.

## Prizes (slide 23)
1st US$6,000 + interview with Factored engineering & talent team · 2nd US$3,000 · 3rd US$1,000.
