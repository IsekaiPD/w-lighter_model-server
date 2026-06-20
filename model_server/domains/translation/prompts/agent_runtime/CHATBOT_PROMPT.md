Locale:
{locale} ({target_language})

Source {source_language} text:
{source_text}

Translation draft:
{draft_translation}

Current reviewed translation:
{reviewed_translation}

Translation rationale:
{translation_rationale}

Used RAG references:
{used_references_json}

Inspection report:
{inspection_report_json}

Translation memory / consistency constraints:
{translation_memory_json}

Chat history:
{chat_history_json}

User message:
{user_message}

Task:
- Answer the user in Korean unless the user asks otherwise.
- If the user asks why, explain using translation rationale, references, and inspection report.
- If the user asks for a change, propose a revised translation in `proposed_translation`.
- Do not say the revision was saved or applied. Set `needs_user_confirmation=true` when the user should approve the change.
