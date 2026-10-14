"""Manual MCP smoke test. Output contains shapes/counts, never profile values."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def smoke(url, token):
    endpoint = url.rstrip('/')
    if not endpoint.endswith('/mcp'):
        endpoint += '/mcp'
    origin = urlsplit(endpoint)
    if origin.scheme not in {'http', 'https'} or not origin.netloc or origin.username or origin.password:
        raise ValueError('invalid_url')
    async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + token}, timeout=120) as http:
        async with Client(streamable_http_client(endpoint, http_client=http), mode='legacy') as client:
            tools = await client.list_tools()
            print(json.dumps({'tools': len(tools.tools), 'tool_schema_fields': sorted(tools.tools[0].input_schema) if tools.tools else []}))
            async def call(name, args=None):
                result = await client.call_tool(name, args or {})
                if result.is_error or not isinstance(result.structured_content, dict):
                    raise ValueError('tool_failed')
                return result.structured_content
            profile = await call('huhua_profile_get')
            print(json.dumps({'profile_fields': sorted(profile), 'confirmed_facts': len(profile.get('facts', [])),
                              'pending_conflicts': profile.get('pending_conflicts', 0)}))
            templates = await call('huhua_templates_list')
            print(json.dumps({'templates': len(templates['templates'])}))
            template = templates['templates'][0]['id']
            sample = json.loads((Path(__file__).resolve().parents[1] / 'data/sample_resume.json').read_text())
            measured = await call('huhua_resume_measure', {'resume': sample, 'template_id': template})
            print(json.dumps({'measure_fields': sorted(measured), 'pages': measured['pages'],
                              'overflow_lines': measured['overflow_lines']}))
            sample['layout'] = {'density': measured['suggested_density'], 'density_source': 'user'}
            exported = await call('huhua_resume_export', {'resume': sample, 'template_id': template, 'format': 'pdf'})
            download = urlsplit(exported['download_url'])
            if (download.scheme, download.netloc) != (origin.scheme, origin.netloc):
                raise ValueError('unexpected_download_origin')
            # The one-use capability needs no PAT header; never follow redirects.
            async with httpx2.AsyncClient(timeout=120, follow_redirects=False) as anonymous:
                response = await anonymous.get(exported['download_url'])
            if response.status_code != 200 or not response.content.startswith(b'%PDF-'):
                raise ValueError('invalid_pdf')
            print(json.dumps({'export_fields': sorted(exported), 'pdf_bytes': len(response.content),
                              'pdf_signature_valid': True,
                              'lexical_issues': exported['fact_check']['issue_count']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Application origin or full /mcp URL')
    parser.add_argument('--token-env', default='HUHUA_MCP_TOKEN', help='Environment variable containing the PAT')
    args = parser.parse_args()
    # SDK/http clients may log URLs. Smoke output must not include capabilities.
    logging.disable(logging.CRITICAL)
    token = os.environ.get(args.token_env, '')
    if not token.startswith('hh_pat_'):
        print(json.dumps({'ok': False, 'error': 'token_environment_missing_or_invalid'}))
        return 2
    try:
        asyncio.run(smoke(args.url, token))
    except Exception:
        print(json.dumps({'ok': False, 'error': 'smoke_failed_check_connection_scopes_and_server'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
