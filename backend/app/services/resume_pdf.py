"""Render only the application's escaped resume templates as downloadable PDFs."""

import base64
import io
import re

from PIL import Image

from app.services.renderer import list_templates, render_resume

_PHOTO_URL = re.compile(r"\Adata:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})\Z")
_MAX_PHOTO_URL = 7 * 1024 * 1024


def _photo_resource(url: str) -> tuple[str, bytes]:
    """No network or filesystem resources, including redirects and SVGs."""
    match = _PHOTO_URL.fullmatch(url) if len(url) <= _MAX_PHOTO_URL else None
    if not match:
        raise ValueError("PDF resources must be uploaded PNG or JPEG images")
    content = base64.b64decode(match[2], validate=True)
    # Reject broken or oversized images before WeasyPrint can include the data
    # URL in an image-decoding warning. Encoded images are private user data.
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > 20_000_000:
                raise ValueError("Invalid PDF photo")
            image.verify()
    except Exception:
        raise ValueError("Invalid PDF photo") from None
    return f"image/{match[1]}", content


def render_resume_pdf(template_id: str, data: dict) -> bytes:
    if template_id not in {template["id"] for template in list_templates()}:
        raise ValueError("模板不存在")
    # Lazy import: a missing optional native library must not prevent chatting,
    # saving, HTML preview, or Word export. The API reports a recoverable error.
    from weasyprint import HTML
    from weasyprint.urls import FatalURLFetchingError, URLFetcher, URLFetcherResponse

    class PhotoOnlyFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            try:
                content_type, content = _photo_resource(url)
            except (ValueError, TypeError):
                # Never include a resource URL in an exception or log: it can
                # contain the user's encoded photograph.
                raise FatalURLFetchingError("PDF resource is not an uploaded image") from None
            return URLFetcherResponse(url, body=content, headers={"Content-Type": content_type})

    html = render_resume(template_id, data, interactive=False)
    # Templates already carry their own horizontal padding and 210mm width.
    # Page margins reserve space on every page, including long resumes.
    style = """<style>
      @page { size: A4; margin: 10mm 0; }
      body { display: block !important; min-height: 0 !important; padding-top: 0 !important; padding-bottom: 0 !important; }
      .bottom-bar { margin-top: 12px; }
      .icons, .icon-circle { flex-shrink: 0; }
      .section-title, .item-header { break-after: avoid; }
      .header, .photo, .item-header { break-inside: avoid; }
      p, li { orphans: 2; widows: 2; }
    </style>"""
    html = html.replace("</head>", style + "</head>")
    try:
        return HTML(string=html, url_fetcher=PhotoOnlyFetcher()).write_pdf()
    except FatalURLFetchingError:
        # WeasyPrint's fatal fetch error inherits BaseException; normalize only
        # this explicit renderer failure so the API can provide a retry path.
        raise ValueError("PDF resource is not an uploaded image") from None
