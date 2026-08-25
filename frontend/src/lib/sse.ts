/**
 * SSE 연결 관리자.
 *
 * 브라우저 내장 `EventSource`는 자동 재연결을 해주지만 **우리에게 필요한 것을 못 한다**:
 *
 *  1. 재연결 간격이 고정이고 제어할 수 없다 → 서버가 죽었을 때 재연결 폭풍을 만든다.
 *  2. 연결 상태를 알 방법이 `onerror`뿐이라 "끊김"과 "재시도 중"을 구분하지 못한다.
 *  3. 탭이 백그라운드로 가도 계속 받는다 → 돌아왔을 때 수만 건이 한꺼번에 밀린다.
 *
 * 그래서 EventSource를 감싸 **지수 백오프 + 지터**, **상태 관측**, **가시성 연동**을 얹는다.
 * 재개는 SSE 표준의 `Last-Event-ID`에 의존한다 — 서버가 `id:`로 재생 커서를 실어주고,
 * EventSource가 재연결 시 자동으로 그 헤더를 보낸다. 우리는 커서를 따로 관리하지 않는다.
 */
export type StreamStatus = "connecting" | "open" | "retrying" | "closed";

export interface SseOptions {
  url: string;
  /** 이벤트 이름별 핸들러. 핸들러는 **동기·저비용**이어야 한다(§ 아래 주석). */
  handlers: Record<string, (data: unknown, id: string | null) => void>;
  onStatus?: (status: StreamStatus, detail?: { attempt: number; nextDelayMs?: number }) => void;
  /** 탭이 숨겨지면 연결을 끊고, 돌아오면 Last-Event-ID로 재개한다. */
  pauseWhenHidden?: boolean;
  maxDelayMs?: number;
}

const BASE_DELAY_MS = 500;
const DEFAULT_MAX_DELAY_MS = 15_000;

export class SseClient {
  private source: EventSource | null = null;
  private attempt = 0;
  private retryTimer: number | null = null;
  private disposed = false;
  private lastId: string | null = null;

  constructor(private readonly opts: SseOptions) {}

  start(): void {
    this.disposed = false;
    if (this.opts.pauseWhenHidden !== false) {
      document.addEventListener("visibilitychange", this.onVisibility);
    }
    this.connect();
  }

  stop(): void {
    this.disposed = true;
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.clearRetry();
    this.close();
    this.opts.onStatus?.("closed", { attempt: this.attempt });
  }

  private onVisibility = (): void => {
    if (this.disposed) return;
    if (document.hidden) {
      // 백그라운드에서 계속 받으면 복귀 시 수만 건이 한꺼번에 밀려 프레임이 멈춘다.
      // 끊어두고 Last-Event-ID로 이어받는 편이 낫다 — 재생 스트림이라 건너뛰어도 무방하다.
      this.close();
      this.opts.onStatus?.("retrying", { attempt: this.attempt });
    } else {
      this.clearRetry();
      this.attempt = 0;
      this.connect();
    }
  };

  private connect(): void {
    if (this.disposed || document.hidden) return;
    this.close();
    this.opts.onStatus?.("connecting", { attempt: this.attempt });

    // EventSource는 헤더를 직접 못 넣는다. 최초 연결의 재개 지점은 쿼리로 넘기고,
    // 이후 자동 재연결은 브라우저가 Last-Event-ID 헤더로 처리한다.
    const url = this.lastId
      ? `${this.opts.url}${this.opts.url.includes("?") ? "&" : "?"}from=${encodeURIComponent(this.lastId)}`
      : this.opts.url;

    const es = new EventSource(url);
    this.source = es;

    es.onopen = () => {
      this.attempt = 0;
      this.opts.onStatus?.("open", { attempt: 0 });
    };

    for (const [name, handler] of Object.entries(this.opts.handlers)) {
      es.addEventListener(name, (ev) => {
        const me = ev as MessageEvent<string>;
        if (me.lastEventId) this.lastId = me.lastEventId;
        try {
          handler(JSON.parse(me.data), me.lastEventId || null);
        } catch (err) {
          // 한 건이 깨져도 스트림을 끊지 않는다 — 부분 실패가 전체를 죽이면 안 된다.
          console.warn(`[sse] ${name} 파싱 실패`, err);
        }
      });
    }

    es.onerror = () => {
      if (this.disposed) return;
      // EventSource는 스스로 재연결을 시도하지만 간격을 제어할 수 없다. 직접 관리한다.
      this.close();
      this.scheduleRetry();
    };
  }

  /** 지수 백오프 + 지터. 지터가 없으면 여러 탭·클라이언트가 동시에 재연결해 서버를 때린다. */
  private scheduleRetry(): void {
    const max = this.opts.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    const backoff = Math.min(max, BASE_DELAY_MS * 2 ** this.attempt);
    const jitter = Math.random() * backoff * 0.3;
    const delay = Math.round(backoff + jitter);
    this.attempt += 1;
    this.opts.onStatus?.("retrying", { attempt: this.attempt, nextDelayMs: delay });
    this.retryTimer = window.setTimeout(() => this.connect(), delay);
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private close(): void {
    this.source?.close();
    this.source = null;
  }
}
