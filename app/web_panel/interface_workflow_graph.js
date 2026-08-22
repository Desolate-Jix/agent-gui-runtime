(function attachInterfaceWorkflowGraph(globalScope) {
  "use strict";

  function projectInterfaceWorkflowNode(node = {}) {
    const reviewStatus = String(node.review_status || "needs_human_review").toLowerCase();
    const evidenceStatus = String(node.evidence_status || "unknown").toLowerCase();
    const invalid = (
      reviewStatus.includes("invalid")
      || reviewStatus.includes("stale")
      || evidenceStatus.includes("invalid")
      || evidenceStatus.includes("stale")
      || evidenceStatus === "evidence_missing"
    );
    const reviewed = !invalid && (
      node.agent_usable === true
      || (
        node.reviewed_by_human === true
        && ["human_approved", "human_reviewed", "approved", "reviewed"].includes(reviewStatus)
      )
    );
    return {
      status_tone: invalid ? "invalid" : reviewed ? "reviewed" : "unreviewed",
      agent_usable: reviewed && node.agent_usable !== false,
    };
  }

  function buildInterfaceWorkflowTopology(graph = {}) {
    const allSourceNodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const allSourceEdges = Array.isArray(graph.edges) ? graph.edges : [];
    const focusNodeId = String(graph.focus?.node_id || "").trim();
    const sourceNodes = allSourceNodes;
    const sourceEdges = allSourceEdges;
    const interfaceIds = new Set(
      sourceNodes
        .map((node) => String(node?.node_id || "").trim())
        .filter(Boolean),
    );
    const validEdges = sourceEdges.filter((edge) => (
      interfaceIds.has(String(edge?.source_node_id || "").trim())
      && interfaceIds.has(String(edge?.target_node_id || "").trim())
      && String(edge?.edge_id || "").trim()
    ));
    const interfaceNodes = sourceNodes
      .filter((node) => interfaceIds.has(String(node?.node_id || "").trim()))
      .map((node) => {
        const evidence = node?.evidence && typeof node.evidence === "object"
          ? node.evidence
          : {};
        const controls = Array.isArray(node?.controls) ? node.controls : [];
        const reviewProjection = projectInterfaceWorkflowNode(node);
        return {
          id: `interface::${node.node_id}`,
          kind: "interface",
          ref_id: String(node.node_id),
          label: String(node.label || node.node_id),
          surface_type: String(node.surface_type || "unknown_surface"),
          evidence_status: String(node.evidence_status || "unknown"),
          review_status: String(node.review_status || "needs_human_review"),
          reviewed_by_human: node.reviewed_by_human === true,
          agent_usable: node.agent_usable === true,
          status_tone: reviewProjection.status_tone,
          evidence_path: String(
            evidence.human_review_overlay_path
            || evidence.fused_overlay_path
            || evidence.numbered_overlay_path
            || evidence.source_screenshot_path
            || "",
          ),
          control_count: controls.length,
          outgoing_count: validEdges.filter(
            (edge) => String(edge.source_node_id) === String(node.node_id),
          ).length,
          incoming_count: validEdges.filter(
            (edge) => String(edge.target_node_id) === String(node.node_id),
          ).length,
          selected: focusNodeId
            ? String(node.node_id) === focusNodeId
            : node.selected === true,
        };
      });
    const projectedByRefId = new Map(interfaceNodes.map((node) => [node.ref_id, node]));
    const links = validEdges.map((edge) => {
      const sourceNode = projectedByRefId.get(String(edge.source_node_id));
      const targetNode = projectedByRefId.get(String(edge.target_node_id));
      const endpointTones = [sourceNode?.status_tone, targetNode?.status_tone];
      const edgeReviewStatus = String(
        edge.review_status || "needs_human_review",
      ).toLowerCase();
      const edgeReviewed = [
        "human_approved",
        "human_reviewed",
        "approved",
        "reviewed",
      ].includes(edgeReviewStatus);
      const statusTone = endpointTones.includes("invalid")
        ? "invalid"
        : endpointTones.includes("unreviewed") || !edgeReviewed
          ? "unreviewed"
          : "reviewed";
      return {
        id: `transition::${edge.edge_id}`,
        kind: "interface_transition",
        ref_id: String(edge.edge_id),
        edge_id: String(edge.edge_id),
        source_id: `interface::${edge.source_node_id}`,
        target_id: `interface::${edge.target_node_id}`,
        source_node_id: String(edge.source_node_id),
        target_node_id: String(edge.target_node_id),
        label: String(edge.display_name || edge.action_type || edge.edge_id),
        action_type: String(edge.action_type || "unknown_action"),
        target_control_id: String(edge.target_control_id || ""),
        target_region_id: String(edge.target_region_id || ""),
        review_status: edgeReviewStatus,
        status_tone: statusTone,
      };
    });
    const connectedNodeIds = new Set(links.flatMap((link) => [link.source_id, link.target_id]));
    interfaceNodes.forEach((node) => {
      node.disconnected = interfaceNodes.length > 1 && !connectedNodeIds.has(node.id);
    });
    return {
      entry_node_id: focusNodeId || String(graph.workflow?.entry_node_id || ""),
      nodes: interfaceNodes,
      links,
    };
  }

  function summarizeWorkflowReadiness(topology = {}) {
    const nodes = Array.isArray(topology.nodes) ? topology.nodes : [];
    const summary = {
      status: "empty",
      reviewed: nodes.filter((node) => node.status_tone === "reviewed").length,
      unreviewed: nodes.filter((node) => node.status_tone === "unreviewed").length,
      invalid: nodes.filter((node) => node.status_tone === "invalid").length,
      total: nodes.length,
      agent_usable: false,
      interpretation: "workflow has no interface nodes",
    };
    if (!nodes.length) return summary;
    if (summary.invalid) {
      summary.status = "invalid_or_stale_present";
      summary.interpretation = "workflow contains invalid or stale interface evidence";
      return summary;
    }
    if (summary.unreviewed) {
      summary.status = "mixed_review_state";
      summary.interpretation = "workflow contains interfaces that Agent cannot use directly";
      return summary;
    }
    summary.status = "all_interfaces_reviewed";
    summary.agent_usable = true;
    summary.interpretation = "all interface evidence is reviewed; this is still not execution authorization";
    return summary;
  }

  function interfaceWorkflowNodeDiameter(node = {}) {
    const controlCount = Math.max(0, Number(node.control_count || 0));
    const degree = Math.max(
      0,
      Number(node.outgoing_count || 0) + Number(node.incoming_count || 0),
    );
    const controlBonus = Math.min(28, Math.log2(controlCount + 1) * 4);
    const degreeBonus = Math.min(28, degree * 8);
    const evidenceBonus = String(node.evidence_status || "") === "ready" ? 6 : 0;
    const selectedBonus = node.selected === true ? 14 : 0;
    return Math.round(Math.max(
      74,
      Math.min(
        132,
        72 + controlBonus + degreeBonus + evidenceBonus + selectedBonus,
      ),
    ));
  }

  function layoutInterfaceWorkflowTopology(topology = {}, viewport = {}) {
    const width = Math.max(320, Number(viewport.width) || 720);
    const height = Math.max(320, Number(viewport.height) || 520);
    const sourceNodes = Array.isArray(topology.nodes) ? topology.nodes : [];
    const sourceLinks = Array.isArray(topology.links) ? topology.links : [];
    const nodeById = new Map(sourceNodes.map((node) => [node.id, node]));
    const neighbours = new Map();
    sourceLinks.forEach((link) => {
      if (!nodeById.has(link.source_id) || !nodeById.has(link.target_id)) return;
      if (!neighbours.has(link.source_id)) neighbours.set(link.source_id, new Set());
      if (!neighbours.has(link.target_id)) neighbours.set(link.target_id, new Set());
      neighbours.get(link.source_id).add(link.target_id);
      neighbours.get(link.target_id).add(link.source_id);
    });

    const entryId = nodeById.has(`interface::${topology.entry_node_id}`)
      ? `interface::${topology.entry_node_id}`
      : sourceNodes[0]?.id;
    const layers = new Map();
    const queue = [];
    if (entryId) {
      layers.set(entryId, 0);
      queue.push(entryId);
    }
    while (queue.length) {
      const currentId = queue.shift();
      const nextLayer = Number(layers.get(currentId) || 0) + 1;
      (neighbours.get(currentId) || []).forEach((targetId) => {
        if (layers.has(targetId)) return;
        layers.set(targetId, nextLayer);
        queue.push(targetId);
      });
    }

    let maxLayer = layers.size ? Math.max(...layers.values()) : -1;
    sourceNodes.forEach((node) => {
      if (layers.has(node.id)) return;
      layers.set(node.id, Math.max(1, maxLayer + 1));
    });

    const grouped = new Map();
    sourceNodes.forEach((node) => {
      const layer = Number(layers.get(node.id) || 0);
      if (!grouped.has(layer)) grouped.set(layer, []);
      grouped.get(layer).push(node);
    });
    grouped.forEach((nodes) => nodes.sort(
      (left, right) => String(left.ref_id).localeCompare(String(right.ref_id)),
    ));

    const centre = { x: width / 2, y: height / 2 };
    const maximumNodeSize = Math.max(
      96,
      ...sourceNodes.map((node) => interfaceWorkflowNodeDiameter(node)),
    );
    const baseRadius = Math.max(156, Math.min(220, Math.min(width, height) * 0.34));
    const layoutNodes = [];
    Array.from(grouped.keys()).sort((a, b) => a - b).forEach((layer) => {
      const nodes = grouped.get(layer);
      const minimumRingRadius = nodes.length > 1
        ? (nodes.length * (maximumNodeSize + 28)) / (2 * Math.PI)
        : 0;
      const radius = layer === 0
        ? 0
        : Math.max(baseRadius * layer, minimumRingRadius);
      const angleOffset = layer % 2 === 0 ? 0 : -Math.PI / 2;
      nodes.forEach((node, index) => {
        const nodeSize = interfaceWorkflowNodeDiameter(node);
        const angle = nodes.length > 1
          ? angleOffset + (Math.PI * 2 * index) / nodes.length
          : angleOffset;
        layoutNodes.push({
          ...node,
          x: centre.x + Math.cos(angle) * radius,
          y: centre.y + Math.sin(angle) * radius,
          width: nodeSize,
          height: nodeSize,
          layer,
        });
      });
    });

    const positionedById = new Map(layoutNodes.map((node) => [node.id, node]));
    const layoutLinks = sourceLinks
      .map((link) => ({
        ...link,
        source: positionedById.get(link.source_id) || null,
        target: positionedById.get(link.target_id) || null,
      }))
      .filter((link) => link.source && link.target);
    const padding = 48;
    const minX = Math.min(0, ...layoutNodes.map((node) => node.x - node.width / 2 - padding));
    const minY = Math.min(0, ...layoutNodes.map((node) => node.y - node.height / 2 - padding));
    const maxX = Math.max(width, ...layoutNodes.map((node) => node.x + node.width / 2 + padding));
    const maxY = Math.max(height, ...layoutNodes.map((node) => node.y + node.height / 2 + padding));

    return {
      nodes: layoutNodes,
      links: layoutLinks,
      bounds: {
        x: minX,
        y: minY,
        width: maxX - minX,
        height: maxY - minY,
      },
    };
  }

  function updateInterfaceWorkflowLayoutBounds(layout = {}, viewport = {}) {
    const width = Math.max(320, Number(viewport.width) || 720);
    const height = Math.max(320, Number(viewport.height) || 520);
    const nodes = Array.isArray(layout.nodes) ? layout.nodes : [];
    const padding = 48;
    const minX = Math.min(0, ...nodes.map((node) => node.x - node.width / 2 - padding));
    const minY = Math.min(0, ...nodes.map((node) => node.y - node.height / 2 - padding));
    const maxX = Math.max(width, ...nodes.map((node) => node.x + node.width / 2 + padding));
    const maxY = Math.max(height, ...nodes.map((node) => node.y + node.height / 2 + padding));
    layout.bounds = {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
    };
    return layout.bounds;
  }

  function createInterfaceWorkflowSimulation(topology = {}, viewport = {}, options = {}) {
    const width = Math.max(320, Number(viewport.width) || 720);
    const height = Math.max(320, Number(viewport.height) || 520);
    const initialLayout = layoutInterfaceWorkflowTopology(topology, { width, height });
    const previousNodes = new Map(
      (Array.isArray(options.previousLayout?.nodes) ? options.previousLayout.nodes : [])
        .map((node) => [String(node.id || ""), node]),
    );
    const nodes = initialLayout.nodes.map((node) => {
      const previous = previousNodes.get(node.id);
      return {
        ...node,
        x: Number.isFinite(Number(previous?.x)) ? Number(previous.x) : node.x,
        y: Number.isFinite(Number(previous?.y)) ? Number(previous.y) : node.y,
        vx: 0,
        vy: 0,
      };
    });
    let hasRetainedOverlap = false;
    for (let leftIndex = 0; leftIndex < nodes.length && !hasRetainedOverlap; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        const minimumDistance = (
          Math.max(left.width, left.height)
          + Math.max(right.width, right.height)
        ) / 2;
        if (Math.hypot(left.x - right.x, left.y - right.y) < minimumDistance) {
          hasRetainedOverlap = true;
          break;
        }
      }
    }
    if (hasRetainedOverlap) {
      const initialNodeById = new Map(initialLayout.nodes.map((node) => [node.id, node]));
      nodes.forEach((node) => {
        const initialNode = initialNodeById.get(node.id);
        node.x = initialNode.x;
        node.y = initialNode.y;
      });
    }
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const links = initialLayout.links.map((link) => ({
      ...link,
      source: nodeById.get(link.source_id),
      target: nodeById.get(link.target_id),
    }));
    const entryId = nodeById.has(`interface::${topology.entry_node_id}`)
      ? `interface::${topology.entry_node_id}`
      : nodes[0]?.id;
    const centre = { x: width / 2, y: height / 2 };
    const config = {
      alphaDecay: Number(options.alphaDecay) || 0.045,
      alphaMin: Number(options.alphaMin) || 0.0025,
      centerStrength: Number(options.centerStrength) || 0.006,
      chargeStrength: Number(options.chargeStrength) || 2400,
      collisionPadding: Number(options.collisionPadding) || 20,
      linkDistance: Number(options.linkDistance) || 188,
      linkStrength: Number(options.linkStrength) || 0.055,
      velocityDecay: Number(options.velocityDecay) || 0.72,
    };
    const layout = {
      nodes,
      links,
      bounds: initialLayout.bounds,
    };
    updateInterfaceWorkflowLayoutBounds(layout, { width, height });
    let alpha = 1;

    function applyIteration() {
      alpha *= 1 - config.alphaDecay;

      nodes.forEach((node) => {
        if (node.id === entryId) return;
        node.vx += (centre.x - node.x) * config.centerStrength * alpha;
        node.vy += (centre.y - node.y) * config.centerStrength * alpha;
      });

      links.forEach((link) => {
        if (!link.source || !link.target || link.source === link.target) return;
        const dx = link.target.x - link.source.x;
        const dy = link.target.y - link.source.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const spring = (
          (distance - config.linkDistance)
          * config.linkStrength
          * alpha
          / distance
        );
        const offsetX = dx * spring * 0.5;
        const offsetY = dy * spring * 0.5;
        if (link.source.id !== entryId) {
          link.source.vx += offsetX;
          link.source.vy += offsetY;
        }
        if (link.target.id !== entryId) {
          link.target.vx -= offsetX;
          link.target.vy -= offsetY;
        }
      });

      for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
          const left = nodes[leftIndex];
          const right = nodes[rightIndex];
          let dx = right.x - left.x;
          let dy = right.y - left.y;
          if (Math.abs(dx) + Math.abs(dy) < 0.001) {
            dx = ((leftIndex + 1) * 0.61803398875) % 1 - 0.5;
            dy = ((rightIndex + 1) * 0.38196601125) % 1 - 0.5;
          }
          const distance = Math.max(1, Math.hypot(dx, dy));
          const unitX = dx / distance;
          const unitY = dy / distance;
          const repulsion = (config.chargeStrength * alpha) / (distance * distance);
          const minimumDistance = (
            Math.max(left.width, left.height)
            + Math.max(right.width, right.height)
          ) / 2 + config.collisionPadding;
          const collision = distance < minimumDistance
            ? (minimumDistance - distance) * 0.12 * alpha
            : 0;
          const force = repulsion + collision;
          if (left.id !== entryId) {
            left.vx -= unitX * force;
            left.vy -= unitY * force;
          }
          if (right.id !== entryId) {
            right.vx += unitX * force;
            right.vy += unitY * force;
          }
        }
      }

      nodes.forEach((node) => {
        if (node.id === entryId) {
          node.x = centre.x;
          node.y = centre.y;
          node.vx = 0;
          node.vy = 0;
          return;
        }
        node.vx *= config.velocityDecay;
        node.vy *= config.velocityDecay;
        node.x += node.vx;
        node.y += node.vy;
      });
      updateInterfaceWorkflowLayoutBounds(layout, { width, height });
    }

    return {
      layout,
      step(iterations = 1) {
        const count = Math.max(1, Math.floor(Number(iterations) || 1));
        for (let index = 0; index < count && alpha > config.alphaMin; index += 1) {
          applyIteration();
        }
        return layout;
      },
      isSettled() {
        return alpha <= config.alphaMin;
      },
      runToCompletion(maxIterations = 360) {
        const limit = Math.max(1, Math.floor(Number(maxIterations) || 1));
        let iterations = 0;
        while (iterations < limit && alpha > config.alphaMin) {
          applyIteration();
          iterations += 1;
        }
        return layout;
      },
      alpha() {
        return alpha;
      },
    };
  }

  function interfaceWorkflowHoverProjection(layout = {}, hoveredNodeId = "") {
    const nodes = Array.isArray(layout.nodes) ? layout.nodes : [];
    const links = Array.isArray(layout.links) ? layout.links : [];
    const normalizedHoveredNodeId = String(hoveredNodeId || "").trim();
    if (!normalizedHoveredNodeId || !nodes.some((node) => node.id === normalizedHoveredNodeId)) {
      return {
        hovered_node_id: "",
        highlighted_node_ids: [],
        highlighted_link_ids: [],
        dimmed_node_ids: [],
        dimmed_link_ids: [],
      };
    }

    const highlightedNodeIds = new Set([normalizedHoveredNodeId]);
    const highlightedLinkIds = new Set();
    links.forEach((link) => {
      if (
        link.source_id !== normalizedHoveredNodeId
        && link.target_id !== normalizedHoveredNodeId
      ) {
        return;
      }
      highlightedLinkIds.add(link.id);
      highlightedNodeIds.add(link.source_id);
      highlightedNodeIds.add(link.target_id);
    });
    return {
      hovered_node_id: normalizedHoveredNodeId,
      highlighted_node_ids: Array.from(highlightedNodeIds),
      highlighted_link_ids: Array.from(highlightedLinkIds),
      dimmed_node_ids: nodes
        .map((node) => node.id)
        .filter((nodeId) => !highlightedNodeIds.has(nodeId)),
      dimmed_link_ids: links
        .map((link) => link.id)
        .filter((linkId) => !highlightedLinkIds.has(linkId)),
    };
  }

  function hitTestInterfaceWorkflowNode(layout = {}, point = {}) {
    const x = Number(point.x);
    const y = Number(point.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const nodes = Array.isArray(layout?.nodes) ? layout.nodes : [];
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const node = nodes[index];
      if (
        x >= node.x - node.width / 2
        && x <= node.x + node.width / 2
        && y >= node.y - node.height / 2
        && y <= node.y + node.height / 2
      ) {
        return node;
      }
    }
    return null;
  }

  function fitInterfaceWorkflowLayout(bounds = {}, viewport = {}, padding = 24) {
    const width = Math.max(1, Number(viewport.width) || 1);
    const height = Math.max(1, Number(viewport.height) || 1);
    const inset = Math.max(0, Number(padding) || 0);
    const boundsX = Number(bounds.x) || 0;
    const boundsY = Number(bounds.y) || 0;
    const boundsWidth = Math.max(1, Number(bounds.width) || width);
    const boundsHeight = Math.max(1, Number(bounds.height) || height);
    const zoom = Math.min(
      1,
      Math.max(0.1, (width - inset * 2) / boundsWidth),
      Math.max(0.1, (height - inset * 2) / boundsHeight),
    );
    return {
      zoom,
      pan: {
        x: width / 2 - (boundsX + boundsWidth / 2) * zoom,
        y: height / 2 - (boundsY + boundsHeight / 2) * zoom,
      },
    };
  }

  function interfaceWorkflowEdgeGeometry(source = {}, target = {}, index = 0) {
    const sourceX = Number(source.x || 0);
    const sourceY = Number(source.y || 0);
    const targetX = Number(target.x || 0);
    const targetY = Number(target.y || 0);
    const sourceRadius = Math.min(
      Math.max(1, Number(source.width || 0)),
      Math.max(1, Number(source.height || 0)),
    ) / 2;
    const targetRadius = Math.min(
      Math.max(1, Number(target.width || 0)),
      Math.max(1, Number(target.height || 0)),
    ) / 2;
    const dx = targetX - sourceX;
    const dy = targetY - sourceY;
    const distance = Math.hypot(dx, dy);
    if (distance < 1) {
      return {
        start: {
          x: sourceX + sourceRadius * 0.7,
          y: sourceY - sourceRadius * 0.7,
        },
        control: {
          x: sourceX,
          y: sourceY - sourceRadius * 1.9,
        },
        end: {
          x: sourceX - sourceRadius * 0.7,
          y: sourceY - sourceRadius * 0.7,
        },
      };
    }
    const unitX = dx / distance;
    const unitY = dy / distance;
    const normalX = -unitY;
    const normalY = unitX;
    const offset = ((Number(index || 0) % 3) - 1) * 10;
    return {
      start: {
        x: sourceX + unitX * sourceRadius,
        y: sourceY + unitY * sourceRadius,
      },
      control: {
        x: (sourceX + targetX) / 2 + normalX * offset,
        y: (sourceY + targetY) / 2 + normalY * offset,
      },
      end: {
        x: targetX - unitX * targetRadius,
        y: targetY - unitY * targetRadius,
      },
    };
  }

  function interfaceWorkflowEdgeLabelPose(source = {}, target = {}, index = 0, offset = 6) {
    const curve = interfaceWorkflowEdgeGeometry(source, target, index);
    const progress = 0.5;
    const inverse = 1 - progress;
    const x = (
      inverse * inverse * curve.start.x
      + 2 * inverse * progress * curve.control.x
      + progress * progress * curve.end.x
    );
    const y = (
      inverse * inverse * curve.start.y
      + 2 * inverse * progress * curve.control.y
      + progress * progress * curve.end.y
    );
    const tangentX = (
      2 * inverse * (curve.control.x - curve.start.x)
      + 2 * progress * (curve.end.x - curve.control.x)
    );
    const tangentY = (
      2 * inverse * (curve.control.y - curve.start.y)
      + 2 * progress * (curve.end.y - curve.control.y)
    );
    const tangentLength = Math.max(1, Math.hypot(tangentX, tangentY));
    let normalX = -tangentY / tangentLength;
    let normalY = tangentX / tangentLength;
    if (normalY > 0) {
      normalX *= -1;
      normalY *= -1;
    }
    let angle = Math.atan2(tangentY, tangentX);
    if (angle > Math.PI / 2) angle -= Math.PI;
    if (angle < -Math.PI / 2) angle += Math.PI;
    return {
      x: x + normalX * offset,
      y: y + normalY * offset,
      angle,
    };
  }

  function interfaceWorkflowEdgeLabelLayout(source = {}, target = {}, index = 0) {
    const curve = interfaceWorkflowEdgeGeometry(source, target, index);
    const midpoint = 0.5;
    const sampleCount = 12;
    let firstHalfLength = 0;
    let secondHalfLength = 0;
    let previous = curve.start;
    for (let sampleIndex = 1; sampleIndex <= sampleCount; sampleIndex += 1) {
      const progress = sampleIndex / sampleCount;
      const inverse = 1 - progress;
      const point = {
        x: (
          inverse * inverse * curve.start.x
          + 2 * inverse * progress * curve.control.x
          + progress * progress * curve.end.x
        ),
        y: (
          inverse * inverse * curve.start.y
          + 2 * inverse * progress * curve.control.y
          + progress * progress * curve.end.y
        ),
      };
      const segmentLength = Math.hypot(point.x - previous.x, point.y - previous.y);
      if (progress <= midpoint) {
        firstHalfLength += segmentLength;
      } else {
        secondHalfLength += segmentLength;
      }
      previous = point;
    }
    const clearSpan = Math.max(0, 2 * Math.min(firstHalfLength, secondHalfLength));
    const maxWidth = Math.max(0, Math.min(112, Math.floor(clearSpan - 16)));
    const fontSize = maxWidth >= 84 ? 8 : maxWidth >= 48 ? 7.5 : 7;
    return {
      ...interfaceWorkflowEdgeLabelPose(source, target, index),
      visible: maxWidth >= 24,
      max_width: maxWidth,
      font_size: fontSize,
      clear_span: clearSpan,
    };
  }

  function finitePositive(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }

  function normalizedBbox(value) {
    if (Array.isArray(value) && value.length >= 4) {
      const [xValue, yValue, widthValue, heightValue] = value;
      const x = Number(xValue);
      const y = Number(yValue);
      const width = finitePositive(widthValue);
      const height = finitePositive(heightValue);
      return Number.isFinite(x) && Number.isFinite(y) && width && height
        ? { x, y, width, height }
        : null;
    }
    if (!value || typeof value !== "object") return null;
    const x = Number(value.x ?? value.left ?? value.x1);
    const y = Number(value.y ?? value.top ?? value.y1);
    const width = finitePositive(
      value.width
      ?? value.w
      ?? (Number.isFinite(Number(value.x2)) ? Number(value.x2) - x : null),
    );
    const height = finitePositive(
      value.height
      ?? value.h
      ?? (Number.isFinite(Number(value.y2)) ? Number(value.y2) - y : null),
    );
    return Number.isFinite(x) && Number.isFinite(y) && width && height
      ? { x, y, width, height }
      : null;
  }

  function normalizedViewport(value) {
    if (Array.isArray(value) && value.length >= 2) {
      const width = finitePositive(value[0]);
      const height = finitePositive(value[1]);
      return width && height ? { width, height } : null;
    }
    if (!value || typeof value !== "object") return null;
    const width = finitePositive(value.width ?? value.w);
    const height = finitePositive(value.height ?? value.h);
    return width && height ? { width, height } : null;
  }

  function interfaceWorkflowEvidenceItemId(item = {}) {
    if (!item || typeof item !== "object") return "";
    return String(
      item.control_id
      || item.region_id
      || item.component_id
      || item.action_template_id
      || item.action_id
      || item.object_id
      || item.id
      || "",
    ).trim();
  }

  function resolveInterfaceWorkflowTargetEvidence(node = {}, operation = {}, viewportOverride = null) {
    const targetId = String(
      operation?.target_control_id
      || operation?.target_region_id
      || "",
    ).trim();
    if (!targetId) return null;
    const candidates = [
      ...(Array.isArray(node?.controls) ? node.controls : []),
      ...(Array.isArray(node?.regions) ? node.regions : []),
      ...(Array.isArray(node?.action_candidates) ? node.action_candidates : []),
    ];
    const target = candidates.find((item) => interfaceWorkflowEvidenceItemId(item) === targetId);
    const bbox = normalizedBbox(
      target?.bbox
      || target?.bounds
      || target?.target_bbox
      || target?.region_bbox,
    );
    const viewport = [
      viewportOverride,
      node?.evidence?.viewport_size,
      node?.viewport_size,
      node?.page_details?.viewport_size,
      node?.page_details?.screen?.viewport_size,
      node?.page_details?.screen?.source_viewport,
    ].map(normalizedViewport).find(Boolean) || null;
    if (!bbox || !viewport) return null;
    if (
      bbox.x < 0
      || bbox.y < 0
      || bbox.x + bbox.width > viewport.width
      || bbox.y + bbox.height > viewport.height
    ) {
      return null;
    }
    return {
      target_id: targetId,
      bbox,
      viewport,
      normalized: {
        left: bbox.x / viewport.width,
        top: bbox.y / viewport.height,
        width: bbox.width / viewport.width,
        height: bbox.height / viewport.height,
      },
    };
  }

  function interfaceWorkflowNodePresentation(node = {}, options = {}) {
    const english = String(options.language || "").toLowerCase().startsWith("en");
    const copy = english
      ? {
        unnamed_interface: "Unnamed interface",
        unnamed_operation: "Unnamed operation",
        unnamed_control: "Unnamed control",
        invalid: "Invalid evidence",
        learning: "Needs learning",
        reviewed: "Reviewed",
        unreviewed: "Pending review",
        operation_path: "Operation path",
        interface_control: "Interface control",
        selected: "Selected",
      }
      : {
        unnamed_interface: "未命名界面",
        unnamed_operation: "未命名操作",
        unnamed_control: "未命名控件",
        invalid: "证据无效",
        learning: "待学习",
        reviewed: "已审核",
        unreviewed: "待审核",
        operation_path: "操作路径",
        interface_control: "界面控件",
        selected: "已选择",
      };
    const kind = String(node.kind || "");
    if (kind === "interface") {
      const statusTone = String(node.status_tone || projectInterfaceWorkflowNode(node).status_tone);
      const needsLearning = String(node.evidence_status || "") === "needs_learning";
      return {
        title: String(node.label || node.ref_id || copy.unnamed_interface),
        subtitle: String(node.surface_type || "unknown_surface"),
        meta: english
          ? `${Number(node.control_count || 0)} controls · ${Number(node.outgoing_count || 0)} paths`
          : `${Number(node.control_count || 0)} 个控件 · ${Number(node.outgoing_count || 0)} 条路径`,
        status: statusTone === "invalid"
          ? copy.invalid
          : needsLearning
            ? copy.learning
            : statusTone === "reviewed" ? copy.reviewed : copy.unreviewed,
        status_tone: statusTone === "invalid"
          ? "invalid"
          : needsLearning ? "learning" : statusTone,
      };
    }
    if (kind === "operation") {
      const reviewed = ["human_reviewed", "approved", "reviewed"].includes(
        String(node.review_status || "").toLowerCase(),
      );
      return {
        title: String(node.label || node.ref_id || copy.unnamed_operation),
        subtitle: String(node.action_type || "unknown_action"),
        meta: copy.operation_path,
        status: reviewed ? copy.reviewed : copy.unreviewed,
        status_tone: reviewed ? "reviewed" : "review",
      };
    }
    return {
      title: String(node.label || node.ref_id || copy.unnamed_control),
      subtitle: String(node.role || "control"),
      meta: copy.interface_control,
      status: node.selected === true ? copy.selected : "",
      status_tone: node.selected === true ? "selected" : "neutral",
    };
  }

  const api = {
    buildInterfaceWorkflowTopology,
    projectInterfaceWorkflowNode,
    summarizeWorkflowReadiness,
    layoutInterfaceWorkflowTopology,
    createInterfaceWorkflowSimulation,
    interfaceWorkflowHoverProjection,
    fitInterfaceWorkflowLayout,
    interfaceWorkflowEdgeGeometry,
    interfaceWorkflowEdgeLabelPose,
    interfaceWorkflowEdgeLabelLayout,
    hitTestInterfaceWorkflowNode,
    resolveInterfaceWorkflowTargetEvidence,
    interfaceWorkflowNodePresentation,
    interfaceWorkflowNodeDiameter,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  globalScope.InterfaceWorkflowGraph = api;
}(typeof globalThis !== "undefined" ? globalThis : this));
