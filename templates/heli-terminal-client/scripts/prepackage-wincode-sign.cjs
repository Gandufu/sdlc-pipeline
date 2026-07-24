#!/usr/bin/env node
/**
 * electron-builder 在 Windows 上解压 winCodeSign 7z 包时遇到 darwin 目录里的 symlink
 * 会失败（"Cannot create symbolic link"），因为 7za.exe 在 Windows 普通用户权限下
 * 不能创建 symlink。
 *
 * 此脚本在每次 pnpm package 前自动解压所有 winCodeSign 缓存里的 7z 包，
 * 使用 `-snl` 参数跳过 symlink，让 electron-builder 之后检查缓存已解压时跳过这一步。
 *
 * 注意：每个 hash 目录（缓存解压目标）是 electron-builder 内部用 URL hash 算出来的，
 * 此脚本只处理当前已下载的 7z 包；新的 7z 包会触发 electron-builder 下载 + 解压，
 * 所以我们用一个 retry loop：第一次解压完触发一次 package，让新 hash 出现后再跑一次。
 */

const { execFileSync } = require('node:child_process');
const { existsSync, readdirSync } = require('node:fs');
const { join } = require('node:path');
const os = require('node:os');

const WIN_CODE_SIGN_DIR = join(os.homedir(), 'AppData', 'Local', 'electron-builder', 'Cache', 'winCodeSign');
const SEVEN_ZA = join(__dirname, '..', 'node_modules', '7zip-bin', 'win', 'x64', '7za.exe');

const extractAll = () => {
  if (!existsSync(WIN_CODE_SIGN_DIR)) {
    console.log('[prepackage] winCodeSign cache dir does not exist yet, nothing to extract');
    return 0;
  }

  const archives = readdirSync(WIN_CODE_SIGN_DIR).filter((f) => f.endsWith('.7z'));
  if (archives.length === 0) {
    console.log('[prepackage] no winCodeSign 7z archives yet');
    return 0;
  }

  let extracted = 0;
  for (const archive of archives) {
    const hash = archive.replace(/\.7z$/, '');
    const target = join(WIN_CODE_SIGN_DIR, hash);
    if (existsSync(target)) {
      continue;
    }
    console.log(`[prepackage] extracting ${archive} -> ${hash} (skip symlinks)`);
    try {
      execFileSync(SEVEN_ZA, ['x', '-bd', '-snl', join(WIN_CODE_SIGN_DIR, archive), `-o${target}`], {
        stdio: 'inherit',
      });
      extracted += 1;
    } catch (err) {
      console.warn(`[prepackage] WARN: failed to extract ${archive}, electron-builder will retry`);
    }
  }
  return extracted;
};

const totalExtracted = extractAll();
console.log(`[prepackage] done — extracted ${totalExtracted} archive(s)`);
