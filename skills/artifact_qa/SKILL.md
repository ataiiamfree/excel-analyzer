# Artifact QA Skill

Use this skill when the user asks about an existing file, chart, image, table,
report, or attachment produced by the current conversation.

Rules:

1. Do not rerun spreadsheet preprocessing just to explain an existing artifact.
2. Resolve the artifact by file name, artifact id, or recency.
3. Inspect artifact metadata, producer step, source tables, script path, stdout summary, and chart metadata.
4. Explain what the artifact is, where it came from, what it means, and what limitations apply.
5. If multiple artifacts could match, explain the selected match and mention the ambiguity.
