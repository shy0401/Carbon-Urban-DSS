import { AlertCircle, Database, RefreshCw } from 'lucide-react';

export function LoadingState({ label = '데이터를 불러오는 중입니다' }: { label?: string }) {
  return <div className="state-panel"><span className="spinner" aria-hidden="true" /><p>{label}</p></div>;
}

export function ErrorState({ message, onRetry }: { message?: string | null; onRetry: () => void }) {
  return (
    <div className="state-panel state-error">
      <AlertCircle size={30} />
      <strong>데이터를 불러오지 못했습니다</strong>
      <p>{message ?? 'API 서버 연결 상태를 확인해 주세요.'}</p>
      <button className="button secondary" onClick={onRetry}><RefreshCw size={15} />다시 시도</button>
    </div>
  );
}

export function EmptyState({ title = '표시할 자료가 없습니다', description }: { title?: string; description?: string }) {
  return <div className="state-panel compact"><Database size={24} /><strong>{title}</strong>{description && <p>{description}</p>}</div>;
}
