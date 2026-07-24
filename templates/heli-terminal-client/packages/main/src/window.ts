import { BrowserWindow, shell } from 'electron';
import { join } from 'path';
import { pathToFileURL } from 'url';
import { existsSync } from 'node:fs';

export const createMainWindow = (): BrowserWindow => {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    title: 'Heli Conference Terminal',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: join(__dirname, 'preload.js'),
    },
  });

  // 外部链接走默认浏览器，不在 app 内打开
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    // 开发模式：Vite dev server
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    // 生产模式：renderer 已被 electron-builder 拷到 process.resourcesPath/renderer/
    // pathToFileURL 处理 Windows 路径中的空格与中文
    const prodPath = join(process.resourcesPath, 'renderer', 'index.html');
    // dev/源码直跑 fallback：electron . 从 packages/main 运行时，renderer 在 ../renderer/dist
    const devPath = join(__dirname, '..', '..', 'renderer', 'dist', 'index.html');
    const indexPath = existsSync(prodPath) ? prodPath : devPath;
    win.loadURL(pathToFileURL(indexPath).toString());
  }

  return win;
};
