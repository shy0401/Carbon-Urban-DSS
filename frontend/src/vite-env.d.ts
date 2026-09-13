/// <reference types="vite/client" />

declare namespace GeoJSON {
  interface Geometry {
    type: string;
    coordinates?: unknown;
  }
  interface Feature<G = Geometry, P = Record<string, unknown>> {
    type: 'Feature';
    geometry: G;
    properties: P | null;
    id?: string | number;
  }
  interface FeatureCollection<G = Geometry, P = Record<string, unknown>> {
    type: 'FeatureCollection';
    features: Array<Feature<G, P>>;
  }
}
