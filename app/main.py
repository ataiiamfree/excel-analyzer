"""Compatibility exports for legacy tests.

The previous interactive entrypoint has been replaced by ``app.api.server``.
Pure formatting helpers remain importable here so older unit tests and scripts
do not need to change immediately.
"""

from app.ui_helpers import (
    _format_plan_for_ui,
    _format_step_result_for_ui,
    _message_ui_content,
    _message_ui_marker,
    _message_ui_metadata,
    _mime_for_path,
    _report_for_ui,
    _table_preview_for_path,
)

__all__ = [
    "_format_plan_for_ui",
    "_format_step_result_for_ui",
    "_message_ui_content",
    "_message_ui_marker",
    "_message_ui_metadata",
    "_mime_for_path",
    "_report_for_ui",
    "_table_preview_for_path",
]
