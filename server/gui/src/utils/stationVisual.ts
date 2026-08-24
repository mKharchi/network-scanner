export type StationVisual =
  | 'healthy'
  | 'warning'
  | 'critical'
  | 'isolated'
  | 'offline'
  | 'empty';

export const STATION_VISUAL_LABEL: Record<StationVisual, string> = {
  healthy: 'Healthy',
  warning: 'Warning',
  critical: 'Critical',
  isolated: 'Isolated',
  offline: 'Offline',
  empty: 'Empty',
};

const STATION_VISUALS = new Set<StationVisual>([
  'healthy',
  'warning',
  'critical',
  'isolated',
  'offline',
  'empty',
]);

export function stationVisual(input: {
  client_id?: string;
  client_state?: 'ONLINE' | 'OFFLINE' | 'ISOLATED';
  health_status?: string | null;
  showsClients: boolean;
}): StationVisual {
  if (!input.showsClients || !input.client_id) return 'empty';
  if (input.health_status && STATION_VISUALS.has(input.health_status as StationVisual)) {
    return input.health_status as StationVisual;
  }
  if (input.client_state === 'ISOLATED') return 'isolated';
  if (input.client_state === 'ONLINE') return 'healthy';
  return 'offline';
}
