"""保存迭代版新增提示词；v1.1只替换规划目标与结构，不更改Scout、Writer或Critic提示词。"""

CONSTRAINT_PLANNING = """Original question:
{query}

Plan a factual investigation to answer this exact question, not an industry report.
Identify the requested answer type, then list every explicit constraint faithfully.
Do not insert a disease, year, location, person or event as a confirmed fact unless the question states it.
Preserve uncertainty and ambiguous wording. Candidate identities are unverified hypotheses, not evidence.
Create exactly THREE subquestions. Put the most distinctive constraint first, then connect candidate identity
to the remaining clues, and finally verify all constraints and the exact attribute requested by the question.
For EACH subquestion provide exactly TWO concrete ENGLISH keyword queries suitable for the English corpus.
Use actual distinctive nouns and dates from the question. Never use placeholders such as [Actor Name],
[Paper Title] or <candidate>. If identity is unknown, use the descriptive clues instead.
If a plausible candidate can be named, put it in hypotheses with status unverified, and include
candidate-name verification queries in the last subquestion. Otherwise leave hypotheses empty.
Do not add market size, competitors, policy landscape or future trends unless explicitly requested.
No benchmark answers or annotations are available to you. Output only a JSON object:
{{
  "answer_type": "requested kind of answer",
  "constraints": ["every explicit constraint, separately"],
  "outline": [
    {{"id":"sec_1","title":"Most distinctive clue","description":"Question to resolve", "section_type":"mixed", "requires_data":false,"requires_chart":false,"search_queries":["English keyword query one","English keyword query two"]}},
    {{"id":"sec_2","title":"Candidate identification","description":"Question to resolve", "section_type":"mixed", "requires_data":false,"requires_chart":false,"search_queries":["English keyword query one","English keyword query two"]}},
    {{"id":"sec_3","title":"Constraint and answer verification","description":"Question to resolve", "section_type":"mixed", "requires_data":false,"requires_chart":false,"search_queries":["English keyword query one","English keyword query two"]}}
  ],
  "research_questions": ["subquestion one","subquestion two","subquestion three"],
  "key_entities": [],
  "hypotheses": []
}}
Each hypothesis, if present, must be an object containing id, content, status="unverified",
evidence_for=[] and evidence_against=[]. It must remain a hypothesis until documents verify it.
"""

PLANNING_SYSTEM = "You plan evidence-based factual retrieval. Follow the question's constraints and return only the required JSON."

QUERY_EXPANSION = """Rewrite this retrieval query into exactly TWO alternative ENGLISH keyword queries.
Keep its factual target. Use complementary angles: aliases or a distinctive explicit constraint,
and a plausible named candidate ONLY as a hypothesis for verification. Do not invent confirmed facts.
Avoid market commentary, instructions to a researcher, placeholders, quotation marks, Boolean
operators and site filters. Return JSON only: {{"queries": ["first English keyword query", "second English keyword query"]}}.
Original query: {query}
"""
