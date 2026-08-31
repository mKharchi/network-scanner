export type FloorId = 0 | 1 | 2;

export interface FloorConfig {
  id: FloorId;
  name: string;
  shortName: string;
  subtitle: string;
  description: string;
  elevationMeters: number;
  hasFormationRooms: boolean;
  hasTables: boolean;
  hasReferenceClients: boolean;
  objects: string[];
}

export const FLOOR_IDS: readonly FloorId[] = [0, 1, 2] as const;

export const FLOOR_CONFIG: Record<FloorId, FloorConfig> = {
  0: {
    id: 0,
    name: "Floor 0",
    shortName: "Ground",
    subtitle: "Ground Floor Level",
    description: "Open floor area. No fixed formation rooms or reference PCs.",
    elevationMeters: 0.0,
    hasFormationRooms: false,
    hasTables: false,
    hasReferenceClients: false,
    objects: ["open-floor-grid"],
  },
  1: {
    id: 1,
    name: "Floor 1",
    shortName: "Floor 1",
    subtitle: "Training Level 1 (Reference)",
    description: "Formation rooms, stairs, PC clusters & fixed reference clients.",
    elevationMeters: 3.0,
    hasFormationRooms: true,
    hasTables: true,
    hasReferenceClients: true,
    objects: ["formationRooms", "stairs", "tables", "referenceClients"],
  },
  2: {
    id: 2,
    name: "Floor 2",
    shortName: "Floor 2",
    subtitle: "Training Level 2",
    description: "Upper level with Formation Room 1 & 2 in identical relative position. No fixed PCs.",
    elevationMeters: 6.0,
    hasFormationRooms: true,
    hasTables: false,
    hasReferenceClients: false,
    objects: ["formationRooms", "stairs"],
  },
};
