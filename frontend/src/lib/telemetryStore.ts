/**
 * 텔레메트리 저장소 — **수신과 렌더를 분리하는 계층.**
 *
 * ## 문제
 *
 * 실측 기준 신호가 차량당 초당 약 1,200건이고 4대면 **초당 5,100건**이 들어온다.
 * 이걸 그대로 React 상태에 넣으면 초당 5,100번 렌더가 예약된다. 배치 처리로 줄여도
 * 초당 40번(배치 도착률)이고, 각 렌더가 지도·차트를 건드리면 프레임이 남아나지 않는다.
 *
 * ## 해법 — 세 층으로 나눈다
 *
 * ```
 * SSE 수신  ──▶  가변 저장소(React 밖)  ──▶  구독자
 *  초당 40건       참조로 즉시 쓰기            ├─ 고빈도: rAF에서 직접 읽어 명령형 갱신
 *                  (setState 없음)            │         (지도·차트 — React 렌더 없음)
 *                                             └─ 저빈도: 4Hz로 스로틀된 알림
 *                                                       (카운터·목록 — useSyncExternalStore)
 * ```
 *
 * 핵심은 **수신 경로에 setState가 하나도 없다는 것**이다. 데이터는 가변 구조에 바로 쓰이고,
 * 화면 갱신 주기는 데이터 도착 주기와 완전히 분리된다. 지도와 차트는 React를 거치지 않고
 * 자기 rAF 루프에서 저장소를 읽어 캔버스/GL 레이어를 직접 갱신한다.
 */
import { RingBuffer } from "./ringBuffer";
import { assertLatLon, bearingDeg, type LatLon } from "./geo";

/** 차트에 보이는 창 = 30초. 20Hz ego_pose 기준 600점이면 충분하다. */
const SERIES_CAPACITY = 900;
const EVENT_CAPACITY = 300;

/** 급제동 임계. |accel| > 3.0 m/s^2 (0.3g 관례를 보수적으로 반올림) — docs/data-design.md */
const HARSH_ACCEL_MPS2 = 3.0;

export type FleetEventKind = "harsh_brake" | "sensor_dropout" | "low_confidence" | "epoch";

export interface FleetEvent {
  readonly id: string;
  readonly t: number;
  readonly vehicleId: string;
  readonly kind: FleetEventKind;
  readonly detail: string;
}

/** 인지된 객체 하나의 평면 발자국 — 지도 투영용. */
export interface PerceivedObject {
  readonly category: string;
  /** ENU 글로벌 미터 */
  readonly cx: number;
  readonly cy: number;
  readonly width: number;
  readonly length: number;
  readonly yaw: number;
  /** 박스 내 LiDAR 포인트 수. 0이면 미관측 = 저신뢰(§7.1) */
  readonly lidarPts: number;
  readonly visibility: string;
}

export interface VehicleState {
  readonly vehicleId: string;
  location: string;
  sceneName: string;
  /** 최신 위치. 지도가 매 프레임 읽는다. */
  pos: LatLon | null;
  prevPos: LatLon | null;
  headingDeg: number;
  speedMps: number;
  steeringRad: number;
  yawRate: number;
  /** 최근 인지 프레임 요약 */
  objectCount: number;
  zeroLidarCount: number;
  classes: Record<string, number>;
  /** 최신 키프레임의 인지 객체. 지도 투영에 쓴다. */
  objects: PerceivedObject[];
  /** 마지막 신호의 재생 시각(ms) */
  lastT: number;
  /** 이 차량이 지금까지 받은 레코드 수 — 처리량 표시용 */
  recordCount: number;
  series: {
    speed: RingBuffer;
    steering: RingBuffer;
    yawRate: RingBuffer;
  };
  trail: number[][]; // [lon, lat][] — GeoJSON 순서로 바로 쓴다
}

interface SignalBatch {
  vehicle_id: string;
  t: number;
  n: number;
  records: { e: string; c: string; t: number; v: Record<string, unknown> }[];
}

/** SSE로 오는 인지 산출 이벤트(키프레임 1건). */
interface PerceptionEvent {
  vehicle_id: string;
  location: string;
  t: number;
  n_objects: number;
  n_zero_lidar: number;
  classes: Record<string, number>;
  boxes?: {
    /** 중심 (ENU 글로벌 미터) */
    c: [number, number];
    /** (width, length) 미터 */
    s: [number, number];
    /** 길이 방향 방위 (rad) */
    yaw: number;
    cat: string;
    /** num_lidar_pts */
    lp: number;
    vis: string;
  }[];
}

const TRAIL_MAX = 400;

class TelemetryStore {
  private readonly vehicles = new Map<string, VehicleState>();
  private readonly events: FleetEvent[] = [];
  private listeners = new Set<() => void>();

  /** 저빈도 구독자에게 알릴 때 쓰는 스냅샷 버전. 값 자체는 의미 없다. */
  private version = 0;
  private notifyScheduled = false;

  /** 처리량 계측 — 초당 레코드/배치 */
  private windowRecords = 0;
  private windowBatches = 0;
  private windowStart = performance.now();
  recordsPerSec = 0;
  batchesPerSec = 0;
  /** 수신했으나 아직 화면에 반영되지 않은 레코드(=분리가 실제로 동작하는지 관측) */
  droppedFrames = 0;

  ensureVehicle(vehicleId: string, meta?: { location?: string; sceneName?: string }): VehicleState {
    let v = this.vehicles.get(vehicleId);
    if (!v) {
      v = {
        vehicleId,
        location: meta?.location ?? "",
        sceneName: meta?.sceneName ?? "",
        pos: null,
        prevPos: null,
        headingDeg: 0,
        speedMps: 0,
        steeringRad: 0,
        yawRate: 0,
        objectCount: 0,
        zeroLidarCount: 0,
        classes: {},
        objects: [],
        lastT: 0,
        recordCount: 0,
        series: {
          speed: new RingBuffer(SERIES_CAPACITY),
          steering: new RingBuffer(SERIES_CAPACITY),
          yawRate: new RingBuffer(SERIES_CAPACITY),
        },
        trail: [],
      };
      this.vehicles.set(vehicleId, v);
      this.scheduleNotify();
    } else if (meta) {
      if (meta.location) v.location = meta.location;
      if (meta.sceneName) v.sceneName = meta.sceneName;
    }
    return v;
  }

  /**
   * SSE 수신 경로. **여기서 setState를 호출하지 않는다.**
   * 가변 구조에 직접 쓰고, 저빈도 알림만 스로틀해서 예약한다.
   */
  ingestSignals(batch: SignalBatch): void {
    const v = this.ensureVehicle(batch.vehicle_id);
    v.lastT = batch.t;
    v.recordCount += batch.n;
    this.windowRecords += batch.n;
    this.windowBatches += 1;

    for (const r of batch.records) {
      const val = r.v;
      switch (r.c) {
        case "ego_pose": {
          const lat = val["lat"] as number | null;
          const lon = val["lon"] as number | null;
          if (lat == null || lon == null) break;
          const p = assertLatLon([lat, lon], "ingestSignals/ego_pose");
          if (v.pos) {
            v.prevPos = v.pos;
            // 정지 상태에서 방위각이 튀는 것을 막는다 — 1m 이상 움직였을 때만 갱신
            if (Math.abs(p[0] - v.pos[0]) + Math.abs(p[1] - v.pos[1]) > 1e-6) {
              v.headingDeg = bearingDeg(v.pos, p);
            }
          }
          v.pos = p;
          v.trail.push([lon, lat]);
          if (v.trail.length > TRAIL_MAX) v.trail.shift();
          break;
        }
        case "vehicle_monitor": {
          const speed = val["vehicle_speed"];
          if (typeof speed === "number") {
            v.speedMps = speed / 3.6; // vehicle_monitor는 km/h
            v.series.speed.push(r.t, v.speedMps);
          }
          const yaw = val["yaw_rate"];
          if (typeof yaw === "number") {
            v.yawRate = yaw;
            v.series.yawRate.push(r.t, yaw);
          }
          break;
        }
        case "steeranglefeedback": {
          const raw = val["value"];
          if (typeof raw === "number") {
            v.steeringRad = raw;
            v.series.steering.push(r.t, raw);
          }
          break;
        }
        case "pose": {
          const accel = val["accel"];
          if (Array.isArray(accel) && typeof accel[0] === "number") {
            const ax = accel[0] as number;
            if (Math.abs(ax) > HARSH_ACCEL_MPS2) {
              this.pushEvent({
                id: `${batch.vehicle_id}-${r.t}-${r.e}`,
                t: r.t,
                vehicleId: batch.vehicle_id,
                kind: "harsh_brake",
                detail: `종가속 ${ax.toFixed(2)} m/s²`,
              });
            }
          }
          break;
        }
        default:
          break;
      }
    }
    this.tickThroughput();
    this.scheduleNotify();
  }

  ingestPerception(p: PerceptionEvent): void {
    const v = this.ensureVehicle(p.vehicle_id, { location: p.location });
    v.objectCount = p.n_objects;
    v.zeroLidarCount = p.n_zero_lidar;
    v.classes = p.classes;
    // 인지 결과는 키프레임(2Hz)마다 통째로 교체된다 — 누적하지 않는다.
    // 객체는 사라지고 나타나므로 이전 프레임을 남기면 유령이 쌓인다.
    v.objects = (p.boxes ?? []).map((b) => ({
      category: b.cat,
      cx: b.c[0],
      cy: b.c[1],
      width: b.s[0],
      length: b.s[1],
      yaw: b.yaw,
      lidarPts: b.lp,
      visibility: b.vis,
    }));
    if (p.n_zero_lidar > 0) {
      this.pushEvent({
        id: `${p.vehicle_id}-${p.t}-lc`,
        t: p.t,
        vehicleId: p.vehicle_id,
        kind: "low_confidence",
        detail: `LiDAR 미관측 라벨 ${p.n_zero_lidar}/${p.n_objects}`,
      });
    }
    this.scheduleNotify();
  }

  markEpoch(): void {
    // 재생이 한 바퀴 돌았다. 궤적을 비우지 않으면 지도에 선이 순간이동한다.
    for (const v of this.vehicles.values()) {
      v.trail.length = 0;
      v.series.speed.clear();
      v.series.steering.clear();
      v.series.yawRate.clear();
    }
    this.pushEvent({
      id: `epoch-${Date.now()}`,
      t: 0,
      vehicleId: "-",
      kind: "epoch",
      detail: "재생 루프 — 새 replay_epoch",
    });
    this.scheduleNotify();
  }

  private pushEvent(e: FleetEvent): void {
    // 같은 사건이 연속 프레임에서 반복 발화하는 것을 막는다.
    const last = this.events[0];
    if (last && last.vehicleId === e.vehicleId && last.kind === e.kind && e.t - last.t < 500) return;
    this.events.unshift(e);
    if (this.events.length > EVENT_CAPACITY) this.events.pop();
  }

  private tickThroughput(): void {
    const now = performance.now();
    const dt = now - this.windowStart;
    if (dt >= 1000) {
      this.recordsPerSec = Math.round((this.windowRecords * 1000) / dt);
      this.batchesPerSec = Math.round((this.windowBatches * 1000) / dt);
      this.windowRecords = 0;
      this.windowBatches = 0;
      this.windowStart = now;
    }
  }

  // ── React 연동 (저빈도 구독자 전용) ─────────────────────────────────
  //
  // 고빈도 구독자(지도·차트)는 이 경로를 쓰지 않는다. 직접 rAF에서 읽는다.

  private scheduleNotify(): void {
    if (this.notifyScheduled) return;
    this.notifyScheduled = true;
    // 4Hz. 사람 눈에 카운터가 부드럽게 보이는 최소치이고, 도착률(40Hz)의 1/10이다.
    window.setTimeout(() => {
      this.notifyScheduled = false;
      this.version += 1;
      for (const l of this.listeners) l();
    }, 250);
  }

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  };

  /**
   * useSyncExternalStore용 스냅샷.
   *
   * **숫자(version)를 돌려주는 것이 중요하다.** 객체를 새로 만들어 돌려주면 React가 매번
   * 다르다고 판단해 무한 렌더에 빠진다. 실제 데이터는 컴포넌트가 getter로 직접 읽는다.
   */
  getSnapshot = (): number => this.version;

  listVehicles(): VehicleState[] {
    return [...this.vehicles.values()].sort((a, b) => a.vehicleId.localeCompare(b.vehicleId));
  }

  getVehicle(id: string): VehicleState | undefined {
    return this.vehicles.get(id);
  }

  listEvents(): readonly FleetEvent[] {
    return this.events;
  }
}

export const telemetryStore = new TelemetryStore();
