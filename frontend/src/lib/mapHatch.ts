import type * as maplibregl from 'maplibre-gl';
import { TOKENS } from '../theme/palette';

/** 결측(자료 없음) 면의 해치 패턴 이름. */
export const HATCH = 'hatch-missing';

/** 해치 패턴 이미지(45°, --hatch 선 / --prov-missing-bg 바탕) — fill-pattern용. 램프 최저색과 구분한다. */
export function addHatchImage(map: maplibregl.Map) {
  if (map.hasImage(HATCH)) return;
  const size = 16; const canvas = document.createElement('canvas'); canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d'); if (!ctx) return;
  ctx.fillStyle = TOKENS['prov-missing-bg']; ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = TOKENS.hatch; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, size); ctx.lineTo(size, 0); ctx.moveTo(-4, 4); ctx.lineTo(4, -4); ctx.moveTo(size - 4, size + 4); ctx.lineTo(size + 4, size - 4); ctx.stroke();
  map.addImage(HATCH, ctx.getImageData(0, 0, size, size), { pixelRatio: 2 });
}
