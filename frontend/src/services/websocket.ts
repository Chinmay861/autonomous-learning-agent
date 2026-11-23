import type { ExperimentEvent } from '../types';
import { experimentSocketUrl } from './backendUrl';

type Listener = (event: ExperimentEvent) => void;
type StatusListener = (connected: boolean) => void;

/** One live connection to an experiment's event stream, with automatic reconnect. */
export class ExperimentSocket {
  private ws: WebSocket | null = null;
  private timer: number | null = null;
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
    ws.onopen = () => this.onStatus(true);
    ws.onmessage = (msg) => {
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
  }

  close() {
    this.closed = true;
    if (this.timer) window.clearTimeout(this.timer);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
    this.ws = null;
  }
}
