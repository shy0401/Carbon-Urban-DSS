/**
 * 결측 값 (DESIGN.md 5): 값 자리에 "—", 아래에 사유 한 줄. 0이나 빈칸으로 보이지 않게 한다.
 * 화면 낭독기에는 "자료 없음"으로 읽힌다.
 */
export function MissingValue({ reason, inline = false }: { reason?: string; inline?: boolean }) {
  return <span className={`missing-value${inline ? ' inline' : ''}`} title="자료 미확보">
    <span className="mv-dash" aria-hidden="true">—</span><span className="sr-only">자료 없음</span>
    {reason && <span className="mv-reason">{reason}</span>}
  </span>;
}
