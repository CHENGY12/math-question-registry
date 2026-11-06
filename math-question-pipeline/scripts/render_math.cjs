// Build-time typesetting with the project's pinned KaTeX; never fetch remote resources.
const fs = require('node:fs');
const katex = require('../vendor/katex/katex.min.js');
const expressions = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
const result = expressions.map(({latex, display}) => katex.renderToString(latex, {
  displayMode: display,
  throwOnError: true,
  strict: 'error',
  trust: false,
  output: 'htmlAndMathml',
  maxExpand: 1000,
  maxSize: 30,
}));
process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(String(error.message).slice(0, 1200));
  process.exitCode = 2;
}
