import { AgentEvent } from '../types';

type EventCallback = (event: AgentEvent) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private callbacks: EventCallback[] = [];
  private reconnectTimer: number | null = null;
  private currentTaskId: string | null = null;
  private currentToken: string | null = null;

  connect(taskId: string, token: string) {
    this.currentTaskId = taskId;
    this.currentToken = token;
    this.disconnect();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    // In dev, use the proxy or direct. Since Vite proxies /ws, we can just use the path
    // But WebSocket requires full URL. Actually Vite proxy works with wss? Let's use direct host if not provided.
    // For local dev, Vite proxies ws://localhost:5173/ws to ws://localhost:8000
    const wsUrl = `${protocol}//${host}/ws/${taskId}?token=${token}`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      if (this.reconnectTimer) {
        window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const data: AgentEvent = JSON.parse(event.data);
        this.callbacks.forEach(cb => cb(data));
      } catch (err) {
        console.error('Failed to parse WebSocket message', err);
      }
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('WebSocket error', err);
    };
  }

  onEvent(callback: EventCallback) {
    this.callbacks.push(callback);
    return () => {
      this.callbacks = this.callbacks.filter(cb => cb !== callback);
    };
  }

  disconnect() {
    if (this.ws) {
      this.ws.onclose = null; // Prevent auto-reconnect
      this.ws.close();
      this.ws = null;
    }
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.currentTaskId && this.currentToken && !this.reconnectTimer) {
      this.reconnectTimer = window.setTimeout(() => {
        console.log('Attempting to reconnect...');
        this.connect(this.currentTaskId!, this.currentToken!);
      }, 3000);
    }
  }
}

export const wsClient = new WebSocketClient();
