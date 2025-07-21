import { io } from 'socket.io-client';
let socket = null;

export function initSocket() {
  if (!socket) {
    socket = io('http://127.0.0.1:5000', {
      transports: ['websocket'], // 强制使用 websocket
    });
  }
  return socket;
}

export function getSocket() {
  return socket;
}

export function closeSocket() {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
}
