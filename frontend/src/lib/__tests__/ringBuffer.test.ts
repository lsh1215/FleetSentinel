import { describe, expect, it } from "vitest";
import { RingBuffer } from "../ringBuffer";

describe("RingBuffer", () => {
  it("용량을 넘으면 가장 오래된 것을 덮어써 길이가 상수로 유지된다", () => {
    const rb = new RingBuffer(3);
    for (let i = 0; i < 10; i += 1) rb.push(i, i * 2);
    expect(rb.length).toBe(3);
    const [xs, ys] = rb.view();
    expect([...xs]).toEqual([7, 8, 9]);
    expect([...ys]).toEqual([14, 16, 18]);
  });

  it("순환한 뒤에도 view()가 시간순으로 편다", () => {
    // 링 버퍼는 물리적으로 순환하므로 그대로 넘기면 차트가 뒤엉킨다.
    const rb = new RingBuffer(4);
    for (const v of [1, 2, 3, 4, 5, 6]) rb.push(v, v);
    const [xs] = rb.view();
    expect([...xs]).toEqual([3, 4, 5, 6]);
  });

  it("아직 채워지지 않았으면 채운 만큼만 돌려준다", () => {
    const rb = new RingBuffer(5);
    rb.push(1, 10);
    rb.push(2, 20);
    const [xs, ys] = rb.view();
    expect(xs.length).toBe(2);
    expect([...ys]).toEqual([10, 20]);
  });

  it("변경이 없으면 같은 배열 인스턴스를 재사용한다(rAF가 초당 60회 호출한다)", () => {
    const rb = new RingBuffer(4);
    rb.push(1, 1);
    const [a] = rb.view();
    const [b] = rb.view();
    expect(a).toBe(b); // 참조 동일 — 매 프레임 새로 만들지 않는다
    rb.push(2, 2);
    const [c] = rb.view();
    expect(c).not.toBe(a);
  });

  it("last는 가장 최근 값이고 비어 있으면 undefined다", () => {
    const rb = new RingBuffer(3);
    expect(rb.last).toBeUndefined();
    rb.push(1, 42);
    rb.push(2, 99);
    expect(rb.last).toBe(99);
  });

  it("clear 후에는 비어 있다", () => {
    const rb = new RingBuffer(3);
    rb.push(1, 1);
    rb.clear();
    expect(rb.length).toBe(0);
    expect(rb.view()[0].length).toBe(0);
  });
});
