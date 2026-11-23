import type { ExperimentEvent } from '../types';
import { experimentSocketUrl } from './backendUrl';

type Listener = (event: ExperimentEvent) => void;
type StatusListener = (connected: boolean) => void;

// The server sends at least a heartbeat every 20 s. Silence for longer than this means the
// connection died without closing (a "half-open" socket), so it is replaced.
const SILENCE_LIMIT_MS = 50_000;

/** One live connection to an experiment's event stream, with automatic reconnect. */
export class ExperimentSocket {
  private ws: WebSocket | null = null;
  private timer: number | null = null;
  private watchdog: number | null = null;
  private lastMessage = 0;
  private closed = false;

  constructor(
    private experimentId: string,
    private onEvent: Listener,
    private onStatus: StatusListener = () => {},
  ) {}

  open() {
    this.closed = false;
    const token = localStorage.getItem('token') || '';
    const ws = new WebSocket(experimentSocketUrl(this.experimentId, token));
    this.ws = ws;
    this.lastMessage = Date.now();
    ws.onopen = () => {
      this.lastMessage = Date.now();
      this.onStatus(true);
    };
    ws.onmessage = (msg) => {
      this.lastMessage = Date.now();
      try {
        const event = JSON.parse(msg.data) as ExperimentEvent;
        if (event.type !== 'heartbeat') this.onEvent(event);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = (e) => {
      this.onStatus(false);
      // 4401 = bad token, 4404 = not your experiment: retrying cannot help.
      if (this.closed || e.code === 4401 || e.code === 4404) return;
      this.timer = window.setTimeout(() => this.open(), 3000);
    };
    if (this.watchdog === null) {
      this.watchdog = window.setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN && Date.now() - this.lastMessage > SILENCE_LIMIT_MS) {
          this.ws.close(); // onclose reconnects
        }
      }, 10_000);
    }
  }

  close() {
    this.closed = true;
    if (this.timer) window.clearTimeout(this.timer);
    if (this.watchdog !== null) window.clearInterval(this.watchdog);
    this.watchdog = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
    this.ws = null;
  }
}
