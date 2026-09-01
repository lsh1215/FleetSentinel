-- FleetSentinel — ClickHouse 스키마
--
-- ⚠️ 이 파일의 핵심은 **_raw 테이블을 직접 질의하지 않는다**는 규약이다.
--
-- Flink→ClickHouse 구간은 at-least-once 다. ClickHouse 가 2PC 를 못 하므로
-- 체크포인트 복구 시 같은 레코드가 다시 쓰인다(SDD S-7). ReplacingMergeTree 가
-- 그걸 흡수하지만 **머지 시점**에만 지우므로, 머지 전 질의는 중복을 본다.
--
-- 그래서 exactly-once 가 **읽기 시점에 닫힌다**(SDD L-14). 질의가 FINAL 을 붙이는 걸
-- 잊으면 집계가 조용히 부풀어오르고, 그건 유실보다 찾기 어렵다.
--
-- 해소책으로 **FINAL 을 박아둔 뷰**를 만들고 애플리케이션은 뷰만 본다.
-- 잊을 수 있는 것을 잊을 수 없게 만드는 것이 요점이다.

CREATE DATABASE IF NOT EXISTS fleet;

-- ────────────────────────────────────────────────────────────────────────
-- ① 신호 (vehicle-signal.avsc)
-- ────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fleet.signals_raw
(
    -- 전송 봉투. 이 3튜플이 자연 키이자 dedup 키다(data-design.md §5.0).
    vehicle_id   LowCardinality(String),
    boot_id      String,
    seq          UInt64,

    scene_id     LowCardinality(String),
    channel      LowCardinality(String),

    sensor_time  DateTime64(6, 'UTC'),   -- 센서 클럭. 정본 시간축
    log_time     DateTime64(6, 'UTC'),
    ingest_time  DateTime64(6, 'UTC') DEFAULT now64(6),

    -- 채널마다 필드가 달라 맵으로 담는다. 타입별로 셋인 이유는
    -- Avro union 을 피하기 위해서다(data-design.md §5.1).
    values_num   Map(String, Float64),
    values_vec   Map(String, Array(Float64)),
    values_str   Map(String, String),

    -- Flink 가 파생한다. 변환 실패 시 NULL 이고 행은 유지된다(무손실).
    lat          Nullable(Float64),
    lon          Nullable(Float64)
)
ENGINE = ReplacingMergeTree(ingest_time)
-- 멱등 upsert 키. 같은 (vehicle_id, boot_id, seq)가 두 번 오면 머지 때 하나만 남는다.
ORDER BY (vehicle_id, boot_id, seq)
PARTITION BY toYYYYMMDD(sensor_time)
-- 시간 범위 질의가 파티션 프루닝만으로는 부족해서 스킵 인덱스를 둔다.
TTL toDateTime(sensor_time) + INTERVAL 10 YEAR;

-- ────────────────────────────────────────────────────────────────────────
-- ② 인지 산출 (perception-object.avsc)
-- ────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fleet.perception_raw
(
    vehicle_id    LowCardinality(String),
    boot_id       String,
    seq           UInt64,

    scene_id      LowCardinality(String),
    sample_id     String,
    sensor_time   DateTime64(6, 'UTC'),
    ingest_time   DateTime64(6, 'UTC') DEFAULT now64(6),

    track_id      String,
    category      LowCardinality(String),
    attribute     LowCardinality(Nullable(String)),

    center_x      Float64,
    center_y      Float64,
    center_z      Float64,
    size_w        Float64,
    size_l        Float64,
    size_h        Float64,
    rot_w         Float64,
    rot_x         Float64,
    rot_y         Float64,
    rot_z         Float64,

    -- 품질 축. num_lidar_pts=0 이 23.1% 이고 큐레이션 1급 축이다(data-design.md §8.1).
    visibility    LowCardinality(String),
    num_lidar_pts Int32,
    num_radar_pts Int32,

    lat           Nullable(Float64),
    lon           Nullable(Float64)
)
ENGINE = ReplacingMergeTree(ingest_time)
ORDER BY (vehicle_id, boot_id, seq)
PARTITION BY toYYYYMMDD(sensor_time);

-- ────────────────────────────────────────────────────────────────────────
-- ③ 원시 로그 참조 (segment-ref.avsc) — 클립 카탈로그
-- ────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fleet.segments_raw
(
    vehicle_id      LowCardinality(String),
    boot_id         String,
    seq             UInt64,

    segment_id      String,
    scene_id        LowCardinality(Nullable(String)),
    -- 파일은 오브젝트 스토리지에 있고 여기엔 참조만 있다(Claim-Check, SDD S-1).
    blob_uri        String,
    t_start         DateTime64(6, 'UTC'),
    t_end           DateTime64(6, 'UTC'),
    ingest_time     DateTime64(6, 'UTC') DEFAULT now64(6),

    sensor_channels Array(LowCardinality(String)),
    size_bytes      UInt64,
    checksum        String,
    sample_count    UInt32,

    -- DROPPED 는 트리거 예산을 넘겨 업로드를 포기한 클립이다.
    -- 파일은 없지만 사실은 남는다 — 목표는 유실 0이 아니라 버린 것을 아는 것이다.
    state           Enum8('UPLOADED' = 1, 'DROPPED' = 2),
    drop_reason     Nullable(String),

    calibration     Map(String, String)
)
ENGINE = ReplacingMergeTree(ingest_time)
ORDER BY (vehicle_id, boot_id, seq)
PARTITION BY toYYYYMMDD(t_start);

-- ────────────────────────────────────────────────────────────────────────
-- FINAL 뷰 — **애플리케이션은 이것만 본다**
--
-- _raw 를 직접 읽으면 머지 전 중복이 보인다. 뷰에 FINAL 을 박아두면
-- 질의하는 쪽이 그 사실을 몰라도 정확한 결과를 얻는다(SDD L-14 해소책).
--
-- 대가: FINAL 은 읽기 시점에 병합하므로 비용이 있다. ORDER BY 접두사로
-- 필터하면(vehicle_id → boot_id → seq) 병합 대상이 줄어든다.
-- ────────────────────────────────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS fleet.signals AS
SELECT * FROM fleet.signals_raw FINAL;

CREATE VIEW IF NOT EXISTS fleet.perception AS
SELECT * FROM fleet.perception_raw FINAL;

CREATE VIEW IF NOT EXISTS fleet.segments AS
SELECT * FROM fleet.segments_raw FINAL;

-- ────────────────────────────────────────────────────────────────────────
-- 관측 — 중복이 실제로 얼마나 있는지 본다
--
-- 이 뷰가 0 이 아니라고 오류인 것은 아니다. 머지가 아직 안 일어났다는 뜻이고,
-- FINAL 뷰를 쓰면 결과는 정확하다. 다만 **이 값이 계속 자라면** 머지가
-- 따라가지 못하는 것이므로 파티션 전략이나 삽입 배치를 봐야 한다.
-- ────────────────────────────────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS fleet.dup_pressure AS
SELECT
    'signals'    AS table,
    count()      AS rows_raw,
    uniqExact((vehicle_id, boot_id, seq)) AS rows_distinct,
    rows_raw - rows_distinct              AS pending_dupes
FROM fleet.signals_raw
UNION ALL
SELECT 'perception', count(), uniqExact((vehicle_id, boot_id, seq)),
       count() - uniqExact((vehicle_id, boot_id, seq))
FROM fleet.perception_raw
UNION ALL
SELECT 'segments', count(), uniqExact((vehicle_id, boot_id, seq)),
       count() - uniqExact((vehicle_id, boot_id, seq))
FROM fleet.segments_raw;

-- 차량별 수신 진행 — 결번이 곧 유실이므로 seq 연속성을 여기서 본다.
CREATE VIEW IF NOT EXISTS fleet.vehicle_progress AS
SELECT
    vehicle_id,
    boot_id,
    min(seq)                    AS first_seq,
    max(seq)                    AS last_seq,
    count()                     AS received,
    last_seq - first_seq + 1    AS expected,
    expected - received         AS missing   -- > 0 이면 결번 = 유실
FROM fleet.signals FINAL
GROUP BY vehicle_id, boot_id;
