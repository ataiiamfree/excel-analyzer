from io import BytesIO

import openpyxl
import pytest
from fastapi import HTTPException, UploadFile

from app.api.uploads import save_validated_excel


def _workbook_bytes() -> bytes:
    buffer = BytesIO()
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["部门", "金额"])
    worksheet.append(["销售部", 100])
    workbook.save(buffer)
    return buffer.getvalue()


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def test_excel_upload_rejects_unsupported_extension(tmp_path):
    target = tmp_path / "input.csv"

    with pytest.raises(HTTPException) as exc_info:
        save_validated_excel(_upload("input.csv", b"a,b\n1,2"), target, max_size_mb=100)

    assert exc_info.value.status_code == 415
    assert not target.exists()


def test_excel_upload_rejects_oversized_file_without_replacing_existing(tmp_path):
    target = tmp_path / "input.xlsx"
    target.write_bytes(b"existing-good-file")

    with pytest.raises(HTTPException) as exc_info:
        save_validated_excel(
            _upload("input.xlsx", b"x" * (1024 * 1024 + 1)),
            target,
            max_size_mb=1,
        )

    assert exc_info.value.status_code == 413
    assert target.read_bytes() == b"existing-good-file"
    assert not list(tmp_path.glob(".*.uploading.*"))


def test_excel_upload_rejects_corrupt_workbook_without_replacing_existing(tmp_path):
    target = tmp_path / "input.xlsx"
    target.write_bytes(b"existing-good-file")

    with pytest.raises(HTTPException) as exc_info:
        save_validated_excel(
            _upload("input.xlsx", b"not an excel workbook"),
            target,
            max_size_mb=100,
        )

    assert exc_info.value.status_code == 422
    assert target.read_bytes() == b"existing-good-file"
    assert not list(tmp_path.glob(".*.uploading.*"))


def test_excel_upload_atomically_replaces_file_after_validation(tmp_path):
    target = tmp_path / "input.xlsx"
    target.write_bytes(b"old")
    content = _workbook_bytes()

    size, sheet_count, row_count = save_validated_excel(
        _upload("input.xlsx", content),
        target,
        max_size_mb=100,
    )

    assert size == len(content)
    assert sheet_count == 1
    assert row_count == 2
    assert target.read_bytes() == content
