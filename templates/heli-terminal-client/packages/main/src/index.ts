import { app, BrowserWindow } from 'electron';
import { HttpClient } from './device/HttpClient';
import { AuthService } from './device/AuthService';
import { CapabilityProbe } from './device/CapabilityProbe';
import { createDeviceService } from './services/DeviceService';
import { registerDeviceHandlers } from './ipc/device.handlers';
import { createMainWindow } from './window';

// 设备地址从环境变量读（运行时配置），未来可改为设置页注入
// C7：HTTPS 传输 admin 密码与 token；自签证书场景下 HttpClient 需要配 rejectUnauthorized:false
const DEVICE_BASE_URL = process.env.DEVICE_BASE_URL ?? 'https://192.168.1.100';

const bootstrap = () => {
  const http = new HttpClient({
    baseURL: DEVICE_BASE_URL,
    maxConcurrent: 10,
  });

  const auth = new AuthService(http, DEVICE_BASE_URL);
  const probe = new CapabilityProbe(http);
  const deviceService = createDeviceService({ http, auth, probe });

  registerDeviceHandlers(deviceService);
};

app.whenReady().then(() => {
  bootstrap();
  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// 防止导航到外部 URL
app.on('web-contents-created', (_e, contents) => {
  contents.on('will-navigate', (event, url) => {
    if (!url.startsWith(DEVICE_BASE_URL) && !url.startsWith('file://')) {
      event.preventDefault();
    }
  });
});
