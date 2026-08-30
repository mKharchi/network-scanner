import { FLOOR_CONFIG, FLOOR_IDS, type FloorId } from "./floorConfig";

interface FloorSelectorProps {
  selectedFloor: FloorId;
  onSelectFloor: (floor: FloorId) => void;
  deviceCounts?: Partial<Record<FloorId, number>>;
}

export function FloorSelector({
  selectedFloor,
  onSelectFloor,
  deviceCounts,
}: FloorSelectorProps) {
  return (
    <div className="floor-selector" role="tablist" aria-label="Floor Selection">
      {FLOOR_IDS.map((floorId) => {
        const config = FLOOR_CONFIG[floorId];
        const isSelected = selectedFloor === floorId;
        const count = deviceCounts?.[floorId];

        return (
          <button
            key={floorId}
            role="tab"
            aria-selected={isSelected}
            className={`floor-selector__btn ${isSelected ? "floor-selector__btn--active" : ""}`}
            onClick={() => onSelectFloor(floorId)}
            type="button"
          >
            <span className="floor-selector__name">{config.name}</span>
            <span className="floor-selector__sub">{config.shortName}</span>
            {count !== undefined && (
              <span className="floor-selector__count" title={`${count} device(s) on ${config.name}`}>
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
