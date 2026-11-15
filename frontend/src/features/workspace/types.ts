export interface OutlineNode {
  id: string;
  text: string;
  level: number;
  role: string;
  children: OutlineNode[];
}

export interface PageInfo {
  index: number;
  width_pt: number;
  height_pt: number;
  blank: boolean;
}

/** A highlighted region on a rendered page (from findings, Phase 3+). */
export interface Overlay {
  id: string;
  page: number;
  bbox: [number, number, number, number];
  tone: 'critical' | 'high' | 'medium' | 'low' | 'info';
  label: string;
}
