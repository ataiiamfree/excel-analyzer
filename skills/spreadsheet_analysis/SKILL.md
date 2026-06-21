# Spreadsheet Analysis Skill

Use this skill for Excel, CSV, Sheets, and structured office data analysis.

Rules:

1. Do not ask the model to read raw spreadsheet details directly.
2. Use workbook/table manifests and normalized table profiles as the planning source.
3. Use the `python` tool for calculations, filtering, ranking, charting, and exports.
4. User-visible files must be written to `output/`.
5. The final response must mention the result, output artifacts, and any data limitations.
6. If a user asks about an already generated artifact, route to `artifact_qa` instead.
