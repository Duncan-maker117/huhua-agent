"""One-use, already-rendered downloads. The opaque URL is the capability."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.services.mcp_service import downloads

router = APIRouter()


@router.get('/api/mcp-download/{token}')
def download(token: str):
    row = downloads.take(token)
    media = ('application/pdf' if row['format'] == 'pdf' else
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return Response(row['content'], media_type=media, headers={
        'Content-Disposition': 'attachment; filename=resume.' + row['format'],
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
    })
