// Shared pre/post-install check. Requires Node.js, already needed to build the panel.
import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(process.argv[2] || path.dirname(fileURLToPath(import.meta.url)));
function requireFile(relative) {
    const file = path.resolve(root, relative);
    if (!file.startsWith(root + path.sep) || !statSync(file).isFile() || statSync(file).size === 0) {
        throw new Error(`Missing, empty, or invalid panel file: ${relative}`);
    }
    return file;
}
try {
    for (const file of ['dist/index.html', 'dist/CSInterface.js', 'CSXS/manifest.xml', 'jsx/host.jsx']) {
        requireFile(file);
    }
    const html = readFileSync(path.join(root, 'dist/index.html'), 'utf8');
    let count = 0;
    for (const match of html.matchAll(/\b(?:src|href)\s*=\s*["']([^"']+)["']/gi)) {
        const url = match[1];
        if (url.startsWith('#') || url.startsWith('data:')) continue;
        if (/^(?:[a-z]+:|\/)/i.test(url)) throw new Error(`Panel asset must be local and relative: ${url}`);
        requireFile(path.join('dist', decodeURIComponent(url.split(/[?#]/)[0])));
        count++;
    }
    if (!count) throw new Error('Panel HTML contains no asset references');
    console.log(`Panel payload verified (${count} HTML asset references).`);
} catch (error) {
    console.error(`ERROR: Panel payload validation failed: ${error.message}`);
    process.exitCode = 1;
}
