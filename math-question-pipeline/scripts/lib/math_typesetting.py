"""Strict, offline formula typesetting for edited text and learning guidance."""
import base64
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]

# Dollar delimiters are authoring syntax, not raw HTML. Unmatched delimiters fail the build.
MATH = re.compile(r'\$\$(.+?)\$\$|\$([^$\n]+)\$', re.DOTALL)


def segments(text):
    if re.search(r'[\x00-\x09\x0b-\x1f\x7f]', text):
        raise ValueError('Unexpected control character in authored text; check escaped LaTeX (for example \\frac or \\text)')
    end = 0
    for match in MATH.finditer(text):
        plain = text[end:match.start()]
        if '$' in plain:
            raise ValueError('Unmatched math delimiter: ' + text)
        yield ('text', plain)
        expression = match.group(1) or match.group(2)
        if '\n' in expression:
            raise ValueError('A formula contains a newline; use single-line LaTeX and explicit alignment commands')
        yield ('math', (expression, match.group(1) is not None))
        end = match.end()
    if '$' in text[end:]:
        raise ValueError('Unmatched math delimiter: ' + text)
    yield ('text', text[end:])


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


class MathTypesetter:
    def __init__(self, content):
        root = SKILL_ROOT
        expressions = list(dict.fromkeys(value for text in strings(content)
                           for kind, value in segments(text) if kind == 'math'))
        node = shutil.which('node')
        if not node:
            raise RuntimeError('Node.js is required to typeset formulas with bundled KaTeX.')
        try:
            result = subprocess.run([node, str(root/'scripts/render_math.cjs')],
                input=json.dumps([{'latex':latex, 'display':display} for latex,display in expressions]),
                text=True, capture_output=True, check=True, timeout=120)
        except subprocess.CalledProcessError as error:
            raise ValueError('Strict mathematical typesetting failed: ' + error.stderr[-1200:]) from error
        except subprocess.TimeoutExpired as error:
            raise ValueError('Mathematical typesetting exceeded 120 seconds; reduce the batch size') from error
        rendered = json.loads(result.stdout)
        assert len(rendered) == len(expressions)
        self.cache = dict(zip(expressions, rendered))
        css = (root/'vendor/katex/katex.min.css').read_text()
        def embed(match):
            path = root/'vendor/katex'/match.group(1)
            data = base64.b64encode(path.read_bytes()).decode('ascii')
            return 'src:url(data:font/woff2;base64,' + data + ') format("woff2")'
        self.css = re.sub(r'src:url\((fonts/[^)]+\.woff2)\)[^}]+', embed, css)
        assert not re.search(r'url\((?!data:)', self.css)

    def render(self, text):
        result = []
        parts = list(segments(text))
        for index, (kind, value) in enumerate(parts):
            if kind == 'text':
                result.append(html.escape(value).replace('\n','<br>'))
            else:
                # Long formulas scroll inside the line instead of widening the page.
                wrapper = 'math-display' if value[1] else 'math-inline'
                punctuation = ''
                if not value[1] and index+1 < len(parts) and parts[index+1][0] == 'text':
                    following = parts[index+1][1]
                    match = re.match(r'^[，。；：、！？）”]+', following)
                    if match:
                        punctuation = match.group(0)
                        parts[index+1] = ('text', following[len(punctuation):])
                # Keep punctuation outside math semantics but on the same visual line.
                result.append(f'<span class="{wrapper}">{self.cache[value]}{html.escape(punctuation)}</span>')
        return ''.join(result)
