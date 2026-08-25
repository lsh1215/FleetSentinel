import { Suspense, lazy, useState, type ComponentType } from "react";

/**
 * 센서 재생 패널.
 *
 * Rerun 웹뷰어는 wasm을 포함해 번들이 매우 크다. 초기 로드에 넣으면 지도·차트가 뜨기까지
 * 몇 초가 더 걸린다. **사용자가 실제로 열 때만 내려받도록** `lazy`로 코드 분할한다.
 *
 * 뷰어와 SDK는 버전이 결합돼 있다(0.23 이후로 직전 마이너까지 호환). 그래서 `.rrd`를
 * 만든 SDK 버전과 뷰어 패키지 버전을 같이 관리해야 한다 — 어긋나면 조용히 빈 화면이 된다.
 */
/** 뷰어에 넘기는 props. 패키지가 자체 React 타입을 번들해 우리 React 19 타입과 어긋나므로
 *  이 경계에서 한 번만 좁혀 쓴다 — 컴포넌트 내부까지 any가 번지지 않게 한다. */
type RerunProps = { rrd: string; width: string; height: string };

const RerunViewer = lazy<ComponentType<RerunProps>>(async () => {
  try {
    // 기본 내보내기다(named export가 아니다). 패키지 타입 정의로 확인했다.
    const mod = await import("@rerun-io/web-viewer-react");
    return { default: mod.default as unknown as ComponentType<RerunProps> };
  } catch {
    // 패키지 미설치·로드 실패 시에도 대시보드 전체가 죽지 않도록 대체 컴포넌트를 준다.
    const Fallback: ComponentType<RerunProps> = () => (
      <div className="viewer-fallback">
        <p><b>Rerun 웹뷰어를 불러오지 못했다</b></p>
        <p className="muted">
          뷰어 버전은 <code>.rrd</code>를 만든 Rerun SDK 버전과 맞춰야 한다.
          어긋나면 오류 없이 빈 화면이 된다.
        </p>
      </div>
    );
    return { default: Fallback };
  }
});

export function SensorPanel({ vehicleId, rrdUrl }: { vehicleId: string | null; rrdUrl: string | null }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="panel sensor">
      <div className="panel-head">
        <h2>센서 재생</h2>
        {rrdUrl && (
          <button className="ghost" onClick={() => setOpen((o) => !o)}>
            {open ? "닫기" : "열기"}
          </button>
        )}
      </div>
      {!vehicleId ? (
        <p className="empty">차량을 선택하면 해당 클립의 센서 로그를 재생한다.</p>
      ) : !rrdUrl ? (
        <p className="empty">
          <b>{vehicleId}</b>의 재생 파일이 없다.<br />
          <span className="muted">
            <code>replay_rerun.py</code>로 <code>.rrd</code>를 만들어 <code>public/rrd/</code>에 둔다.
          </span>
        </p>
      ) : !open ? (
        <p className="empty">
          <b>열기</b>를 누르면 뷰어를 내려받는다.<br />
          <span className="muted">wasm 번들이 커서 지연 로드한다.</span>
        </p>
      ) : (
        <Suspense fallback={<p className="empty">뷰어 로드 중…</p>}>
          <RerunViewer rrd={rrdUrl} width="100%" height="360px" />
        </Suspense>
      )}
    </div>
  );
}
