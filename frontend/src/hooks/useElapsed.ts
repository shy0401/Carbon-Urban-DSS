import { useEffect, useState } from 'react';

/** Seconds since ``active`` turned true (0 while inactive). For "처음 계산 중" notices on slow first loads. */
export function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return undefined; }
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return seconds;
}

/** 지역 입력을 처음 읽을 때(1~3분) 기다리는 사람에게 보여 줄 문장 (사용성 검토 F3·F6). */
export function slowLoadText(seconds: number): string {
  if (seconds < 8) return '구역 안 자료를 모으고 있습니다.';
  return `이 지역 자료를 처음 읽는 중입니다(${seconds}초). 처음 한 번은 1~3분 걸리고, 그다음부터는 바로 나옵니다.`;
}
