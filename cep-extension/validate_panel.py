"""Validate CEP entry points and Vite's complete emitted asset graph (Python 3.10+)."""
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


def local_file(base: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise ValueError('Empty or invalid asset reference')
    url = urlsplit(reference)
    if url.scheme or url.netloc or reference.startswith(('/', '\\')):
        raise ValueError(f'Asset must be local and relative: {reference}')
    relative = unquote(url.path)
    if '\\' in relative or ':' in relative:
        raise ValueError(f'Invalid asset path: {reference}')
    result = (base / relative).resolve()
    if not result.is_relative_to(base.resolve()) or not result.is_file() or result.stat().st_size == 0:
        raise ValueError(f'Missing, empty, or out-of-tree asset: {reference}')
    return result


class PanelHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.modules = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('src') or (attrs.get('href') if tag == 'link' else None)
        if value:
            self.assets.append(value)
        if tag == 'script' and attrs.get('type') == 'module' and attrs.get('src'):
            self.modules.append(attrs['src'])


def validate_panel(root: Path) -> None:
    root = root.resolve()
    manifest = ET.parse(local_file(root, 'CSXS/manifest.xml')).getroot()
    if manifest.tag != 'ExtensionManifest':
        raise ValueError('Expected CEP ExtensionManifest XML')
    extension_id = 'com.illustrator.mcp.panel'
    if manifest.find(f'./ExtensionList/Extension[@Id="{extension_id}"]') is None:
        raise ValueError('Panel identity missing from CEP extension list')
    resources = manifest.find(f'./DispatchInfoList/Extension[@Id="{extension_id}"]/DispatchInfo/Resources')
    if resources is None:
        raise ValueError('Panel dispatch resources missing')
    main = local_file(root, (resources.findtext('MainPath') or '').strip())
    local_file(root, (resources.findtext('ScriptPath') or '').strip())
    dist = main.parent
    bridge = local_file(dist, 'CSInterface.js')
    html = PanelHTML()
    html.feed(main.read_text(encoding='utf-8'))
    assets = {local_file(dist, ref) for ref in html.assets}
    if bridge not in assets:
        raise ValueError('Panel HTML does not load CSInterface.js')
    modules = {local_file(dist, ref) for ref in html.modules}
    graph = json.loads(local_file(dist, '.vite/manifest.json').read_text(encoding='utf-8'))
    if not isinstance(graph, dict) or not graph:
        raise ValueError('Empty or invalid Vite build manifest')
    entries = set()
    for key, chunk in graph.items():
        if not isinstance(chunk, dict):
            raise ValueError(f'Invalid Vite chunk: {key}')
        file = local_file(dist, chunk.get('file'))
        if chunk.get('isEntry') and chunk.get('src') == main.name:
            entries.add(file)
        for field in ('css', 'assets'):
            for ref in chunk.get(field, []):
                local_file(dist, ref)
        for field in ('imports', 'dynamicImports'):
            for ref in chunk.get(field, []):
                if ref not in graph:
                    raise ValueError(f'Missing Vite chunk {ref}, referenced by {key}')
    if not entries or not entries <= modules:
        raise ValueError('Panel HTML must load its built application module from the Vite manifest')


if __name__ == '__main__':
    try:
        validate_panel(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
        print('Panel payload verified (CEP manifest, application entry, and Vite asset graph).')
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        print(f'ERROR: Panel payload validation failed: {error}', file=sys.stderr)
        sys.exit(1)
