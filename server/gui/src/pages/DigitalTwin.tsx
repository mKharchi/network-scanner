import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import {
  api,
  SpatialSceneResponse,
  SpatialSceneNode,
  SpatialReplayResponse,
  RogueDeviceSummary,
  SpatialSensor,
  SpatialLocationEvent,
} from '../api/client';
import { Card, MetricCard } from '../components/Card';
import { Badge } from '../components/Badge';
import { Notice } from '../components/States';
import { Button } from '../components/Button';
import '../styles/operations.css';
import {
  TbEye,
  TbRadar,
  TbActivity,
  TbPlayerPlay,
  TbPlayerPause,
  TbPlayerSkipForward,
  TbPlayerSkipBack,
  TbReload,
  TbZoomIn,
  TbZoomOut,
  TbFocusCentered,
  TbCamera,
  TbShieldLock,
  TbDeviceDesktop,
  TbServer,
  TbRouter,
  TbAntenna,
  TbAlertTriangle,
  TbNetwork,
} from 'react-icons/tb';

type ViewMode = 'physical' | 'topology' | 'threat' | 'traffic' | 'ar';
type ZoneFilter = 'all' | 'threats' | 'datacenter' | 'workstations' | 'perimeter' | 'sensors';
type CameraPreset = 'iso' | 'top' | 'front' | 'threats';

function normaliseIdentity(value: unknown): string {
  return String(value ?? '').trim().replace(/[-_]/g, ':').toLowerCase();
}

function identityVariants(value: unknown): string[] {
  const normalized = normaliseIdentity(value);
  if (!normalized) return [];
  const withoutSensorPrefix = normalized.replace(/^(sensor|probe)(?::|\\s)+/, '');
  return Array.from(new Set([normalized, withoutSensorPrefix].filter(Boolean)));
}

function nodeIdentityKeys(node: SpatialSceneNode): Set<string> {
  const metadata = node.metadata ?? {};
  const values = [
    node.mac,
    node.ip,
    node.name,
    node.label,
    metadata.sensor_id,
    metadata.client_id,
    metadata.client_hostname,
  ];
  return new Set(values.flatMap(identityVariants));
}

function nodeSpatialKey(node: SpatialSceneNode): string | null {
  const { x, y, z } = node.position;
  if (![x, y, z].every((value) => Number.isFinite(value))) return null;
  return `${x.toFixed(2)}:${y.toFixed(2)}:${z.toFixed(2)}:${normaliseIdentity(node.location_label)}`;
}

function isThreatLikeNode(node: SpatialSceneNode): boolean {
  return node.is_rogue || node.status === 'rogue' || node.status === 'suspicious' ||
    node.risk === 'high' || node.risk === 'critical';
}

function isNearSensorNode(candidate: SpatialSceneNode, sensor: SpatialSceneNode): boolean {
  if (normaliseIdentity(candidate.location_label) !== normaliseIdentity(sensor.location_label)) return false;
  const dx = candidate.position.x - sensor.position.x;
  const dy = candidate.position.y - sensor.position.y;
  const dz = candidate.position.z - sensor.position.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz) <= 1.25;
}

/**
 * The API can briefly return one endpoint in both the sensor and network-device
 * collections while sensor synchronization is catching up. Keep the sensor
 * representation (it has the authoritative spatial role) and remove only the
 * matching non-sensor node and its threat marker/edges.
 */
function dedupeSensorNodes(scene: SpatialSceneResponse): SpatialSceneResponse {
  const sensorNodes = scene.nodes.filter((node) => node.is_sensor || node.type === 'sensor');
  if (sensorNodes.length === 0) return scene;

  const sensorKeys = new Set(sensorNodes.flatMap((node) => Array.from(nodeIdentityKeys(node))));
  const sensorSpatialKeys = new Set(sensorNodes.map(nodeSpatialKey).filter(Boolean));
  const duplicateIds = new Set<string>();

  scene.nodes.forEach((node) => {
    if (node.is_sensor || node.type === 'sensor') return;
    const sharesIdentity = Array.from(nodeIdentityKeys(node)).some((key) => sensorKeys.has(key));
    const sharesPosition = nodeSpatialKey(node) !== null && sensorSpatialKeys.has(nodeSpatialKey(node));
    const isNearbySensorDuplicate = isThreatLikeNode(node) && sensorNodes.some((sensor) => isNearSensorNode(node, sensor));
    if (sharesIdentity || sharesPosition || isNearbySensorDuplicate) duplicateIds.add(node.id);
  });

  if (duplicateIds.size === 0) return scene;

  const nodes = scene.nodes.filter((node) => !duplicateIds.has(node.id));
  const threats = scene.threats.filter((threat) => !duplicateIds.has(threat.node_id));
  const edges = scene.edges.filter((edge) => !duplicateIds.has(edge.source) && !duplicateIds.has(edge.target));

  return {
    ...scene,
    nodes,
    threats,
    edges,
    meta: {
      ...scene.meta,
      total_nodes: nodes.length,
      total_edges: edges.length,
      total_threats: threats.length,
    },
  };
}

export function DigitalTwinPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Data states
  const [scene, setScene] = useState<SpatialSceneResponse | null>(null);
  const [replay, setReplay] = useState<SpatialReplayResponse | null>(null);
  const [rogueList, setRogueList] = useState<RogueDeviceSummary[]>([]);
  const [sensorsList, setSensorsList] = useState<SpatialSensor[]>([]);
  const [eventsList, setEventsList] = useState<SpatialLocationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [sceneLoadError, setSceneLoadError] = useState<string | null>(null);

  // View & Filter states
  const [viewMode, setViewMode] = useState<ViewMode>('physical');
  const [zoneFilter, setZoneFilter] = useState<ZoneFilter>('all');
  const [selectedFloor, setSelectedFloor] = useState<number | 'all'>('all');
  const CENTER_FLOORS = [0, 1, 2] as const;
  const FLOOR_HEIGHT = 3;
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('search') || '');
  const requestedClientId = searchParams.get('client');
  const [showLinks, setShowLinks] = useState(true);
  const [showLabels, setShowLabels] = useState<'threats' | 'all' | 'none'>('threats');

  // 3D Camera & Interaction states
  const [yaw, setYaw] = useState<number>(45); // horizontal rotation in degrees
  const [pitch, setPitch] = useState<number>(32); // vertical tilt in degrees
  const [zoom, setZoom] = useState<number>(1.0);
  const [panX, setPanX] = useState<number>(0);
  const [panY, setPanY] = useState<number>(0);
  const isDraggingRef = useRef(false);
  const didDragRef = useRef(false);
  const dragModeRef = useRef<'rotate' | 'pan'>('rotate');
  const lastMousePosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Replay states
  const [isReplaying, setIsReplaying] = useState(false);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState<number>(1);
  const replayTimerRef = useRef<number | null>(null);

  // AR Video Stream state
  const [arCameraActive, setArCameraActive] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Apply Camera Presets
  const applyCameraPreset = (preset: CameraPreset) => {
    switch (preset) {
      case 'top':
        setYaw(0);
        setPitch(85);
        setZoom(1.05);
        setPanX(0);
        setPanY(0);
        break;
      case 'iso':
        setYaw(45);
        setPitch(32);
        setZoom(1.0);
        setPanX(0);
        setPanY(0);
        break;
      case 'front':
        setYaw(0);
        setPitch(15);
        setZoom(1.0);
        setPanX(0);
        setPanY(0);
        break;
      case 'threats':
        setYaw(35);
        setPitch(40);
        setZoom(1.4);
        setPanX(-160);
        setPanY(20);
        break;
    }
  };

  // Load all spatial scene, rogue devices, sensor and replay data
  const loadSceneData = async () => {
    try {
      setLoading(true);
      setSceneLoadError(null);
      const [spatialData, replayData, rogueData, sensorData, eventData] = await Promise.all([
        // Match Rogue Device Manager: include the full scored inventory, not only
        // endpoints seen inside the live recency window.
        api.getSpatialScene(
          selectedFloor !== 'all' ? { floor: selectedFloor, active_only: false } : { active_only: false },
        ).catch(() => null),
        api.getSpatialReplay().catch(() => null),
        api.listRogueDevices({ min_score: 20, active_only: false }).catch(() => ({ items: [], total: 0 })), 
        api.listSensors().catch(() => ({ items: [] })),
        api.listSpatialEvents(50).catch(() => ({ items: [] })),
      ]);

      const rogues = rogueData?.items || [];
      const sensors = sensorData?.items || [];
      const events = eventData?.items || [];

      setRogueList(rogues);
      setSensorsList(sensors);
      setEventsList(events);
      setReplay(replayData);

      // Prefer the backend's real scene. The previous implementation fetched it
      // but discarded it, making the fallback scene (floor 1 only) the only view.
      if (spatialData && spatialData.locations?.length > 0) {
        const normalizedScene = dedupeSensorNodes(spatialData);
        setScene(normalizedScene);
        setSelectedNodeId((current) =>
          current && normalizedScene.nodes.some((node) => node.id === current) ? current : null,
        );
        return;
      }

      setScene(null);
      setSelectedNodeId(null);
      setSceneLoadError(
        spatialData
          ? 'The server returned no spatial locations for this view.'
          : 'The spatial scene could not be loaded from the server.',
      );
      return;

      // Ground floor 0 is the entrance/common level; floors 1 and 2 are the
      // two training levels shown in the Locations page.
      const baseScene: SpatialSceneResponse = {
        version: 1,
        timestamp: new Date().toISOString(),
        locations: [
          {
            id: 1,
            name: 'Datacenter / Server Room [Restricted]',
            label: 'Server Room',
            type: 'room',
            floor: 1,
            position: { x: 8, y: 9, z: 0 },
            bounds: { width: 12, length: 12, height: 3.5 },
            is_restricted: true,
            zone_type: 'datacenter',
          },
          {
            id: 2,
            name: 'Office Zone Alpha (Engineering)',
            label: 'Zone Alpha',
            type: 'room',
            floor: 1,
            position: { x: 28, y: 10, z: 0 },
            bounds: { width: 18, length: 14, height: 3.0 },
            is_restricted: false,
            zone_type: 'office',
          },
          {
            id: 3,
            name: 'Office Zone Beta (Operations)',
            label: 'Zone Beta',
            type: 'room',
            floor: 1,
            position: { x: 28, y: 28, z: 0 },
            bounds: { width: 18, length: 14, height: 3.0 },
            is_restricted: false,
            zone_type: 'office',
          },
          {
            id: 4,
            name: 'Perimeter / Unmanaged Gateway Zone',
            label: 'Perimeter Zone',
            type: 'room',
            floor: 1,
            position: { x: 48, y: 19, z: 0 },
            bounds: { width: 14, length: 32, height: 2.8 },
            is_restricted: false,
            zone_type: 'perimeter',
          },
        ],
        nodes: [],
        edges: [],
        threats: [],
        meta: {
          version: 1,
          floors: [1],
          total_locations: 4,
          total_nodes: 0,
          total_edges: 0,
          total_threats: 0,
          bounds: { min_x: 0, max_x: 60, min_y: 0, max_y: 40, min_z: 0, max_z: 4 },
        },
      };

      // Keep a useful three-floor fallback when the backend has no scene yet.
      // Floor 0 is intentionally an open ground/entrance level; floors 1 and
      // 2 reuse the center's training-zone footprint at their real elevations.
      const floorOneLocations = [...baseScene.locations];
      baseScene.locations = baseScene.locations.map((location) => ({
        ...location,
        floor: 1,
        position: { ...location.position, z: FLOOR_HEIGHT },
      }));
      [0, 2].forEach((floor) => {
        const floorOffset = floor * FLOOR_HEIGHT;
        floorOneLocations.forEach((location) => {
          baseScene.locations.push({
            ...location,
            id: location.id + (floor + 1) * 100,
            floor,
            name: floor === 0 ? `${location.name} · Ground Floor` : `${location.name} · Floor ${floor}`,
            label: floor === 0 ? `${location.label} · F0` : `${location.label} · F${floor}`,
            position: { ...location.position, z: floorOffset },
          });
        });
      });
      baseScene.meta.floors = [...CENTER_FLOORS];
      baseScene.meta.total_locations = baseScene.locations.length;
      baseScene.meta.bounds.max_z = FLOOR_HEIGHT * 2 + 4;

      // 1. Add Gateway & Core Switch in Server Room
      const gatewayNode: SpatialSceneNode = {
        id: 'node-gateway',
        name: 'Core Gateway / Firewall',
        label: 'Gateway-01',
        type: 'gateway',
        position: { x: 5.5, y: 6.5, z: 1.2 },
        status: 'online',
        risk: 'low',
        confidence: 1.0,
        ip: '192.168.1.1',
        mac: '00:50:56:00:00:01',
        vendor: 'Cisco Security',
        location_label: 'Server Room',
        is_sensor: false,
        is_rogue: false,
        quarantined: false,
        metadata: { role: 'default_gateway', bandwidth_gbps: 10 },
      };
      baseScene.nodes.push(gatewayNode);

      const switchNode: SpatialSceneNode = {
        id: 'node-switch-core',
        name: 'Core Distribution Switch',
        label: 'Core Switch',
        type: 'switch',
        position: { x: 10.5, y: 6.5, z: 1.2 },
        status: 'online',
        risk: 'low',
        confidence: 1.0,
        ip: '192.168.1.2',
        mac: '00:50:56:00:00:02',
        vendor: 'Cisco Nexus',
        location_label: 'Server Room',
        is_sensor: false,
        is_rogue: false,
        quarantined: false,
        metadata: { ports_total: 48, ports_active: 32 },
      };
      baseScene.nodes.push(switchNode);

      // Core link Gateway <-> Switch
      baseScene.edges.push({
        id: 'edge-core-link',
        source: 'node-gateway',
        target: 'node-switch-core',
        type: 'physical',
        status: 'active',
        traffic_rate: '10 Gbps',
        latency: 0.1,
        risk: 'low',
      });

      // 2. Add Dedicated Grid Sensors
      const sensorPositions = [
        { x: 15.0, y: 9.0, z: 2.4, label: 'Sensor 01 (Core/Server)' },
        { x: 38.0, y: 19.0, z: 2.4, label: 'Sensor 02 (Perimeter Boundary)' },
      ];

      sensors.forEach((s, idx) => {
        const sPos = sensorPositions[idx % sensorPositions.length];
        const sensorFloor = s.floor != null ? Number(s.floor) : 1;
        const sensorFloorZ = sensorFloor * FLOOR_HEIGHT;
        const sNodeId = `sensor-${s.id}`;
        baseScene.nodes.push({
          id: sNodeId,
          name: s.name || `Sensor Probe ${s.id}`,
          label: s.name || `Sensor-${s.id}`,
          type: 'sensor',
          position: {
            x: s.x != null ? Number(s.x) : sPos.x,
            y: s.y != null ? Number(s.y) : sPos.y,
            z: sensorFloorZ + 2.4,
          },
          status: s.status === 'ONLINE' ? 'online' : 'offline',
          risk: 'low',
          confidence: 1.0,
          location_label: s.location_label || sPos.label,
          is_sensor: true,
          is_rogue: false,
          quarantined: false,
          metadata: {
            capabilities: s.capabilities || ['arp', 'dhcp', 'rssi_triangulation'],
            sensor_type: s.type,
            floor: sensorFloor,
          },
        });

        // Link sensor to core switch
        baseScene.edges.push({
          id: `edge-sensor-${s.id}`,
          source: 'node-switch-core',
          target: sNodeId,
          type: 'physical',
          status: 'active',
          traffic_rate: '100 kbps',
          latency: 0.3,
          risk: 'low',
        });
      });

      // 3. Layout Network & Rogue Devices into Clean Structured Grid Cells (Avoid Collision!)
      // - Critical/Rogue threats in Server Room or Perimeter
      // - Normal workstations in Zone Alpha and Zone Beta
      let alphaIndex = 0;
      let betaIndex = 0;
      let perimeterIndex = 0;
      let serverRoomIndex = 0;

      rogues.forEach((r) => {
        const nodeId = `dev-${r.device_id}`;
        const isCritical = r.risk_level === 'CRITICAL' || r.risk_level === 'HIGH';
        const isRogue = r.is_rogue || r.rogue_score >= 35;

        let nx = 0;
        let ny = 0;
        let nz = 0.8;
        let zoneLabel = 'Office Floor';

        if (r.location?.x != null && r.location?.y != null) {
          nx = Number(r.location.x);
          ny = Number(r.location.y);
          nz = Number(r.location.z || 0.8);
          zoneLabel = r.location.label || 'Assigned Zone';
        } else if (isCritical) {
          // Place critical threats near Server Room perimeter or Perimeter Zone
          if (serverRoomIndex < 3) {
            nx = 5.0 + serverRoomIndex * 3.5;
            ny = 11.5;
            zoneLabel = 'Server Room (Breach)';
            serverRoomIndex++;
          } else {
            nx = 44.0 + (perimeterIndex % 3) * 3.6;
            ny = 8.0 + Math.floor(perimeterIndex / 3) * 3.4;
            zoneLabel = 'Perimeter Zone (Threat)';
            perimeterIndex++;
          }
        } else if (isRogue) {
          // Perimeter zone matrix (4 columns spaced neatly)
          const col = perimeterIndex % 4;
          const row = Math.floor(perimeterIndex / 4);
          nx = 43.0 + col * 3.2;
          ny = 6.0 + row * 2.8;
          zoneLabel = 'Perimeter Zone (Unmanaged)';
          perimeterIndex++;
        } else if (alphaIndex <= 30) {
          // Zone Alpha (Engineering) desk matrix (6 columns x 5 rows)
          const col = alphaIndex % 6;
          const row = Math.floor(alphaIndex / 6);
          nx = 21.0 + col * 2.6;
          ny = 5.0 + row * 2.4;
          zoneLabel = 'Zone Alpha (Workstation)';
          alphaIndex++;
        } else {
          // Zone Beta (Operations) desk matrix (6 columns x 5 rows)
          const col = betaIndex % 6;
          const row = Math.floor(betaIndex / 6);
          nx = 21.0 + col * 2.6;
          ny = 23.0 + row * 2.4;
          zoneLabel = 'Zone Beta (Operations)';
          betaIndex++;
        }

        const devType = isRogue ? 'rogue' : (r.hostname?.toLowerCase().includes('srv') ? 'server' : 'workstation');

        const nodeObj: SpatialSceneNode = {
          id: nodeId,
          name: r.hostname || r.mac_address,
          label: r.hostname ? r.hostname.slice(0, 14) : r.mac_address.slice(-8),
          type: devType,
          position: { x: nx, y: ny, z: nz },
          status: isRogue ? 'rogue' : 'suspicious',
          risk: r.risk_level.toLowerCase() as any,
          confidence: r.location?.confidence || 0.85,
          ip: r.ip_address,
          mac: r.mac_address,
          vendor: r.vendor || 'LAN Endpoint',
          location_label: zoneLabel,
          is_sensor: false,
          is_rogue: isRogue,
          quarantined: false,
          metadata: {
            rogue_score: r.rogue_score,
            reasons: r.reasons || ['Unmanaged host detected on subnet'],
            method: r.location?.method || 'MULTILATERATION',
          },
        };
        baseScene.nodes.push(nodeObj);

        // Add threat marker if rogue or critical
        if (isRogue || isCritical) {
          baseScene.threats.push({
            id: `threat-${r.device_id}`,
            device_id: r.device_id,
            node_id: nodeId,
            name: r.hostname || r.mac_address,
            severity: r.risk_level.toLowerCase() as any,
            score: r.rogue_score,
            position: { x: nx, y: ny, z: nz },
            confidence: r.location?.confidence || 0.85,
            reasons: r.reasons || ['Rogue risk anomaly detected'],
            detected_at: r.first_seen || new Date().toISOString(),
            is_restricted_zone: Boolean(r.location?.is_restricted || zoneLabel.includes('Server Room')),
          });

          // Add visual threat proximity link to nearest sensor
          baseScene.edges.push({
            id: `edge-threat-${r.device_id}`,
            source: 'sensor-1',
            target: nodeId,
            type: 'threat',
            status: 'active',
            traffic_rate: 'RF Pulse',
            latency: 1.2,
            risk: 'high',
          });
        }
      });

      // Update meta counts
      baseScene.meta.total_nodes = baseScene.nodes.length;
      baseScene.meta.total_threats = baseScene.threats.length;
      baseScene.meta.total_edges = baseScene.edges.length;

      setScene(baseScene);
    } catch (err: any) {
      console.error('Failed to load 3D spatial scene:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSceneData();
  }, [selectedFloor]);

  // Replay playback loop
  useEffect(() => {
    if (isReplaying && replay && replay.frames.length > 0) {
      replayTimerRef.current = window.setInterval(() => {
        setCurrentFrameIndex((prev) => {
          if (prev + 1 >= replay.frames.length) {
            setIsReplaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 1000 / replaySpeed);
    } else {
      if (replayTimerRef.current) {
        clearInterval(replayTimerRef.current);
      }
    }
    return () => {
      if (replayTimerRef.current) {
        clearInterval(replayTimerRef.current);
      }
    };
  }, [isReplaying, replay, replaySpeed]);

  // AR Camera initialization
  useEffect(() => {
    if (viewMode === 'ar') {
      navigator.mediaDevices
        ?.getUserMedia({ video: { facingMode: 'environment' } })
        .then((stream) => {
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            videoRef.current.play();
            setArCameraActive(true);
          }
        })
        .catch(() => {
          setArCameraActive(false);
        });
    } else {
      if (videoRef.current && videoRef.current.srcObject) {
        const stream = videoRef.current.srcObject as MediaStream;
        stream.getTracks().forEach((track) => track.stop());
        videoRef.current.srcObject = null;
      }
      setArCameraActive(false);
    }
  }, [viewMode]);

  // Filtered nodes based on search and zoneFilter tab
  const nodeFloor = useCallback((node: SpatialSceneNode) => {
    const declaredFloor = Number(node.metadata?.floor);
    if (Number.isFinite(declaredFloor) && CENTER_FLOORS.includes(declaredFloor as 0 | 1 | 2)) return declaredFloor;
    if (node.position.z >= FLOOR_HEIGHT * 2) return 2;
    if (node.position.z >= FLOOR_HEIGHT) return 1;
    return 0;
  }, []);

  const visibleLocations = useMemo(() => {
    if (!scene) return [];
    return selectedFloor === 'all'
      ? scene.locations
      : scene.locations.filter((location) => location.floor === selectedFloor);
  }, [scene, selectedFloor]);

  const displayedNodes = useMemo(() => {
    if (!scene) return [];
    let list = selectedFloor === 'all'
      ? scene.nodes
      : scene.nodes.filter((node) => nodeFloor(node) === selectedFloor);

    if (zoneFilter === 'threats') {
      list = list.filter((n) => n.risk === 'critical' || n.risk === 'high' || n.is_rogue);
    } else if (zoneFilter === 'datacenter') {
      list = list.filter((n) => n.location_label?.toLowerCase().includes('server') || n.type === 'gateway' || n.type === 'switch');
    } else if (zoneFilter === 'workstations') {
      list = list.filter((n) => n.location_label?.toLowerCase().includes('alpha') || n.location_label?.toLowerCase().includes('beta'));
    } else if (zoneFilter === 'perimeter') {
      list = list.filter((n) => n.location_label?.toLowerCase().includes('perimeter'));
    } else if (zoneFilter === 'sensors') {
      list = list.filter((n) => n.is_sensor || n.type === 'sensor');
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (n) =>
          n.name.toLowerCase().includes(q) ||
          n.label.toLowerCase().includes(q) ||
          n.ip?.toLowerCase().includes(q) ||
          n.mac?.toLowerCase().includes(q) ||
          n.location_label?.toLowerCase().includes(q)
      );
    }
    return list;
  }, [scene, selectedFloor, nodeFloor, zoneFilter, searchQuery]);

  const displayedThreats = useMemo(() => {
    // Rogue Device Manager is the canonical assessment list. The scene can
    // intentionally omit duplicate or unlocalized nodes, so using only
    // scene.threats made this panel disagree with the manager.
    const sceneThreatsByDevice = new Map((scene?.threats ?? []).map((threat) => [threat.device_id, threat]));
    const threats = rogueList.map((rogue) => {
      const sceneThreat = sceneThreatsByDevice.get(rogue.device_id);
      if (sceneThreat) return sceneThreat;

      const location = rogue.location;
      return {
        id: `threat-${rogue.device_id}`,
        device_id: rogue.device_id,
        node_id: `dev-${rogue.device_id}`,
        name: rogue.hostname || rogue.mac_address,
        severity: rogue.risk_level.toLowerCase() as 'low' | 'medium' | 'high' | 'critical',
        score: rogue.rogue_score,
        position: {
          x: Number(location?.x ?? 0),
          y: Number(location?.y ?? 0),
          z: Number(location?.z ?? 0.8),
        },
        confidence: Number(location?.confidence ?? 0),
        reasons: rogue.reasons,
        detected_at: rogue.first_seen || new Date().toISOString(),
        is_restricted_zone: Boolean(location?.is_restricted),
      };
    });

    if (zoneFilter === 'datacenter') {
      return threats.filter((threat) => threat.is_restricted_zone);
    }
    return threats;
  }, [scene, rogueList, zoneFilter]);

  const selectedNode = useMemo(() => {
    if (!scene || !selectedNodeId) return null;
    return scene.nodes.find((n) => n.id === selectedNodeId) || null;
  }, [scene, selectedNodeId]);

  const hoveredNode = useMemo(() => {
    if (!scene || !hoveredNodeId) return null;
    return scene.nodes.find((n) => n.id === hoveredNodeId) || null;
  }, [scene, hoveredNodeId]);

  // 3D Canvas Rendering Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !scene) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let tick = 0;

    const render = () => {
      tick += 0.025;
      const width = canvas.width;
      const height = canvas.height;

      // Clear canvas
      ctx.clearRect(0, 0, width, height);

      // Gradient High-Tech Canvas Background
      if (viewMode === 'threat') {
        const bgGrad = ctx.createRadialGradient(width / 2, height / 2, 50, width / 2, height / 2, width);
        bgGrad.addColorStop(0, '#0d1322');
        bgGrad.addColorStop(1, '#050810');
        ctx.fillStyle = bgGrad;
      } else if (viewMode === 'ar') {
        ctx.fillStyle = arCameraActive ? 'rgba(0, 0, 0, 0.15)' : '#070f1e';
      } else {
        const bgGrad = ctx.createRadialGradient(width / 2, height / 2, 50, width / 2, height / 2, width);
        bgGrad.addColorStop(0, '#0f172a');
        bgGrad.addColorStop(1, '#060a14');
        ctx.fillStyle = bgGrad;
      }
      ctx.fillRect(0, 0, width, height);

      // Camera 3D to 2D isometric projection setup
      const radYaw = (yaw * Math.PI) / 180;
      const radPitch = (pitch * Math.PI) / 180;
      const cosY = Math.cos(radYaw);
      const sinY = Math.sin(radYaw);
      const cosP = Math.cos(radPitch);
      const sinP = Math.sin(radPitch);

      const centerX = width / 2 + panX;
      const centerY = height / 2 + panY;
      const scale = 16 * zoom;

      // Projection helper: (x, y, z) in meters -> (screenX, screenY, depth)
      const project = (x: number, y: number, z: number) => {
        const dx = x - 28;
        const dy = y - 19;
        const dz = z;

        const rx = dx * cosY - dy * sinY;
        const ry = dx * sinY + dy * cosY;

        const px = rx;
        const py = ry * cosP - dz * sinP;
        const pz = ry * sinP + dz * cosP;

        const screenX = centerX + px * scale;
        const screenY = centerY - py * scale;
        return { x: screenX, y: screenY, z: pz };
      };

      // 1. Draw Floor Grid Background Matrix
      ctx.lineWidth = 1;
      ctx.strokeStyle = viewMode === 'threat' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(56, 189, 248, 0.08)';
      const gridSizeX = 58;
      const gridSizeY = 38;
      const step = 4;

      ctx.beginPath();
      for (let x = 0; x <= gridSizeX; x += step) {
        const p1 = project(x, 0, 0);
        const p2 = project(x, gridSizeY, 0);
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
      }
      for (let y = 0; y <= gridSizeY; y += step) {
        const p1 = project(0, y, 0);
        const p2 = project(gridSizeX, y, 0);
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
      }
      ctx.stroke();

      // 2. Draw Distinct Zone Floor Pads & Glass Enclosures
      visibleLocations.forEach((loc) => {
        const lx = loc.position.x;
        const ly = loc.position.y;
        const lz = loc.position.z;
        const lw = loc.bounds.width;
        const ll = loc.bounds.length;

        const p0 = project(lx - lw / 2, ly - ll / 2, lz);
        const p1 = project(lx + lw / 2, ly - ll / 2, lz);
        const p2 = project(lx + lw / 2, ly + ll / 2, lz);
        const p3 = project(lx - lw / 2, ly + ll / 2, lz);

        // Floor Plate Polygon
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.lineTo(p3.x, p3.y);
        ctx.closePath();

        if (loc.is_restricted) {
          // Server Room / Datacenter
          ctx.fillStyle = 'rgba(239, 68, 68, 0.14)';
          ctx.strokeStyle = 'rgba(239, 68, 68, 0.75)';
          ctx.lineWidth = 2;
        } else if (loc.zone_type === 'perimeter') {
          // Perimeter Zone
          ctx.fillStyle = 'rgba(245, 158, 11, 0.08)';
          ctx.strokeStyle = 'rgba(245, 158, 11, 0.5)';
          ctx.lineWidth = 1.8;
        } else {
          // Workstation Office Zones
          ctx.fillStyle = 'rgba(14, 165, 233, 0.08)';
          ctx.strokeStyle = 'rgba(56, 189, 248, 0.5)';
          ctx.lineWidth = 1.5;
        }
        ctx.fill();
        ctx.stroke();

        // 3D Glass Boundary Walls
        const topH = loc.bounds.height;
        const tp0 = project(lx - lw / 2, ly - ll / 2, lz + topH);
        const tp1 = project(lx + lw / 2, ly - ll / 2, lz + topH);
        const tp2 = project(lx + lw / 2, ly + ll / 2, lz + topH);
        const tp3 = project(lx - lw / 2, ly + ll / 2, lz + topH);

        ctx.strokeStyle = loc.is_restricted ? 'rgba(239, 68, 68, 0.3)' : 'rgba(56, 189, 248, 0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y); ctx.lineTo(tp0.x, tp0.y);
        ctx.moveTo(p1.x, p1.y); ctx.lineTo(tp1.x, tp1.y);
        ctx.moveTo(p2.x, p2.y); ctx.lineTo(tp2.x, tp2.y);
        ctx.moveTo(p3.x, p3.y); ctx.lineTo(tp3.x, tp3.y);
        ctx.stroke();

        // Top Roof Outline
        ctx.beginPath();
        ctx.moveTo(tp0.x, tp0.y); ctx.lineTo(tp1.x, tp1.y);
        ctx.lineTo(tp2.x, tp2.y); ctx.lineTo(tp3.x, tp3.y);
        ctx.closePath();
        ctx.stroke();

        // Floating Zone Label Tag
        const centerTop = project(lx, ly, lz + topH);
        ctx.font = 'bold 11px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = loc.is_restricted ? '#fca5a5' : '#7dd3fc';
        ctx.fillText(loc.name, centerTop.x, centerTop.y - 6);
      });

      // 3. Draw Sensor Radar Coverage Radii
      scene.nodes.filter((n) => n.is_sensor).forEach((sNode) => {
        const sBase = project(sNode.position.x, sNode.position.y, sNode.position.z);
        const pulseRadius = (26 + ((Math.sin(tick * 3) + 1) * 8)) * zoom;

        ctx.beginPath();
        ctx.ellipse(sBase.x, sBase.y, pulseRadius, pulseRadius * 0.5, 0, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(16, 185, 129, 0.4)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      });

      // 4. Draw Network Topology Links (Edges)
      if (showLinks) {
        scene.edges.forEach((edge) => {
          const sourceNode = scene.nodes.find((n) => n.id === edge.source);
          const targetNode = scene.nodes.find((n) => n.id === edge.target);
          if (!sourceNode || !targetNode) return;

          const pSource = project(sourceNode.position.x, sourceNode.position.y, sourceNode.position.z);
          const pTarget = project(targetNode.position.x, targetNode.position.y, targetNode.position.z);

          ctx.beginPath();
          ctx.moveTo(pSource.x, pSource.y);

          const midX = (sourceNode.position.x + targetNode.position.x) / 2;
          const midY = (sourceNode.position.y + targetNode.position.y) / 2;
          const arcHeight = edge.type === 'threat' ? 2.5 : 1.0;
          const pMid = project(midX, midY, Math.max(sourceNode.position.z, targetNode.position.z) + arcHeight);

          ctx.quadraticCurveTo(pMid.x, pMid.y, pTarget.x, pTarget.y);

          if (edge.type === 'threat') {
            ctx.strokeStyle = 'rgba(239, 68, 68, 0.75)';
            ctx.lineWidth = 2.0;
            ctx.setLineDash([5, 4]);
          } else {
            ctx.strokeStyle = 'rgba(56, 189, 248, 0.35)';
            ctx.lineWidth = 1.2;
            ctx.setLineDash([]);
          }
          ctx.stroke();
          ctx.setLineDash([]);

          // Animated energy packets
          if (viewMode === 'traffic' || edge.type === 'threat') {
            const t = (tick * 0.9 + parseInt(edge.id.replace(/\D/g, '') || '0') * 0.25) % 1.0;
            const packetX = (1 - t) * (1 - t) * pSource.x + 2 * (1 - t) * t * pMid.x + t * t * pTarget.x;
            const packetY = (1 - t) * (1 - t) * pSource.y + 2 * (1 - t) * t * pMid.y + t * t * pTarget.y;

            ctx.beginPath();
            ctx.arc(packetX, packetY, edge.type === 'threat' ? 3.5 : 2.5, 0, Math.PI * 2);
            ctx.fillStyle = edge.type === 'threat' ? '#ef4444' : '#38bdf8';
            ctx.shadowColor = edge.type === 'threat' ? '#ef4444' : '#38bdf8';
            ctx.shadowBlur = 6;
            ctx.fill();
            ctx.shadowBlur = 0;
          }
        });
      }

      // 5. Draw Spatial Nodes (Sorted by Depth)
      const projectedNodes = displayedNodes.map((node) => {
        const p = project(node.position.x, node.position.y, node.position.z);
        return { node, proj: p };
      });

      projectedNodes.sort((a, b) => b.proj.z - a.proj.z);

      projectedNodes.forEach(({ node, proj }) => {
        const isSelected = selectedNodeId === node.id;
        const isHovered = hoveredNodeId === node.id;
        const isThreat = node.is_rogue || node.risk === 'critical' || node.risk === 'high';

        // Floor anchor shadow
        const baseProj = project(node.position.x, node.position.y, 0);
        ctx.beginPath();
        ctx.ellipse(baseProj.x, baseProj.y, 6 * zoom, 3 * zoom, 0, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.fill();

        // Vertical stalk
        ctx.beginPath();
        ctx.moveTo(baseProj.x, baseProj.y);
        ctx.lineTo(proj.x, proj.y);
        ctx.strokeStyle = isSelected ? '#38bdf8' : isThreat ? 'rgba(239, 68, 68, 0.5)' : 'rgba(148, 163, 184, 0.25)';
        ctx.lineWidth = isSelected ? 2 : 1;
        ctx.stroke();

        const nodeRadius = (isSelected ? 12 : isHovered ? 10 : isThreat ? 9 : 7.5) * zoom;

        // Threat Hazard Ring / Pulse Aura
        if (isThreat) {
          const pulseR = nodeRadius + ((Math.sin(tick * 4) + 1) * 4.5);
          ctx.beginPath();
          ctx.arc(proj.x, proj.y, pulseR, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(239, 68, 68, 0.8)';
          ctx.lineWidth = 1.8;
          ctx.stroke();
        }

        // Node 3D Body
        ctx.beginPath();
        ctx.arc(proj.x, proj.y, nodeRadius, 0, Math.PI * 2);

        if (node.is_rogue || node.status === 'rogue') {
          ctx.fillStyle = '#ef4444';
          ctx.shadowColor = '#ef4444';
        } else if (node.status === 'isolated' || node.quarantined) {
          ctx.fillStyle = '#f59e0b';
          ctx.shadowColor = '#f59e0b';
        } else if (node.type === 'sensor' || node.is_sensor) {
          ctx.fillStyle = '#10b981';
          ctx.shadowColor = '#10b981';
        } else if (node.type === 'switch' || node.type === 'gateway') {
          ctx.fillStyle = '#8b5cf6';
          ctx.shadowColor = '#8b5cf6';
        } else {
          ctx.fillStyle = '#0ea5e9';
          ctx.shadowColor = '#0ea5e9';
        }

        ctx.shadowBlur = isSelected ? 14 : isThreat ? 8 : 4;
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.strokeStyle = isSelected ? '#ffffff' : 'rgba(255, 255, 255, 0.7)';
        ctx.lineWidth = isSelected ? 2.5 : 1.2;
        ctx.stroke();

        // Selective Smart Labels (Avoid Clutter!)
        const shouldShowLabel =
          isSelected ||
          isHovered ||
          showLabels === 'all' ||
          (showLabels === 'threats' && isThreat) ||
          zoom > 1.8;

        if (shouldShowLabel) {
          ctx.font = isSelected ? 'bold 11px Inter, system-ui' : '10px Inter, system-ui';
          ctx.fillStyle = isThreat ? '#fca5a5' : '#f8fafc';
          ctx.textAlign = 'center';
          ctx.fillText(node.label, proj.x, proj.y - nodeRadius - 5);
        }
      });

      // 6. In-Canvas Floating HUD Tooltip when Hovering
      if (hoveredNode && !isDraggingRef.current) {
        const hProj = project(hoveredNode.position.x, hoveredNode.position.y, hoveredNode.position.z);
        const cardW = 180;
        const cardH = 68;
        const cardX = Math.min(width - cardW - 10, Math.max(10, hProj.x + 15));
        const cardY = Math.min(height - cardH - 10, Math.max(10, hProj.y - 35));

        ctx.fillStyle = 'rgba(15, 23, 42, 0.92)';
        ctx.strokeStyle = hoveredNode.is_rogue ? '#ef4444' : '#38bdf8';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(cardX, cardY, cardW, cardH, 6);
        ctx.fill();
        ctx.stroke();

        ctx.textAlign = 'left';
        ctx.font = 'bold 11px Inter, system-ui';
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(hoveredNode.name.slice(0, 20), cardX + 10, cardY + 18);

        ctx.font = '10px Inter, system-ui';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${hoveredNode.ip || 'No IP'} • ${hoveredNode.mac || 'No MAC'}`, cardX + 10, cardY + 34);
        ctx.fillText(`Zone: ${hoveredNode.location_label}`, cardX + 10, cardY + 48);

        ctx.font = 'bold 9px Inter, system-ui';
        ctx.fillStyle = hoveredNode.is_rogue ? '#ef4444' : '#10b981';
        ctx.fillText(`Risk: ${hoveredNode.risk.toUpperCase()} | Conf: ${Math.round(hoveredNode.confidence * 100)}%`, cardX + 10, cardY + 61);
      }

      // 7. AR Mode HUD Overlays & Reticles
      if (viewMode === 'ar') {
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(width / 2, height / 2, 40, 0, Math.PI * 2);
        ctx.moveTo(width / 2 - 50, height / 2);
        ctx.lineTo(width / 2 - 20, height / 2);
        ctx.moveTo(width / 2 + 20, height / 2);
        ctx.lineTo(width / 2 + 50, height / 2);
        ctx.moveTo(width / 2, height / 2 - 50);
        ctx.lineTo(width / 2 - 20, height / 2);
        ctx.moveTo(width / 2, height / 2 + 20);
        ctx.lineTo(width / 2 + 50, height / 2);
        ctx.stroke();

        scene.threats.forEach((threat) => {
          const p = project(threat.position.x, threat.position.y, threat.position.z);
          ctx.strokeStyle = '#ef4444';
          ctx.lineWidth = 2;
          const sz = 16;
          ctx.strokeRect(p.x - sz, p.y - sz, sz * 2, sz * 2);

          ctx.fillStyle = '#ef4444';
          ctx.font = 'bold 10px Inter, system-ui';
          ctx.textAlign = 'left';
          ctx.fillText(`⚠️ ${threat.name} [${threat.score} PTS]`, p.x + sz + 4, p.y - 3);
          ctx.fillStyle = '#f8fafc';
          ctx.font = '9px Inter, system-ui';
          ctx.fillText(`Dist: ${(Math.hypot(threat.position.x - 28, threat.position.y - 19)).toFixed(1)}m | Conf: ${Math.round(threat.confidence * 100)}%`, p.x + sz + 4, p.y + 9);
        });
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [scene, visibleLocations, displayedNodes, selectedNodeId, hoveredNodeId, hoveredNode, yaw, pitch, zoom, panX, panY, viewMode, showLinks, showLabels, arCameraActive]);

  // Mouse interaction handlers
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = true;
    didDragRef.current = false;
    dragModeRef.current = e.button === 2 || e.shiftKey ? 'pan' : 'rotate';
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !scene) return;
    const rect = canvas.getBoundingClientRect();
    const canvasScaleX = canvas.width / Math.max(rect.width, 1);
    const canvasScaleY = canvas.height / Math.max(rect.height, 1);
    const mouseX = (e.clientX - rect.left) * canvasScaleX;
    const mouseY = (e.clientY - rect.top) * canvasScaleY;

    if (isDraggingRef.current) {
      const dx = e.clientX - lastMousePosRef.current.x;
      const dy = e.clientY - lastMousePosRef.current.y;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) didDragRef.current = true;
      lastMousePosRef.current = { x: e.clientX, y: e.clientY };

      if (dragModeRef.current === 'rotate') {
        setYaw((prev) => (prev + dx * 0.5) % 360);
        setPitch((prev) => Math.max(10, Math.min(88, prev - dy * 0.5)));
      } else {
        setPanX((prev) => prev + dx);
        setPanY((prev) => prev + dy);
      }
      return;
    }

    const radYaw = (yaw * Math.PI) / 180;
    const radPitch = (pitch * Math.PI) / 180;
    const cosY = Math.cos(radYaw);
    const sinY = Math.sin(radYaw);
    const cosP = Math.cos(radPitch);
    const sinP = Math.sin(radPitch);
    const centerX = canvas.width / 2 + panX;
    const centerY = canvas.height / 2 + panY;
    const scale = 16 * zoom;

    let hitNodeId: string | null = null;
    for (const node of displayedNodes) {
      const dx = node.position.x - 28;
      const dy = node.position.y - 19;
      const dz = node.position.z;
      const rx = dx * cosY - dy * sinY;
      const ry = dx * sinY + dy * cosY;
      const px = rx;
      const py = ry * cosP - dz * sinP;
      const sx = centerX + px * scale;
      const sy = centerY - py * scale;

      const dist = Math.hypot(mouseX - sx, mouseY - sy);
      if (dist < 13 * zoom) {
        hitNodeId = node.id;
        break;
      }
    }
    setHoveredNodeId(hitNodeId);
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
  };

  const handleClick = () => {
    if (didDragRef.current) return;
    if (hoveredNodeId) {
      const target = displayedNodes.find((node) => node.id === hoveredNodeId);
      if (target) focusOnNode(target);
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.88;
    setZoom((prev) => Math.max(0.4, Math.min(4.5, prev * zoomFactor)));
  };

  const focusOnNode = (node: SpatialSceneNode) => {
    const floor = nodeFloor(node);
    if (selectedFloor !== 'all' && floor !== selectedFloor) {
      setSelectedFloor(floor);
    }
    setSelectedNodeId(node.id);
    setPanX((28 - node.position.x) * 16 * zoom);
    setPanY((node.position.y - 19) * 16 * zoom);
  };

  // Typing an exact device identifier is still supported, but no longer
  // requires a second manual search action: the matching node is selected and
  // centered as soon as the query uniquely identifies it.
  useEffect(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!scene) return;
    const exactMatches = scene.nodes.filter((node) =>
      requestedClientId && node.metadata?.client_id === requestedClientId,
    );
    if (exactMatches.length === 1) {
      focusOnNode(exactMatches[0]);
      return;
    }
    if (!query) return;
    const queryMatches = scene.nodes.filter((node) =>
      [node.ip, node.mac, node.name, node.label]
        .filter(Boolean)
        .some((value) => value!.toLowerCase() === query),
    );
    if (queryMatches.length === 1) focusOnNode(queryMatches[0]);
  }, [searchQuery, requestedClientId, scene]);

  const triggerIsolation = async (clientId: string) => {
    try {
      await api.isolateClient(clientId, {
        reason: 'Operator initiated spatial isolation from 3D Digital Twin',
      });
      loadSceneData();
    } catch (err: any) {
      alert(`Could not isolate device: ${err?.message || err}`);
    }
  };

  const criticalThreatsCount = rogueList.filter((r) => r.risk_level === 'CRITICAL' || r.risk_level === 'HIGH').length;
  const activeSensorsCount = sensorsList.filter((s) => s.status === 'ONLINE').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', height: '100%' }}>
      {/* Spatial command header */}
      <div className="page-header spatial-page-header">
        <div className="spatial-page-header__copy">
          <span className="eyebrow eyebrow--accent">SPATIAL INTELLIGENCE / NETWORK TWIN</span>
          <h1 className="page-title">Your infrastructure, mapped in space</h1>
          <p style={{ color: "var(--text-muted)", marginTop: "var(--space-1)" }}>Inspect devices, sensors, threats, and connectivity in the spatial scene. Threat counts use the same full scored inventory as Rogue Device Manager.</p>
        </div>

        {/* View Mode Switcher */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', background: 'var(--color-bg-secondary)', padding: '3px', borderRadius: '8px', gap: '5px' }}>
          <Button
            variant={viewMode === 'physical' ? 'primary' : 'quiet'}
            size="sm"
            onClick={() => setViewMode('physical')}
          >
            <TbEye size={14} style={{ marginRight: '4px' }} />
            Physical 3D
          </Button>
          <Button
            variant={viewMode === 'topology' ? 'primary' : 'quiet'}
            size="sm"
            onClick={() => setViewMode('topology')}
          >
            <TbNetwork size={14} style={{ marginRight: '4px' }} />
            Topology
          </Button>
          <Button
            variant={viewMode === 'threat' ? 'primary' : 'quiet'}
            size="sm"
            onClick={() => setViewMode('threat')}
          >
            <TbRadar size={14} style={{ marginRight: '4px' }} />
            Threat Radar
          </Button>
          <div style={{gridColumn: 'span 3' , width: '100%' ,   justifyContent: "center", display: 'flex', gap: '2px'}}>
          <Button
            variant={viewMode === 'traffic' ? 'primary' : 'quiet'}
            size="sm"
            onClick={() => setViewMode('traffic')}
          >
            <TbActivity size={14} style={{ marginRight: '4px' }} />
            Flows
          </Button>
          <Button
            variant={viewMode === 'ar' ? 'primary' : 'quiet'}
            size="sm"
            onClick={() => setViewMode('ar')}
          >
            <TbCamera size={14} style={{ marginRight: '4px' }} />
            AR Mode
          </Button></div>
        </div>
      </div>

      {sceneLoadError && (
        <Notice
          variant="warning"
          title="Spatial scene unavailable"
          action={<Button variant="secondary" size="sm" onClick={loadSceneData}>Retry</Button>}
        >
          {sceneLoadError} No devices, sensors, or network links are shown until the server supplies real scene data.
        </Notice>
      )}

      {/* Top 4 Spatial Metrics Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 'var(--space-3)' }}>
        <MetricCard
          label="ROGUE CANDIDATES"
          value={rogueList.length || scene?.nodes.filter((n) => n.is_rogue).length || 0}
          context="Unmanaged / suspicious endpoints"
          valueVariant="warning"
        />
        <MetricCard
          label="HIGH / CRITICAL THREATS"
          value={criticalThreatsCount}
          context="Restricted zone or randomized MAC"
          valueVariant={criticalThreatsCount > 0 ? 'danger' : 'success'}
        />
        <MetricCard
          label="GRID SENSORS"
          value={`${activeSensorsCount} / ${sensorsList.length || 2}`}
          context="Endpoint & infrastructure probes"
          valueVariant="info"
        />
        <MetricCard
          label="LOCATION TRANSITIONS"
          value={eventsList.length || replay?.events?.length || 0}
          context="Recorded spatial movement events"
          valueVariant="default"
        />
      </div>

      {/* Main Workspace Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 'var(--space-4)', flex: 1, minHeight: '660px' }}>
        {/* Left Column: 3D Viewport & Timeline Scrubber */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <Card className="spatial-canvas-card">
            <div style={{ position: 'relative', overflow: 'hidden', minHeight: '520px', width: '100%', height: '100%' }}>
              {/* AR Video Background Element */}
              {viewMode === 'ar' && (
                <video
                  ref={videoRef}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    zIndex: 0,
                    opacity: arCameraActive ? 0.65 : 0,
                  }}
                  playsInline
                  muted
                />
              )}

              {/* 3D Canvas Element */}
              <div style={{ position: 'absolute', bottom: '38px', left: '14px', zIndex: 2, display: 'flex', gap: '6px', pointerEvents: 'none' }}>
                {(scene?.meta.floors?.length ? scene.meta.floors : CENTER_FLOORS).map((floor) => (
                  <span key={floor} style={{ padding: '3px 7px', borderRadius: '999px', background: selectedFloor === floor ? 'rgba(56, 189, 248, 0.35)' : 'rgba(15, 23, 42, 0.8)', border: '1px solid rgba(148, 163, 184, 0.35)', color: '#e2e8f0', fontSize: '0.7rem' }}>
                    F{floor}
                  </span>
                ))}
              </div>

              <canvas
                ref={canvasRef}
                width={1050}
                height={600}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                onClick={handleClick}
                onWheel={handleWheel}
                onContextMenu={(e) => e.preventDefault()}
                style={{
                  width: '100%',
                  height: '100%',
                  display: 'block',
                  cursor: isDraggingRef.current ? 'grabbing' : hoveredNodeId ? 'pointer' : 'grab',
                  touchAction: 'none',
                  position: 'relative',
                  zIndex: 1,
                }}
              />

              {/* In-Canvas Filters & Quick Presets Toolbar */}
              <div style={{ position: 'absolute', top: '12px', left: '12px', zIndex: 2, display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  placeholder="Search device, IP..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid rgba(56, 189, 248, 0.4)',
                    color: '#f8fafc',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    backdropFilter: 'blur(8px)',
                    width: '160px',
                  }}
                />

                {/* Zone Filter Dropdown */}
                <select
                  value={zoneFilter}
                  onChange={(e) => setZoneFilter(e.target.value as ZoneFilter)}
                  style={{
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid rgba(56, 189, 248, 0.4)',
                    color: '#f8fafc',
                    padding: '6px 10px',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    backdropFilter: 'blur(8px)',
                  }}
                >
                  <option value="all">🏢 All Zones ({scene?.nodes.length || 0})</option>
                  <option value="threats">🚨 Threats ({scene?.threats.length || 0})</option>
                  <option value="datacenter">🔒 Server Room</option>
                  <option value="workstations">💻 Workstation Floors</option>
                  <option value="perimeter">🛰️ Perimeter Zone</option>
                  <option value="sensors">📡 Sensors ({sensorsList.length || 0})</option>
                </select>

                {/* Floor Selector */}
                <select
                  value={selectedFloor}
                  onChange={(e) => setSelectedFloor(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                  style={{
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid rgba(56, 189, 248, 0.4)',
                    color: '#f8fafc',
                    padding: '6px 10px',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    backdropFilter: 'blur(8px)',
                  }}
                >
                  <option value="all">🏢 All Floors ({scene?.meta.floors?.length || CENTER_FLOORS.length})</option>
                  {(scene?.meta.floors?.length ? scene.meta.floors : CENTER_FLOORS).map((floor) => (
                    <option key={floor} value={floor}>Floor {floor}</option>
                  ))}
                </select>

                {/* Camera View Presets */}
                <div style={{ display: 'flex', background: 'rgba(15, 23, 42, 0.9)', padding: '2px', borderRadius: '6px', border: '1px solid rgba(148, 163, 184, 0.3)' }}>
                  <button
                    onClick={() => applyCameraPreset('top')}
                    style={{ background: pitch >= 80 ? 'rgba(56, 189, 248, 0.3)' : 'transparent', border: 'none', color: '#f8fafc', padding: '4px 8px', fontSize: '0.75rem', borderRadius: '4px', cursor: 'pointer' }}
                    title="Top-Down 2D/3D Floor Plan"
                  >
                    Top Plan
                  </button>
                  <button
                    onClick={() => applyCameraPreset('iso')}
                    style={{ background: pitch < 80 && pitch > 20 ? 'rgba(56, 189, 248, 0.3)' : 'transparent', border: 'none', color: '#f8fafc', padding: '4px 8px', fontSize: '0.75rem', borderRadius: '4px', cursor: 'pointer' }}
                    title="Isometric 3D View"
                  >
                    3D Iso
                  </button>
                  <button
                    onClick={() => applyCameraPreset('threats')}
                    style={{ background: 'transparent', border: 'none', color: '#fca5a5', padding: '4px 8px', fontSize: '0.75rem', borderRadius: '4px', cursor: 'pointer' }}
                    title="Focus Threats Cluster"
                  >
                    Threats
                  </button>
                </div>

                {/* Display Toggles */}
                <button
                  onClick={() => setShowLinks(!showLinks)}
                  style={{
                    background: showLinks ? 'rgba(56, 189, 248, 0.25)' : 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#f8fafc',
                    padding: '6px 8px',
                    borderRadius: '6px',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                  }}
                  title="Toggle Network Links"
                >
                  {showLinks ? 'Links ON' : 'Links OFF'}
                </button>

                <button
                  onClick={() => setShowLabels(showLabels === 'threats' ? 'all' : showLabels === 'all' ? 'none' : 'threats')}
                  style={{
                    background: 'rgba(15, 23, 42, 0.9)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#f8fafc',
                    padding: '6px 8px',
                    borderRadius: '6px',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                  }}
                  title="Toggle Label Density"
                >
                  Labels: {showLabels.toUpperCase()}
                </button>
              </div>

              {/* Camera Floating Controls */}
              <div style={{ position: 'absolute', top: '12px', right: '12px', zIndex: 2, display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <button
                  onClick={() => setZoom((z) => Math.min(4.5, z * 1.2))}
                  style={{ background: 'rgba(15, 23, 42, 0.9)', border: '1px solid rgba(148, 163, 184, 0.3)', color: '#f8fafc', width: '32px', height: '32px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  title="Zoom In"
                >
                  <TbZoomIn size={16} />
                </button>
                <button
                  onClick={() => setZoom((z) => Math.max(0.4, z * 0.8))}
                  style={{ background: 'rgba(15, 23, 42, 0.9)', border: '1px solid rgba(148, 163, 184, 0.3)', color: '#f8fafc', width: '32px', height: '32px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  title="Zoom Out"
                >
                  <TbZoomOut size={16} />
                </button>
                <button
                  onClick={() => applyCameraPreset('iso')}
                  style={{ background: 'rgba(15, 23, 42, 0.9)', border: '1px solid rgba(148, 163, 184, 0.3)', color: '#f8fafc', width: '32px', height: '32px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  title="Reset Camera"
                >
                  <TbFocusCentered size={16} />
                </button>
              </div>

              {/* HUD Status Bar at Bottom of Canvas */}
              <div style={{ position: 'absolute', bottom: '10px', left: '14px', right: '14px', zIndex: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8', fontSize: '0.75rem', pointerEvents: 'none' }}>
                <div style={{ display: 'flex', gap: '14px' }}>
                  <span>Visible Nodes: <strong style={{ color: '#f8fafc' }}>{displayedNodes.length}</strong></span>
                  <span>Threats: <strong style={{ color: '#ef4444' }}>{displayedThreats.length}</strong></span>
                  <span>Sensors: <strong style={{ color: '#10b981' }}>{activeSensorsCount}</strong></span>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <span>Yaw: {Math.round(yaw)}°</span>
                  <span>Pitch: {Math.round(pitch)}°</span>
                  <span>Zoom: {(zoom * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Time-Replay Controller Bar */}
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', padding: 'var(--space-2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Button
                  size="sm"
                  variant="quiet"
                  onClick={() => setCurrentFrameIndex((f) => Math.max(0, f - 1))}
                  disabled={isReplaying || currentFrameIndex === 0}
                >
                  <TbPlayerSkipBack size={14} />
                </Button>
                <Button
                  size="sm"
                  variant={isReplaying ? 'danger' : 'primary'}
                  onClick={() => setIsReplaying(!isReplaying)}
                >
                  {isReplaying ? <TbPlayerPause size={14} /> : <TbPlayerPlay size={14} />}
                  {isReplaying ? 'Pause' : 'Replay'}
                </Button>
                <Button
                  size="sm"
                  variant="quiet"
                  onClick={() => setCurrentFrameIndex((f) => Math.min((replay?.frames.length || 1) - 1, f + 1))}
                  disabled={isReplaying || !replay || currentFrameIndex >= (replay?.frames.length || 1) - 1}
                >
                  <TbPlayerSkipForward size={14} />
                </Button>
              </div>

              {/* Scrubber Range Slider */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <input
                  type="range"
                  min={0}
                  max={Math.max(1, (replay?.frames.length || eventsList.length || 1) - 1)}
                  value={currentFrameIndex}
                  onChange={(e) => setCurrentFrameIndex(Number(e.target.value))}
                  style={{ width: '100%', cursor: 'pointer' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  <span>Frame {currentFrameIndex + 1} of {Math.max(1, replay?.frames.length || eventsList.length || 1)}</span>
                  <span>{replay?.frames[currentFrameIndex]?.timestamp || eventsList[currentFrameIndex]?.timestamp || 'Live Present'}</span>
                </div>
              </div>

              {/* Speed Multiplier */}
              <div style={{ display: 'flex', gap: '4px' }}>
                {[1, 2, 5].map((spd) => (
                  <Button
                    key={spd}
                    size="sm"
                    variant={replaySpeed === spd ? 'secondary' : 'quiet'}
                    onClick={() => setReplaySpeed(spd)}
                    style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                  >
                    {spd}x
                  </Button>
                ))}
              </div>
            </div>
          </Card>
        </div>

        {/* Right Column: Spatial Inspector & Threat Radar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {selectedNode ? (
            /* Selected Node Inspector */
            <Card>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', padding: 'var(--space-2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {selectedNode.type === 'workstation' && <TbDeviceDesktop />}
                      {selectedNode.type === 'server' && <TbServer />}
                      {selectedNode.type === 'switch' && <TbRouter />}
                      {selectedNode.type === 'sensor' && <TbAntenna />}
                      {selectedNode.type === 'rogue' && <TbAlertTriangle color="#ef4444" />}
                      {selectedNode.name}
                    </h3>
                    <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                      {selectedNode.ip || 'No IP'} • {selectedNode.mac || 'No MAC'}
                    </span>
                  </div>
                  <Button size="sm" variant="quiet" onClick={() => setSelectedNodeId(null)}>
                    ✕
                  </Button>
                </div>

                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <Badge variant={selectedNode.is_rogue ? 'critical' : selectedNode.status === 'online' ? 'success' : 'muted'}>
                    {selectedNode.status.toUpperCase()}
                  </Badge>
                  <Badge variant={selectedNode.risk === 'critical' ? 'critical' : selectedNode.risk === 'high' ? 'danger' : 'info'}>
                    RISK: {selectedNode.risk.toUpperCase()}
                  </Badge>
                  {selectedNode.quarantined && <Badge variant="warning">ISOLATED</Badge>}
                </div>

                {/* Physical Spatial Location Details */}
                <div style={{ background: 'var(--color-bg-secondary)', padding: '10px', borderRadius: '6px', display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.85rem' }}>
                  <div style={{ fontWeight: 600, color: 'var(--color-text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>
                    📍 Physical Position
                  </div>
                  <div>Zone: <strong>{selectedNode.location_label || 'Floor Grid'}</strong></div>
                  <div>
                    Coordinates: <code>({selectedNode.position.x.toFixed(1)}m, {selectedNode.position.y.toFixed(1)}m, {selectedNode.position.z.toFixed(1)}m)</code>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                    <span>Confidence:</span>
                    <div style={{ flex: 1, height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: `${Math.round(selectedNode.confidence * 100)}%`, height: '100%', background: selectedNode.confidence > 0.8 ? '#10b981' : '#f59e0b' }} />
                    </div>
                    <strong>{Math.round(selectedNode.confidence * 100)}%</strong>
                  </div>
                </div>

                {/* Threat Evidence if Rogue / Suspicious */}
                {selectedNode.metadata?.reasons && (
                  <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', padding: '10px', borderRadius: '6px', fontSize: '0.8rem' }}>
                    <div style={{ fontWeight: 600, color: '#ef4444', marginBottom: '4px' }}>
                      🚨 Threat Evidence Breakdown (Score {selectedNode.metadata.rogue_score || 0})
                    </div>
                    <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                      {selectedNode.metadata.reasons.map((r: string, idx: number) => (
                        <li key={idx}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Inspector Actions */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => focusOnNode(selectedNode)}
                  >
                    <TbFocusCentered size={14} style={{ marginRight: '4px' }} />
                    Focus Camera
                  </Button>
                  {selectedNode.id.startsWith('client-') && (
                    <Button
                      size="sm"
                      variant={selectedNode.quarantined ? 'secondary' : 'danger'}
                      onClick={() => triggerIsolation(selectedNode.id.replace('client-', ''))}
                    >
                      <TbShieldLock size={14} style={{ marginRight: '4px' }} />
                      {selectedNode.quarantined ? 'Release Isolation' : 'Isolate Endpoint'}
                    </Button>
                  )}
                  {selectedNode.mac && (
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={() => navigate(`/network/devices/${encodeURIComponent(selectedNode.mac!)}`)}
                    >
                      View Device Telemetry →
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          ) : (
            /* Threat Radar & Overview Panel */
            <Card>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', padding: 'var(--space-2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <TbRadar color="#ef4444" />
                    Active Threat Radar
                  </h3>
                  <Badge variant={displayedThreats.length > 0 ? 'critical' : 'success'}>
                    {displayedThreats.length} DETECTED
                  </Badge>
                </div>

                {displayedThreats.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '340px', overflowY: 'auto' }}>
                    {displayedThreats.map((th) => (
                      <div
                        key={th.id}
                        onClick={() => {
                          const targetNode = scene?.nodes.find((n) => n.id === th.node_id);
                          if (targetNode) focusOnNode(targetNode);
                        }}
                        style={{
                          background: 'rgba(239, 68, 68, 0.06)',
                          border: '1px solid rgba(239, 68, 68, 0.25)',
                          borderRadius: '6px',
                          padding: '8px 10px',
                          cursor: 'pointer',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '4px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <strong style={{ fontSize: '0.85rem', color: '#fca5a5' }}>{th.name}</strong>
                          <Badge variant="critical">Score {th.score}</Badge>
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                          Location: <code>({th.position.x.toFixed(1)}m, {th.position.y.toFixed(1)}m)</code> • {Math.round(th.confidence * 100)}% conf
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', padding: 'var(--space-4)', color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
                    ✨ No active spatial rogue threats detected for selected filter.
                  </div>
                )}

                {/* Quick Actions */}
                <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <Button size="sm" variant="secondary" onClick={loadSceneData} disabled={loading}>
                    <TbReload size={14} style={{ marginRight: '4px' }} />
                    {loading ? 'Refreshing…' : 'Refresh Digital Twin'}
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => navigate('/rogue-devices')}>
                    Open Rogue Device Manager →
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
