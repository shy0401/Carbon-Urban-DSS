import type { QualityScores as Scores } from '../types';

type ComponentScoreKey = 'coverage_score' | 'completeness_score' | 'temporal_score' | 'spatial_match_score';

const fields: Array<[ComponentScoreKey, string]> = [
  ['coverage_score', '범위 충족'],
  ['completeness_score', '값 완전성'],
  ['temporal_score', '시간 적합성'],
  ['spatial_match_score', '공간 매칭'],
];

export function QualityScores({ scores }: { scores: Scores | null | undefined }) {
  return <div className="quality-scores">
    {fields.map(([key, label]) => { const dimension = dimensionFor(key); const value = scores?.[key] ?? scores?.dimensions?.[dimension]?.score; const evidence = scores?.dimensions?.[dimension]?.evidence; return <div className="score-row" key={key}><div><span>{label}</span><strong>{scoreText(value)}</strong></div><div className="score-track"><span style={{ width: scoreWidth(value) }} /></div>{evidence && <small>{evidence}</small>}</div>; })}
    <div className="overall-score"><span>종합 품질</span><strong>{scoreText(scores?.overall)}</strong><small>구성 점수와 함께 해석하세요</small></div>
  </div>;
}

function scoreText(value: number | null | undefined) { return value === null || value === undefined ? '미산정' : `${Math.round(value * 100)}%`; }
function scoreWidth(value: number | null | undefined) { return value === null || value === undefined ? '0%' : `${Math.max(0, Math.min(1, value)) * 100}%`; }
function dimensionFor(key: ComponentScoreKey): 'coverage' | 'completeness' | 'temporal' | 'spatial_match' { return key.replace('_score', '') as 'coverage' | 'completeness' | 'temporal' | 'spatial_match'; }
