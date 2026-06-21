"""Materialize public spreadsheet benchmarks into run_eval manifests."""

from __future__ import annotations

import json
import re
import shutil
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "eval_datasets"
HF_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/main/{filename}"


@dataclass(frozen=True)
class ArchiveSpec:
    repo: str
    filename: str

    @property
    def url(self) -> str:
        return HF_RESOLVE.format(repo=self.repo, filename=self.filename)


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    default_variant: str
    archives: dict[str, ArchiveSpec]


BENCHMARKS: dict[str, BenchmarkSpec] = {
    "spreadsheetbench": BenchmarkSpec(
        name="spreadsheetbench",
        default_variant="verified",
        archives={
            "verified": ArchiveSpec("KAKA22/SpreadsheetBench", "spreadsheetbench_verified_400.tar.gz"),
            "full": ArchiveSpec("KAKA22/SpreadsheetBench", "spreadsheetbench_912_v0.1.tar.gz"),
        },
    ),
    "spreadsheetbench-v2": BenchmarkSpec(
        name="spreadsheetbench-v2",
        default_variant="example",
        archives={
            "example": ArchiveSpec("KAKA22/SpreadsheetBench-v2", "data_example_05_11.zip"),
            "full": ArchiveSpec("KAKA22/SpreadsheetBench-v2", "spreadsheetbench-v2.zip"),
        },
    ),
}


@dataclass(frozen=True)
class WorkbookPair:
    input_path: Path
    golden_path: Path
    test_id: str


def materialize_benchmarks(
    names: list[str],
    *,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    variant: str | None = None,
    force: bool = False,
    download: bool = True,
) -> list[Path]:
    expanded: list[str] = []
    for name in names:
        if name == "all":
            expanded.extend(BENCHMARKS)
        else:
            expanded.append(name)
    return [
        materialize_benchmark(
            name,
            output_dir=output_dir,
            variant=variant,
            force=force,
            download=download,
        )
        for name in expanded
    ]


def materialize_benchmark(
    name: str,
    *,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    variant: str | None = None,
    force: bool = False,
    download: bool = True,
) -> Path:
    key = name.strip().lower()
    if key not in BENCHMARKS:
        raise ValueError(f"Unknown benchmark {name!r}. Expected one of: {', '.join(sorted(BENCHMARKS))}, all")

    spec = BENCHMARKS[key]
    archive_variant = variant or spec.default_variant
    if archive_variant not in spec.archives:
        choices = ", ".join(sorted(spec.archives))
        raise ValueError(f"Unknown variant {archive_variant!r} for {key}. Expected one of: {choices}")

    archive_spec = spec.archives[archive_variant]
    root = Path(output_dir)
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    benchmark_dir = root / key / archive_variant
    archive_path = benchmark_dir / "archives" / archive_spec.filename
    extracted_dir = benchmark_dir / "extracted"
    manifest_path = benchmark_dir / "manifest.json"

    if download:
        _download_archive(archive_spec.url, archive_path, force=force)
    elif not archive_path.exists():
        raise FileNotFoundError(f"Archive does not exist and download is disabled: {archive_path}")

    _extract_archive(archive_path, extracted_dir, force=force)
    if key == "spreadsheetbench":
        build_spreadsheetbench_manifest(extracted_dir, manifest_path)
    else:
        build_spreadsheetbench_v2_manifest(extracted_dir, manifest_path)
    return manifest_path


def build_spreadsheetbench_manifest(extracted_dir: str | Path, manifest_path: str | Path) -> Path:
    extracted_dir = Path(extracted_dir)
    manifest_path = Path(manifest_path)
    dataset_path = _find_first_dataset_json(extracted_dir)
    dataset_root = dataset_path.parent
    items = _load_json_list(dataset_path)

    cases: list[dict[str, Any]] = []
    for item in items:
        item_id = _case_text(item.get("id"))
        spreadsheet_path = _resolve_inside(dataset_root, item.get("spreadsheet_path") or f"spreadsheet/{item_id}")
        if not spreadsheet_path.exists():
            continue
        prompt = _read_prompt(spreadsheet_path) or _case_text(item.get("instruction"))
        for pair in _pair_workbooks(spreadsheet_path):
            cases.append(
                _case_entry(
                    case_id=f"spreadsheetbench-{item_id}-{pair.test_id}",
                    file_path=pair.input_path,
                    question=prompt,
                    manifest_path=manifest_path,
                    source="KAKA22/SpreadsheetBench",
                    answer_path=pair.golden_path,
                    answer_position=item.get("answer_position"),
                    answer_sheet=item.get("answer_sheet"),
                    notes=[
                        _case_text(item.get("instruction_type")),
                        f"spreadsheet_id={item_id}",
                    ],
                )
            )

    _write_manifest(
        manifest_path,
        benchmark_id="spreadsheetbench",
        description="KAKA22/SpreadsheetBench materialized from the official Hugging Face archive.",
        cases=cases,
    )
    return manifest_path


def build_spreadsheetbench_v2_manifest(extracted_dir: str | Path, manifest_path: str | Path) -> Path:
    extracted_dir = Path(extracted_dir)
    manifest_path = Path(manifest_path)

    cases: list[dict[str, Any]] = []
    for dataset_path in sorted(extracted_dir.rglob("dataset.json")):
        suite_root = dataset_path.parent
        suite_name = suite_root.name
        items = _load_json_list(dataset_path)
        for item in items:
            item_id = _case_text(item.get("id"))
            input_path = _resolve_inside(suite_root, item.get("spreadsheet_path"))
            answer_path = _resolve_inside(suite_root, item.get("golden_response_path") or item.get("answer_path"))
            if not input_path.exists() or not answer_path.exists():
                continue
            cases.append(
                _case_entry(
                    case_id=f"spreadsheetbench-v2-{suite_name}-{item_id}",
                    file_path=input_path,
                    question=_case_text(item.get("instruction")),
                    manifest_path=manifest_path,
                    source="KAKA22/SpreadsheetBench-v2",
                    answer_path=answer_path,
                    answer_position=item.get("answer_position"),
                    answer_sheet=item.get("answer_sheet"),
                    notes=[f"suite={suite_name}"],
                )
            )

    _write_manifest(
        manifest_path,
        benchmark_id="spreadsheetbench-v2",
        description="KAKA22/SpreadsheetBench-v2 materialized from the official Hugging Face archive.",
        cases=cases,
    )
    return manifest_path


def _download_archive(url: str, target: Path, *, force: bool = False) -> None:
    if target.exists() and target.stat().st_size > 0 and not force:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp")
    if tmp.exists():
        tmp.unlink()
    with urllib.request.urlopen(url) as response, tmp.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    tmp.replace(target)


def _extract_archive(archive_path: Path, extracted_dir: Path, *, force: bool = False) -> None:
    marker = extracted_dir / ".extracted"
    if marker.exists() and not force:
        return
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    suffixes = "".join(archive_path.suffixes[-2:])
    if suffixes.endswith(".tar.gz") or archive_path.suffix == ".tgz":
        with tarfile.open(archive_path, "r:*") as archive:
            _safe_extract_tar(archive, extracted_dir)
    elif archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract_zip(archive, extracted_dir)
    else:
        raise ValueError(f"Unsupported benchmark archive: {archive_path}")
    marker.write_text(archive_path.name, encoding="utf-8")


def _safe_extract_tar(archive: tarfile.TarFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.getmembers():
        member_target = (target_dir / member.name).resolve()
        if target_root not in member_target.parents and member_target != target_root:
            raise ValueError(f"Unsafe archive member path: {member.name}")
    archive.extractall(target_dir)


def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.infolist():
        member_target = (target_dir / member.filename).resolve()
        if target_root not in member_target.parents and member_target != target_root:
            raise ValueError(f"Unsafe archive member path: {member.filename}")
    archive.extractall(target_dir)


def _find_first_dataset_json(root: Path) -> Path:
    candidates = sorted(root.rglob("dataset.json"))
    if not candidates:
        raise FileNotFoundError(f"No dataset.json found under {root}")
    return candidates[0]


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("cases", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"Expected a JSON list or object with cases in {path}")
    return [dict(item) for item in items if isinstance(item, dict)]


def _resolve_inside(base: Path, raw_path: Any) -> Path:
    if raw_path is None:
        return base / "__missing__"
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _read_prompt(folder: Path) -> str:
    prompt_path = folder / "prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _pair_workbooks(folder: Path) -> list[WorkbookPair]:
    inputs: dict[str, Path] = {}
    goldens: dict[str, Path] = {}
    for path in sorted(folder.glob("*.xls*")):
        key = _workbook_pair_key(path, kind="input")
        if key is not None:
            inputs[key] = path
            continue
        key = _workbook_pair_key(path, kind="golden")
        if key is not None:
            goldens[key] = path

    pairs: list[WorkbookPair] = []
    for key, input_path in sorted(inputs.items()):
        golden_path = goldens.get(key) or goldens.get("")
        if golden_path is None and len(inputs) == 1 and len(goldens) == 1:
            golden_path = next(iter(goldens.values()))
        if golden_path is None:
            continue
        pairs.append(
            WorkbookPair(
                input_path=input_path,
                golden_path=golden_path,
                test_id=_safe_id(key or input_path.stem),
            )
        )
    return pairs


def _workbook_pair_key(path: Path, *, kind: str) -> str | None:
    stem = path.stem
    lowered = stem.lower()
    if kind == "input":
        for suffix in ("_input", "_init"):
            if lowered.endswith(suffix):
                return stem[: -len(suffix)]
        if lowered in {"input", "initial"}:
            return ""
    else:
        for suffix in ("_answer", "_golden"):
            if lowered.endswith(suffix):
                return stem[: -len(suffix)]
        if lowered in {"answer", "golden"}:
            return ""
    return None


def _case_entry(
    *,
    case_id: str,
    file_path: Path,
    question: str,
    manifest_path: Path,
    source: str,
    answer_path: Path,
    answer_position: Any,
    answer_sheet: Any,
    notes: list[str],
) -> dict[str, Any]:
    prompt = question.strip()
    if "output" not in prompt.casefold() and "save" not in prompt.casefold():
        prompt = (
            f"{prompt}\n\n"
            "Please create a completed workbook artifact in .xlsx format so it can be compared "
            "against the provided golden workbook."
        )
    return {
        "id": _safe_id(case_id),
        "file": _relative_to_manifest(file_path, manifest_path),
        "question": prompt,
        "source": source,
        "tests": [note for note in notes if note],
        "assertions": {
            "required_output_exts": [".xlsx"],
            "answer_workbook": {
                "path": _relative_to_manifest(answer_path, manifest_path),
                "ranges": answer_position,
                "sheet": answer_sheet,
                "min_match_ratio": 1.0,
                "max_mismatches": 0,
                "abs_tol": 1e-6,
            },
        },
    }


def _relative_to_manifest(path: Path, manifest_path: Path) -> str:
    try:
        return str(path.resolve().relative_to(manifest_path.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def _write_manifest(manifest_path: Path, *, benchmark_id: str, description: str, cases: list[dict[str, Any]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": benchmark_id,
        "description": description,
        "generated_by": "scripts/benchmark_data.py",
        "case_count": len(cases),
        "cases": cases,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _case_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_id(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "case"
