import {
  Check,
  Hand,
  Maximize,
  Minus,
  MousePointer2,
  Plus,
  Ruler,
  Grid3X3,
} from "lucide-react";
import {
  furnitureBounds,
  modelBounds,
  openingRect,
  type Furniture,
  type SpatialModel,
  type Bounds,
  updateFurniture,
  wallRect,
} from "./model";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useId,
  type PointerEvent as ReactPointerEvent,
} from "react";

export type SelectionTarget = {
  kind: "room" | "wall" | "opening" | "furniture";
  id: string;
};
export type Selection = SelectionTarget | null;

type PlanCanvasProps = {
  model: SpatialModel;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  onEdit: (model: SpatialModel) => void;
  readOnly: boolean;
};

type ViewBox = Bounds;
type Tool = "select" | "pan";
type DragState = {
  id: string;
  start: { x: number; y: number };
  startClient: { x: number; y: number };
  transform: Furniture["transform"];
  current: Furniture["transform"];
  moved: boolean;
};
type PanState = {
  startWorld: { x: number; y: number };
  inverseCtm: DOMMatrix | null;
  viewBox: ViewBox;
};

const PADDING = 500;
const MIN_VIEW_SIZE = 1000;
const MAX_VIEW_SIZE = 10_000_000;

function fitViewBox(model: SpatialModel): ViewBox {
  const base = modelBounds(model);
  let left = base.x;
  let top = base.y;
  let right = base.x + base.width;
  let bottom = base.y + base.height;
  for (const item of model.furniture_instances) {
    if (item.visible === false) continue;
    const bounds = furnitureBounds(item);
    left = Math.min(left, bounds.x);
    top = Math.min(top, bounds.y);
    right = Math.max(right, bounds.x + bounds.width);
    bottom = Math.max(bottom, bounds.y + bounds.height);
  }
  const bounds = { x: left, y: top, width: right - left, height: bottom - top };
  const width = Math.max(bounds.width + PADDING * 2, MIN_VIEW_SIZE);
  const height = Math.max(bounds.height + PADDING * 2, MIN_VIEW_SIZE);
  return {
    x: bounds.x - PADDING,
    y: bounds.y - PADDING,
    width,
    height,
  };
}

function snap(value: number): number {
  return Math.round(value * 100) / 100;
}

function eventToWorld(
  svg: SVGSVGElement,
  event: { clientX: number; clientY: number },
  fixedInverse?: DOMMatrix | null,
) {
  const ctm = svg.getScreenCTM();
  if (!fixedInverse && !ctm) return { x: event.clientX, y: event.clientY };
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const transformed = point.matrixTransform(fixedInverse ?? ctm!.inverse());
  return { x: transformed.x, y: transformed.y };
}

function selected(
  selection: Selection,
  kind: SelectionTarget["kind"],
  id: string,
): boolean {
  return selection?.kind === kind && selection.id === id;
}

function labelForFurniture(item: Furniture): string {
  return (
    { sofa: "沙发", coffee_table: "茶几", bed: "床" }[item.catalog_id] ??
    item.catalog_id.replace(/[_-]+/g, " ")
  );
}

function labelForRoom(room: { id: string; name: string }): string {
  const key = room.name.toLowerCase();
  if (key === "living") return "客厅";
  if (key === "foyer") return "门厅";
  if (key === "study") return "书房";
  if (key === "master") return "主卧";
  return room.name || room.id;
}

function furnitureShape(
  item: Furniture,
  selectedItem: boolean,
  showDimensions: boolean,
) {
  const catalog = item.catalog_id.toLowerCase();
  const width = item.dimensions.width;
  const depth = item.dimensions.depth;
  const stroke = selectedItem ? "#227c68" : "#927082";
  const fill = selectedItem ? "#d7f0e8" : "#f1e7eb";
  const common = { stroke, strokeWidth: selectedItem ? 28 : 18, fill };
  let shape: React.ReactNode;
  if (catalog.includes("sofa") || catalog.includes("couch")) {
    shape = (
      <>
        <rect
          {...common}
          x={0}
          y={0}
          width={width}
          height={depth}
          rx={Math.min(depth * 0.16, 180)}
        />
        <line
          x1={width * 0.08}
          y1={depth * 0.36}
          x2={width * 0.92}
          y2={depth * 0.36}
          stroke={stroke}
          strokeWidth={12}
        />
        <line
          x1={width * 0.34}
          y1={depth * 0.42}
          x2={width * 0.34}
          y2={depth * 0.9}
          stroke={stroke}
          strokeWidth={10}
        />
        <line
          x1={width * 0.66}
          y1={depth * 0.42}
          x2={width * 0.66}
          y2={depth * 0.9}
          stroke={stroke}
          strokeWidth={10}
        />
      </>
    );
  } else if (
    catalog.includes("coffee") ||
    catalog === "table" ||
    catalog.includes("side_table")
  ) {
    shape = (
      <>
        <rect
          {...common}
          x={0}
          y={0}
          width={width}
          height={depth}
          rx={Math.min(width, depth) * 0.22}
        />
        <line
          x1={width * 0.15}
          y1={depth * 0.5}
          x2={width * 0.85}
          y2={depth * 0.5}
          stroke={stroke}
          strokeWidth={10}
        />
      </>
    );
  } else if (catalog.includes("bed")) {
    shape = (
      <>
        <rect
          {...common}
          x={0}
          y={0}
          width={width}
          height={depth}
          rx={Math.min(width, depth) * 0.04}
        />
        <rect
          x={0}
          y={0}
          width={width}
          height={Math.min(depth * 0.18, 220)}
          fill={selectedItem ? "#b9e3d5" : "#d9c1cc"}
          stroke={stroke}
          strokeWidth={12}
        />
        <line
          x1={width * 0.5}
          y1={depth * 0.2}
          x2={width * 0.5}
          y2={depth * 0.94}
          stroke={stroke}
          strokeWidth={8}
          strokeDasharray="30 22"
        />
      </>
    );
  } else {
    shape = (
      <rect
        {...common}
        x={0}
        y={0}
        width={width}
        height={depth}
        rx={Math.min(width, depth) * 0.04}
      />
    );
  }
  return (
    <>
      {shape}
      <text
        x={width / 2}
        y={depth + 160}
        textAnchor="middle"
        className="plan-label furniture-label"
        fontSize={150}
        pointerEvents="none"
      >
        {labelForFurniture(item)}
      </text>
      {showDimensions && (
        <text
          x={width / 2}
          y={depth + 330}
          textAnchor="middle"
          className="plan-label dimension-label"
          fontSize={120}
          pointerEvents="none"
        >
          {width} × {depth} mm
        </text>
      )}
    </>
  );
}

export function PlanCanvas({
  model,
  selection,
  onSelect,
  onEdit,
  readOnly,
}: PlanCanvasProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const panRef = useRef<PanState | null>(null);
  const suppressClickRef = useRef(false);
  const [tool, setTool] = useState<Tool>("select");
  const [showDimensions, setShowDimensions] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [viewBox, setViewBox] = useState<ViewBox>(() => fitViewBox(model));
  const [preview, setPreview] = useState<{
    id: string;
    transform: Furniture["transform"];
  } | null>(null);
  const gridId = useId().replace(/[^a-zA-Z0-9_-]/g, "");

  const displayFurniture = useMemo(() => {
    if (!preview) return model.furniture_instances;
    return model.furniture_instances.map((item) =>
      item.id === preview.id ? { ...item, transform: preview.transform } : item,
    );
  }, [model.furniture_instances, preview]);

  useEffect(() => {
    setViewBox(fitViewBox(model));
  }, [model.model_id]);

  useEffect(() => {
    clearInteraction();
  }, [model.model_id, model.revision, readOnly]);

  const clearInteraction = useCallback(() => {
    dragRef.current = null;
    panRef.current = null;
    setPreview(null);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        clearInteraction();
        suppressClickRef.current = false;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [clearInteraction]);

  const zoom = useCallback((factor: number) => {
    setViewBox((current) => {
      const width = Math.min(
        Math.max(current.width * factor, MIN_VIEW_SIZE * 0.1),
        MAX_VIEW_SIZE,
      );
      const height = Math.min(
        Math.max(current.height * factor, MIN_VIEW_SIZE * 0.1),
        MAX_VIEW_SIZE,
      );
      return {
        x: current.x + (current.width - width) / 2,
        y: current.y + (current.height - height) / 2,
        width,
        height,
      };
    });
  }, []);

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!svgRef.current || event.button !== 0) return;
    svgRef.current.focus({ preventScroll: true });
    if (tool !== "pan") return;
    event.preventDefault();
    svgRef.current.setPointerCapture(event.pointerId);
    const inverseCtm = svgRef.current.getScreenCTM()?.inverse() ?? null;
    panRef.current = {
      startWorld: eventToWorld(svgRef.current, event, inverseCtm),
      inverseCtm,
      viewBox: { ...viewBox },
    };
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const pan = panRef.current;
    if (pan) {
      const world = eventToWorld(svg, event, pan.inverseCtm);
      setViewBox({
        ...pan.viewBox,
        x: pan.viewBox.x - (world.x - pan.startWorld.x),
        y: pan.viewBox.y - (world.y - pan.startWorld.y),
      });
      return;
    }
    const drag = dragRef.current;
    if (!drag) return;
    const world = eventToWorld(svg, event);
    const nextTransform = {
      ...drag.transform,
      x: snap(drag.transform.x + world.x - drag.start.x),
      y: snap(drag.transform.y + world.y - drag.start.y),
    };
    const moved =
      drag.moved ||
      Math.hypot(
        event.clientX - drag.startClient.x,
        event.clientY - drag.startClient.y,
      ) >= 2;
    dragRef.current = { ...drag, current: nextTransform, moved };
    if (moved) setPreview({ id: drag.id, transform: nextTransform });
  };

  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    const drag = dragRef.current;
    if (panRef.current) {
      panRef.current = null;
      if (svg?.hasPointerCapture(event.pointerId))
        svg.releasePointerCapture(event.pointerId);
      return;
    }
    if (!drag) return;
    if (svg?.hasPointerCapture(event.pointerId))
      svg.releasePointerCapture(event.pointerId);
    const world = eventToWorld(svg!, event);
    const finalTransform = {
      ...drag.transform,
      x: snap(drag.transform.x + world.x - drag.start.x),
      y: snap(drag.transform.y + world.y - drag.start.y),
    };
    const moved =
      Math.hypot(
        event.clientX - drag.startClient.x,
        event.clientY - drag.startClient.y,
      ) >= 2;
    dragRef.current = null;
    setPreview(null);
    if (moved) {
      suppressClickRef.current = true;
      onEdit(
        updateFurniture(model, drag.id, {
          transform: finalTransform,
          provenance: "manual:plan-canvas",
          confidence: 1,
        }),
      );
    }
  };

  const onPointerCancel = () => {
    clearInteraction();
    suppressClickRef.current = false;
  };

  const onFurniturePointerDown = (
    event: ReactPointerEvent<SVGGElement>,
    item: Furniture,
  ) => {
    if (event.button !== 0) return;
    event.preventDefault();
    svgRef.current?.focus({ preventScroll: true });
    onSelect({ kind: "furniture", id: item.id });
    if (tool === "pan") return;
    event.stopPropagation();
    if (readOnly || tool !== "select" || !svgRef.current) return;
    const svg = svgRef.current;
    svg.setPointerCapture(event.pointerId);
    dragRef.current = {
      id: item.id,
      start: eventToWorld(svg, event),
      startClient: { x: event.clientX, y: event.clientY },
      transform: { ...item.transform },
      current: { ...item.transform },
      moved: false,
    };
  };

  const onFurnitureClick = (event: React.MouseEvent, item: Furniture) => {
    event.stopPropagation();
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onSelect({ kind: "furniture", id: item.id });
  };

  const roomShapes = model.rooms
    .filter((room) => room.visible !== false)
    .map((room) => {
      const [x, y, width, height] = room.rect;
      const isSelected = selected(selection, "room", room.id);
      return (
        <g
          key={room.id}
          data-testid={`room-${room.id}`}
          aria-label={`Room ${room.name || room.id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ kind: "room", id: room.id });
          }}
        >
          <rect
            x={x}
            y={y}
            width={width}
            height={height}
            className="plan-room"
            data-testid={`room-shape-${room.id}`}
            fill={isSelected ? "#d7f0e8" : "#eef2eb"}
            stroke={isSelected ? "#227c68" : "#cbd5c8"}
            strokeWidth={isSelected ? 28 : 14}
          />
          <text
            x={x + 120}
            y={y + 370}
            className="plan-label"
            fontSize={170}
            pointerEvents="none"
          >
            {labelForRoom(room)}
          </text>
          {showDimensions && (
            <text
              x={x + width - 120}
              y={y + 260}
              textAnchor="end"
              className="plan-label dimension-label"
              fontSize={130}
              pointerEvents="none"
            >
              {Math.round(width)} × {Math.round(height)} mm
            </text>
          )}
        </g>
      );
    });

  const wallShapes = model.walls.map((wall) => {
    const rect = wallRect(wall);
    const isSelected = selected(selection, "wall", wall.id);
    return (
      <rect
        key={wall.id}
        {...rect}
        data-testid={`wall-${wall.id}`}
        aria-label={`墙体 ${wall.id}`}
        className="plan-wall"
        onClick={(event) => {
          event.stopPropagation();
          onSelect({ kind: "wall", id: wall.id });
        }}
        fill={isSelected ? "#227c68" : "#46534b"}
        stroke={isSelected ? "#227c68" : "#33443b"}
        strokeWidth={isSelected ? 28 : 10}
      />
    );
  });

  const openingShapes = model.openings.map((opening) => {
    const wall = model.walls.find(
      (candidate) => candidate.id === opening.host_wall_id,
    );
    if (!wall) return null;
    const rect = openingRect(opening, wall);
    const isSelected = selected(selection, "opening", opening.id);
    return (
      <rect
        key={opening.id}
        {...rect}
        data-testid={`opening-${opening.id}`}
        aria-label={`开口 ${opening.kind} ${opening.id}`}
        className="plan-opening"
        onClick={(event) => {
          event.stopPropagation();
          onSelect({ kind: "opening", id: opening.id });
        }}
        fill={isSelected ? "#d8f3f6" : "#e7f5f7"}
        stroke={isSelected ? "#227c68" : "#79adbc"}
        strokeWidth={isSelected ? 28 : 18}
        strokeDasharray="80 35"
      />
    );
  });

  const furnitureShapes = displayFurniture
    .filter((item) => item.visible !== false)
    .map((item) => {
      const bounds = furnitureBounds(item);
      const quarterTurns = Math.round(item.transform.rotation_z / 90);
      const rotated = Math.abs(quarterTurns) % 2 === 1;
      const localWidth = item.dimensions.width;
      const localDepth = item.dimensions.depth;
      const centerX = bounds.x + bounds.width / 2;
      const centerY = bounds.y + bounds.height / 2;
      const isSelected = selected(selection, "furniture", item.id);
      return (
        <g
          key={item.id}
          data-testid={`furniture-${item.id}`}
          aria-label={`家具 ${labelForFurniture(item)} ${item.id}`}
          transform={`translate(${centerX} ${centerY}) rotate(${item.transform.rotation_z}) translate(${-localWidth / 2} ${-localDepth / 2})`}
          onPointerDown={(event) => onFurniturePointerDown(event, item)}
          onClick={(event) => onFurnitureClick(event, item)}
        >
          {furnitureShape(item, isSelected, showDimensions)}
          {rotated && (
            <title>{`${labelForFurniture(item)} (${Math.round(bounds.width)} × ${Math.round(bounds.height)} mm)`}</title>
          )}
        </g>
      );
    });

  const patternId = `plan-grid-${gridId}`;
  return (
    <section className="plan-canvas" aria-label="2D floor plan canvas">
      <div
        className="canvas-toolbar"
        role="toolbar"
        aria-label="Plan canvas tools"
      >
        <button
          type="button"
          className={`icon-button${tool === "select" ? " is-active" : ""}`}
          aria-label="选择家具"
          title="选择"
          aria-pressed={tool === "select"}
          onClick={() => setTool("select")}
        >
          <MousePointer2 size={16} />
        </button>
        <button
          type="button"
          className={`icon-button${tool === "pan" ? " is-active" : ""}`}
          aria-label="平移画布"
          title="平移"
          aria-pressed={tool === "pan"}
          onClick={() => setTool("pan")}
        >
          <Hand size={16} />
        </button>
        <span className="canvas-toolbar-divider" aria-hidden="true" />
        <button
          type="button"
          className="icon-button"
          aria-label="放大"
          title="放大"
          onClick={() => zoom(0.8)}
        >
          <Plus size={16} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="缩小"
          title="缩小"
          onClick={() => zoom(1.25)}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="适合画布"
          title="适合画布"
          onClick={() => setViewBox(fitViewBox(model))}
        >
          <Maximize size={16} />
        </button>
        <label className="canvas-toggle">
          <input
            type="checkbox"
            checked={showDimensions}
            onChange={(event) => setShowDimensions(event.target.checked)}
          />{" "}
          <Ruler size={15} /> 尺寸
        </label>
        <label className="canvas-toggle">
          <input
            type="checkbox"
            checked={showGrid}
            onChange={(event) => setShowGrid(event.target.checked)}
          />{" "}
          <Grid3X3 size={15} /> 网格
        </label>
        {readOnly && (
          <span className="plan-label">
            <Check size={14} aria-hidden="true" /> 只读
          </span>
        )}
      </div>
      <svg
        ref={svgRef}
        tabIndex={0}
        className="plan-surface"
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        role="img"
        aria-label="Editable floor plan"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
      >
        <defs>
          <pattern
            id={patternId}
            width="500"
            height="500"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 500 0 L 0 0 0 500"
              fill="none"
              stroke="#e2e8f0"
              strokeWidth="8"
            />
          </pattern>
        </defs>
        {showGrid && (
          <rect
            x={viewBox.x - viewBox.width}
            y={viewBox.y - viewBox.height}
            width={viewBox.width * 3}
            height={viewBox.height * 3}
            fill={`url(#${patternId})`}
            pointerEvents="none"
          />
        )}
        <g>{roomShapes}</g>
        <g>{wallShapes}</g>
        <g>{openingShapes}</g>
        <g>{furnitureShapes}</g>
      </svg>
    </section>
  );
}

export default PlanCanvas;
