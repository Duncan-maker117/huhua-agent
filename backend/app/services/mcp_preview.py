"""MCP PNG 渲染隔离：超时终止子进程，不让原生排版一直占用请求线程。"""

import io
import json
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore

from fastapi import HTTPException


_slots = BoundedSemaphore(2)


class PreviewTimeout(TimeoutError):
    pass


def render_preview(template_id, data, page=1, dpi=100, *, wait_for_slot=False):
    from app.config import get_settings

    settings = get_settings()
    acquired = (_slots.acquire(timeout=settings.MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS)
                if wait_for_slot else _slots.acquire(blocking=False))
    if not acquired:
        raise HTTPException(503, '预览繁忙，请稍后重试')
    try:
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'app.services.mcp_preview'],
                cwd=Path(__file__).resolve().parents[2],
                input=json.dumps([template_id, data, page, dpi]).encode(),
                capture_output=True, timeout=settings.MCP_PREVIEW_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise PreviewTimeout('preview_timeout') from None
        # 子进程 stderr 可能含私有正文；只返回固定错误，不记录或透传。
        if result.returncode == 2:
            raise ValueError('page_out_of_range')
        if result.returncode or not result.stdout[4:].startswith(b'\x89PNG'):
            raise RuntimeError('preview_unavailable')
        return result.stdout[4:], int.from_bytes(result.stdout[:4], 'big')
    finally:
        _slots.release()


def main():
    import pdfplumber
    from app.services.resume_pdf import render_resume_pdf

    template_id, data, page, dpi = json.load(sys.stdin)
    with pdfplumber.open(io.BytesIO(render_resume_pdf(template_id, data))) as pdf:
        if page > len(pdf.pages):
            return 2
        output = io.BytesIO()
        pdf.pages[page - 1].to_image(resolution=dpi).original.save(output, format='PNG')
        sys.stdout.buffer.write(len(pdf.pages).to_bytes(4, 'big') + output.getvalue())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
