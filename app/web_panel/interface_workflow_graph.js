(function attachInterfaceWorkflowGraph(globalScope) {
  "use strict";

  function buildInterfaceWorkflowTopology(graph = {}) {
    const sourceNodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const sourceEdges = Array.isArray(graph.edges) ? graph.edges : [];
    const interfaceIds = new Set(
      sourceNodes
        .map((node) => String(node?.node_id || "").trim())
        .filter(Boolean),
    );
    const interfaceNodes = sourceNodes
      .filter((node) => interfaceIds.has(String(node?.node_id || "").trim()))
      .map((node) => ({
        id: `interface::${node.node_id}`,
        kind: "interface",
        ref_id: String(node.node_id),
        label: String(node.label || node.node_id),
        surface_type: String(node.surface_type || "unknown_surface"),
        evidence_status: String(node.evidence_status || "unknown"),
        selected: node.selected === true,
      }));
    const validEdges = sourceEdges.filter((edge) => (
      interfaceIds.has(String(edge?.source_node_id || "").trim())
      && interfaceIds.has(String(edge?.target_node_id || "").trim())
      && String(edge?.edge_id || "").trim()
    ));
    const operationNodes = validEdges.map((edge) => ({
      id: `operation::${edge.edge_id}`,
      kind: "operation",
      ref_id: String(edge.edge_id),
      source_node_id: String(edge.source_node_id),
      target_node_id: String(edge.target_node_id),
      label: String(edge.display_name || edge.action_type || edge.edge_id),
      action_type: String(edge.action_type || "unknown_action"),
      review_status: String(edge.review_status || "needs_human_review"),
      selected: edge.selected === true,
    }));
    const links = validEdges.flatMap((edge) => [
      {
        id: `source::${edge.edge_id}`,
        source_id: `interface::${edge.source_node_id}`,
        target_id: `operation::${edge.edge_id}`,
        kind: "source_operation",
        edge_id: String(edge.edge_id),
      },
      {
        id: `target::${edge.edge_id}`,
        source_id: `operation::${edge.edge_id}`,
        target_id: `interface::${edge.target_node_id}`,
        kind: "operation_target",
        edge_id: String(edge.edge_id),
      },
    ]);
    return {
      entry_node_id: String(graph.workflow?.entry_node_id || ""),
      nodes: [...interfaceNodes, ...operationNodes],
      links,
    };
  }

  function layoutInterfaceWorkflowTopology(topology = {}, viewport = {}) {
    const width = Math.max(320, Number(viewport.width) || 720);
    const height = Math.max(320, Number(viewport.height) || 520);
    const sourceNodes = Array.isArray(topology.nodes) ? topology.nodes : [];
    const sourceLinks = Array.isArray(topology.links) ? topology.links : [];
    const nodeById = new Map(sourceNodes.map((node) => [node.id, node]));
    const outgoing = new Map();
    sourceLinks.forEach((link) => {
      if (!nodeById.has(link.source_id) || !nodeById.has(link.target_id)) return;
      if (!outgoing.has(link.source_id)) outgoing.set(link.source_id, []);
      outgoing.get(link.source_id).push(link.target_id);
    });

    const entryId = nodeById.has(`interface::${topology.entry_node_id}`)
      ? `interface::${topology.entry_node_id}`
      : sourceNodes.find((node) => node.kind === "interface")?.id;
    const layers = new Map();
    const queue = [];
    if (entryId) {
      layers.set(entryId, 0);
      queue.push(entryId);
    }
    while (queue.length) {
      const currentId = queue.shift();
      const nextLayer = Number(layers.get(currentId) || 0) + 1;
      (outgoing.get(currentId) || []).forEach((targetId) => {
        if (layers.has(targetId)) return;
        layers.set(targetId, nextLayer);
        queue.push(targetId);
      });
    }

    let maxLayer = layers.size ? Math.max(...layers.values()) : -1;
    sourceNodes.forEach((node) => {
      if (layers.has(node.id)) return;
      maxLayer += 1;
      layers.set(node.id, maxLayer);
    });

    const grouped = new Map();
    sourceNodes.forEach((node) => {
      const layer = Number(layers.get(node.id) || 0);
      if (!grouped.has(layer)) grouped.set(layer, []);
      grouped.get(layer).push(node);
    });
    grouped.forEach((nodes) => {
      nodes.sort((left, right) => (
        String(left.kind).localeCompare(String(right.kind))
        || String(left.ref_id).localeCompare(String(right.ref_id))
      ));
    });

    const layerGap = 190;
    const leftPadding = 90;
    const topPadding = 58;
    const rowGap = 86;
    const layoutNodes = [];
    Array.from(grouped.keys()).sort((a, b) => a - b).forEach((layer) => {
      const nodes = grouped.get(layer);
      const requiredHeight = topPadding * 2 + Math.max(0, nodes.length - 1) * rowGap;
      const canvasHeight = Math.max(height, requiredHeight);
      const availableHeight = Math.max(1, canvasHeight - topPadding * 2);
      const spacing = nodes.length > 1 ? availableHeight / (nodes.length - 1) : 0;
      nodes.forEach((node, index) => {
        const isInterface = node.kind === "interface";
        layoutNodes.push({
          ...node,
          x: leftPadding + layer * layerGap,
          y: nodes.length > 1 ? topPadding + index * spacing : canvasHeight / 2,
          width: isInterface ? 148 : 124,
          height: isInterface ? 62 : 46,
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
    const contentWidth = Math.max(
      width,
      ...layoutNodes.map((node) => node.x + node.width / 2 + leftPadding),
    );
    const contentHeight = Math.max(
      height,
      ...layoutNodes.map((node) => node.y + node.height / 2 + topPadding),
    );

    return {
      nodes: layoutNodes,
      links: layoutLinks,
      bounds: {
        width: contentWidth,
        height: contentHeight,
      },
    };
  }

  function hitTestInterfaceWorkflowNode(layout = {}, point = {}) {
    const x = Number(point.x);
    const y = Number(point.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const nodes = Array.isArray(layout.nodes) ? layout.nodes : [];
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

  const api = {
    buildInterfaceWorkflowTopology,
    layoutInterfaceWorkflowTopology,
    hitTestInterfaceWorkflowNode,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  globalScope.InterfaceWorkflowGraph = api;
}(typeof globalThis !== "undefined" ? globalThis : this));
