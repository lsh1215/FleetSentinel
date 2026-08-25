/**
 * 고정 크기 링 버퍼 — 시계열을 상수 메모리로 유지한다.
 *
 * 신호가 차량당 초당 1,200건 넘게 들어오므로 배열에 계속 push하면 몇 분 만에 수십만
 * 원소가 되고 GC 압력과 차트 렌더가 함께 무너진다. 링 버퍼는 **가장 오래된 것을 덮어써서**
 * 길이를 고정한다.
 *
 * uPlot이 요구하는 형태가 열 지향(`[xs[], ys[]]`)이라 내부도 **두 개의 TypedArray**로
 * 들고 있다가 그대로 넘긴다 — 매 프레임 객체 배열을 만들어 변환하면 그 자체가 병목이다.
 */
export class RingBuffer {
  private readonly xs: Float64Array;
  private readonly ys: Float64Array;
  private head = 0;
  private count = 0;

  /** uPlot에 넘길 정렬된 뷰. push마다 다시 만들지 않고 재사용한다. */
  private readonly viewX: Float64Array;
  private readonly viewY: Float64Array;
  private viewDirty = true;

  constructor(readonly capacity: number) {
    this.xs = new Float64Array(capacity);
    this.ys = new Float64Array(capacity);
    this.viewX = new Float64Array(capacity);
    this.viewY = new Float64Array(capacity);
  }

  push(x: number, y: number): void {
    this.xs[this.head] = x;
    this.ys[this.head] = y;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) this.count += 1;
    this.viewDirty = true;
  }

  get length(): number {
    return this.count;
  }

  /** 가장 최근 값. 비어 있으면 undefined. */
  get last(): number | undefined {
    if (this.count === 0) return undefined;
    return this.ys[(this.head - 1 + this.capacity) % this.capacity];
  }

  /**
   * 시간순으로 정렬된 (xs, ys) 쌍을 돌려준다.
   *
   * 링 버퍼는 물리적으로 순환하므로 그대로 넘기면 차트가 뒤엉킨다. 여기서 한 번 펴주되
   * **버퍼가 바뀌지 않았으면 이전 결과를 재사용**한다(rAF 루프가 초당 수십 번 호출한다).
   */
  view(): [Float64Array, Float64Array] {
    if (!this.viewDirty) return [this.subarrayX, this.subarrayY];
    const start = this.count < this.capacity ? 0 : this.head;
    for (let i = 0; i < this.count; i += 1) {
      const src = (start + i) % this.capacity;
      this.viewX[i] = this.xs[src]!;
      this.viewY[i] = this.ys[src]!;
    }
    this.viewDirty = false;
    this.subarrayX = this.viewX.subarray(0, this.count);
    this.subarrayY = this.viewY.subarray(0, this.count);
    return [this.subarrayX, this.subarrayY];
  }

  private subarrayX: Float64Array = new Float64Array(0);
  private subarrayY: Float64Array = new Float64Array(0);

  clear(): void {
    this.head = 0;
    this.count = 0;
    this.viewDirty = true;
  }
}
