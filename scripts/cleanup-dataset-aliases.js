const fs = require('fs');
const path = require('path');

const root = process.cwd();
const datasetsRoot = path.join(root, 'uploads', 'datasets');
const aliasFile = path.join(root, 'config', 'dataset-symbol-aliases.json');

function walkFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) walkFiles(full, out);
    else if (ent.isFile()) out.push(full);
  }
  return out;
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function removeEmptyDirs(dir) {
  if (!fs.existsSync(dir)) return;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.isDirectory()) removeEmptyDirs(path.join(dir, ent.name));
  }
  if (fs.readdirSync(dir).length === 0) {
    fs.rmdirSync(dir);
  }
}

function main() {
  if (!fs.existsSync(aliasFile)) {
    throw new Error(`Alias file not found: ${aliasFile}`);
  }

  const aliases = JSON.parse(fs.readFileSync(aliasFile, 'utf8'));
  let moved = 0;
  let replaced = 0;
  let skipped = 0;
  let deletedAliasDirs = 0;

  for (const [alias, canonical] of Object.entries(aliases)) {
    const srcDir = path.join(datasetsRoot, alias);
    const dstDir = path.join(datasetsRoot, canonical);

    if (!fs.existsSync(srcDir) || srcDir === dstDir) {
      continue;
    }

    ensureDir(dstDir);
    const files = walkFiles(srcDir);

    for (const src of files) {
      const rel = path.relative(srcDir, src);
      const dst = path.join(dstDir, rel);
      ensureDir(path.dirname(dst));

      if (!fs.existsSync(dst)) {
        fs.renameSync(src, dst);
        moved += 1;
        continue;
      }

      const srcStat = fs.statSync(src);
      const dstStat = fs.statSync(dst);
      const srcWins = srcStat.size > dstStat.size || (srcStat.size === dstStat.size && srcStat.mtimeMs > dstStat.mtimeMs);

      if (srcWins) {
        fs.copyFileSync(src, dst);
        fs.unlinkSync(src);
        replaced += 1;
      } else {
        fs.unlinkSync(src);
        skipped += 1;
      }
    }

    removeEmptyDirs(srcDir);
    if (!fs.existsSync(srcDir)) {
      deletedAliasDirs += 1;
    }
  }

  console.log(JSON.stringify({ moved, replaced, skipped, deletedAliasDirs }, null, 2));
}

main();
