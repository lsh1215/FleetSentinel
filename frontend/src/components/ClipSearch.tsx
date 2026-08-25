import { useEffect, useMemo, useState } from "react";

/**
 * 클립 검색 — 시나리오 마이닝의 프론트엔드.
 *
 * 조건 태그로 학습용 클립을 찾는 화면이다. 데이터 엔진(§sdd 3 S-8)의 입구이며,
 * 결과 행에는 오브젝트 스토리지의 `blob_uri`가 실려 있다 — 경량 경로(카탈로그)와
 * 중량 경로(원본 로그)가 여기서 만난다(Claim-Check).
 *
 * 태그가 희소하다는 사실(활성 강우 1/10)을 UI가 감추지 않는다. 결과 0건이 나오는
 * 조건 조합을 그대로 보여주는 편이, 데이터가 충분한 척하는 것보다 낫다.
 */
interface Clip {
  clip_id: string;
  vehicle_id: string;
  location: string;
  description: string;
  tags: string[];
  duration_s: number;
  n_objects: number;
  n_zero_lidar: number;
  blob_uri: string;
}

const TAG_LABEL: Record<string, string> = {
  night: "야간",
  day_inferred: "주간(추정)",
  rain: "우천",
  after_rain: "비 온 뒤",
  peds: "보행자",
  cyclist: "자전거",
  construction: "공사",
  intersection: "교차로",
  turn: "회전",
  parked: "주차",
  bus: "버스",
  truck: "트럭",
  hard_light: "역광",
};

export function ClipSearch({ onSelect }: { onSelect: (vehicleId: string) => void }) {
  const [clips, setClips] = useState<Clip[]>([]);
  const [active, setActive] = useState<Set<string>>(new Set());

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/clips", { signal: ctrl.signal })
      .then((r) => r.json())
      .then(setClips)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  const allTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of clips) for (const t of c.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [clips]);

  // AND 조건 — 선택한 태그를 모두 가진 클립만. 실제 마이닝 질의의 의미와 같다.
  const results = useMemo(
    () => (active.size === 0 ? clips : clips.filter((c) => [...active].every((t) => c.tags.includes(t)))),
    [clips, active],
  );

  const toggle = (t: string) =>
    setActive((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });

  return (
    <div className="panel clip-panel">
      <div className="panel-head">
        <h2>클립 검색</h2>
        <span className="muted">
          {results.length}/{clips.length}
        </span>
      </div>

      <div className="tags">
        {allTags.map(([t, n]) => (
          <button
            key={t}
            className={active.has(t) ? "tag on" : "tag"}
            onClick={() => toggle(t)}
            title={`${n}건`}
          >
            {TAG_LABEL[t] ?? t}
            <i>{n}</i>
          </button>
        ))}
      </div>

      <ul className="clips">
        {results.map((c) => (
          <li key={c.clip_id}>
            <button className="clip" onClick={() => onSelect(c.vehicle_id)}>
              <div className="clip-top">
                <b>{c.clip_id}</b>
                <span className="muted">{c.duration_s}s · {c.location}</span>
              </div>
              <p className="clip-desc">{c.description}</p>
              <div className="clip-meta">
                <span>객체 {c.n_objects}</span>
                <span className={c.n_zero_lidar > 0 ? "warn" : ""}>
                  미관측 {c.n_zero_lidar}
                </span>
                <code title="Claim-Check — 원본 로그 위치">{c.blob_uri.split("/").pop()}</code>
              </div>
            </button>
          </li>
        ))}
        {results.length === 0 && clips.length > 0 && (
          <li className="empty">
            조건에 맞는 클립이 없다. 실데이터의 태그가 희소해서 생기는 결과이고,
            이럴 때 시뮬로 보강한다.
          </li>
        )}
      </ul>
    </div>
  );
}
