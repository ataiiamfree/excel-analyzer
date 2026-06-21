# Result Validation Skill

Use this skill to validate user-visible analysis results.

Rules:

1. Check that required output files exist and are readable.
2. Check that export requests produced artifacts in `output/`.
3. Treat empty stdout as a failure unless the step explicitly only produces files.
4. Preserve warnings so the report can disclose limitations.
