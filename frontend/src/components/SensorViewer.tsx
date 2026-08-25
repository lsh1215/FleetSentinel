import { useEffect, useRef, useState } from "react";

/**
 * Rerun 웹뷰어 — 직접 감싼다.
 *
 * ## 왜 공식 React 래퍼(`@rerun-io/web-viewer-react`)를 안 쓰나
 *
 * 그 래퍼는 클래스 컴포넌트이고 **생성자에서 `new WebViewer()`를 만든 뒤
 * `componentDidMount`에서 `start()`, `componentWillUnmount`에서 `stop()`** 한다.
 *
 * React 19 StrictMode는 개발 모드에서 `mount → unmount → mount`를 **같은 인스턴스에**
 * 실행한다. 그러면 이 순서가 된다:
 *
 * ```
 * start(handle)  →  handle.stop()  →  start(handle)   ← 이미 정지된 핸들을 다시 시작
 * ```
 *
 * 생성자는 다시 돌지 않으므로 두 번째 `start`는 죽은 핸들을 붙잡는다. 결과는 **오류 없는
 * 빈 화면**이다. StrictMode는 하위 트리에서 끌 수 없고, 그것 하나 때문에 앱 전체의
 * StrictMode를 포기하는 것도 손해다.
 *
 * 그래서 프레임워크 비의존 패키지(`@rerun-io/web-viewer`)를 이펙트에서 직접 쓴다.
 * **이펙트가 실행될 때마다 새 인스턴스를 만들고 정리 시 버린다** — StrictMode의
 * 이중 마운트가 정확히 이 패턴을 검증하려고 존재한다.
 *
 * ## 지연 로드
 *
 * wasm이 29.8MB다. 정적 import하면 초기 로딩에 들어가므로 이펙트 안에서 동적 import한다.
 */
interface Props {
  rrdUrl: string;
  /** 같은 URL이라도 이 값이 바뀌면 뷰어를 새로 만든다(수동 재시작). */
  reloadKey?: number;
}

type Phase = { kind: "idle" } | { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

export function SensorViewer({ rrdUrl, reloadKey = 0 }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let cancelled = false;
    // any가 아니라 최소 인터페이스로 좁혀 둔다 — 정리 경로에서 필요한 것만 쓴다.
    let viewer: { start: (...a: unknown[]) => Promise<void>; stop: () => void } | null = null;

    setPhase({ kind: "loading" });

    (async () => {
      try {
        const mod = await import("@rerun-io/web-viewer");
        if (cancelled) return;

        // 이펙트 실행마다 새 인스턴스 — StrictMode 이중 마운트에도 안전하다.
        const instance = new mod.WebViewer();
        viewer = instance as unknown as typeof viewer;

        await instance.start(rrdUrl, host, {
          hide_welcome_screen: true,
          width: "100%",
          height: "100%",
        });
        if (cancelled) {
          instance.stop();
          return;
        }
        setPhase({ kind: "ready" });
      } catch (err) {
        if (cancelled) return;
        setPhase({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    })();

    return () => {
      cancelled = true;
      try {
        viewer?.stop();
      } catch {
        /* 이미 정지됐거나 시작 전이면 무시 */
      }
      // 뷰어가 만든 canvas가 남을 수 있다. 다음 마운트에서 겹치지 않게 비운다.
      host.replaceChildren();
    };
  }, [rrdUrl, reloadKey]);

  return (
    <div className="viewer-wrap">
      <div ref={hostRef} className="viewer-host" />
      {phase.kind !== "ready" && (
        <div className="viewer-overlay">
          {phase.kind === "loading" && (
            <>
              <p><b>뷰어 로드 중…</b></p>
              <p className="muted">wasm 약 29.8MB (gzip 9.6MB) — 첫 로드에 몇 초 걸린다.</p>
            </>
          )}
          {phase.kind === "error" && (
            <>
              <p className="bad"><b>뷰어를 시작하지 못했다</b></p>
              <p className="muted mono">{phase.message}</p>
              <p className="muted">
                뷰어 버전과 <code>.rrd</code>를 만든 Rerun SDK 버전이 같아야 한다(현재 0.23.1).
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
