"""SIGKILL 테스트용 자식 프로세스. WAL에 쓰면서 게이트웨이로 배송한다.

부모가 임의 시점에 SIGKILL하므로 **정리할 기회가 없다**. 재시작 시 커밋 지점부터
재전송하고, 그 결과 게이트웨이 로그에 중복이 생기는 것이 정상이다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleetsentinel_ingest.shipping import LoopbackGateway, WalShipper  # noqa: E402
from fleetsentinel_ingest.wal import Wal  # noqa: E402

PAYLOAD_FILLER = b"x" * 320


def payload_for(seq: int) -> bytes:
    """`seq`에서 결정되는 페이로드. 내용이 어긋나면 배송 정렬이 깨진 것이다."""
    return b"p" + seq.to_bytes(8, "little") + PAYLOAD_FILLER


def main() -> None:
    wal_dir, log_path, limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    every_n = int(sys.argv[4]) if len(sys.argv) > 4 else 512

    with Wal(wal_dir) as wal:
        # 재시작이면 다음 `seq`를 알아야 페이로드를 맞출 수 있다.
        nxt = 0
        for rec in wal.read_from(0):
            nxt = rec.seq + 1
        nxt = max(nxt, wal.committed_seq + 1)

        holder: dict[str, WalShipper] = {}
        gw = LoopbackGateway(
            log_path=log_path,
            on_ack=lambda s: holder["shipper"].on_ack(s),
            every_n=every_n,
            every_s=10.0,  # 개수 조건만 쓰게 해서 ack이 뒤처지도록 만든다
        )
        shipper = WalShipper(wal, gw, max_inflight=1 << 20)
        holder["shipper"] = shipper

        for i in range(limit):
            seq = wal.append(payload_for(nxt + i))
            assert seq == nxt + i, f"seq 정렬 깨짐: {seq} != {nxt + i}"
            if i % 32 == 31:
                shipper.pump()

        shipper.pump()
        gw.flush_ack()
        print(f"appended={limit} sent={shipper.stats.sent} acked={shipper.stats.acked}")


if __name__ == "__main__":
    main()
