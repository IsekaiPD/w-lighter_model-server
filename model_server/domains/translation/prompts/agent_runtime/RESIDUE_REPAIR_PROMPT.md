You are fixing a {target_language} web-novel translation that still contains leftover Korean text. You are given the Korean source and a list of sentence units (each with an `index`) taken from the translation that still contain Korean.

For each unit, return a `fixed` version where the leftover Korean is properly rendered in {target_language}, using the source for meaning.

Rules:
- Fix ONLY the Korean parts. Keep the parts that are already in {target_language} unchanged.
- Preserve the unit's leading/trailing whitespace and punctuation (do not merge or split sentences).
- Do not add explanations, notes, or any content not present in the source.
- Return the same `index` you were given for each fixed unit. If a unit genuinely needs no change, you may omit it.

Source (Korean):
{source_text}

Units to fix (JSON array, each is {{"index": int, "sentence": str}}):
{units_json}
