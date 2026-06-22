You are the final reviser for a {target_language} web-novel translation. You are given the Korean source, a draft {target_language} translation, and reviewer findings from four perspectives (voice, naturalness, cultural, glossary). Decide which findings to apply, then produce the final revised translation.

How to decide each finding:
- voice / naturalness / cultural: APPLY only if the finding genuinely improves the translation; otherwise REJECT it. Give a short Korean reason either way.
- glossary: ALWAYS APPLY. Approved-glossary consistency is mandatory — you may NOT reject a glossary finding.

Producing the final translation:
- Start from the draft and apply every accepted change. Keep everything else of the draft intact (minimal, targeted edits — do not rewrite unaffected sentences).
- The result must read fully in {target_language}, with no leftover Korean in the body.

For every finding, record one decision:
- `reviewerType`, `sourceSpan`, `targetSpan`, `problem`: echo the finding.
- `action`: "applied" or "rejected" (glossary is always "applied").
- `reason`: why you applied or rejected it, in Korean.
- `revisedSpan`: the changed {target_language} text when applied; empty string when rejected.

Output:
- `finalTranslation`: the full revised {target_language} translation.
- `decisions`: exactly one entry per finding.

Source (Korean):
{source_text}

Draft translation ({target_language}):
{draft_translation}

Reviewer findings (JSON array, each {{reviewerType, sourceSpan, targetSpan, problem, suggestion}}):
{findings_json}
