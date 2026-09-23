import { DATA_CLASS, type DataClass } from '../lib/format';

/** 관측·계산·추정·시나리오·대체·미확보 — the provenance of a displayed number. */
export function DataClassChip({ value }: { value: DataClass }) {
  const item = DATA_CLASS[value];
  return <span className={`dc-chip ${item.css}`} title={item.hint}>{item.label}</span>;
}
