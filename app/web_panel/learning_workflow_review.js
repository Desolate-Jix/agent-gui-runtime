(function attachInterfaceWorkflowReview(globalScope) {
  "use strict";

  const CONTRACT_VERSION = "single_application_workflow_review_v1";
  const LAYER_PATH_KEYS = {
    human_review: "human_review_overlay_path",
    fused: "fused_overlay_path",
    numbered: "numbered_overlay_path",
    source: "source_screenshot_path",
  };
  const DEFAULT_LAYER_ORDER = ["human_review", "fused", "numbered", "source"];
  const ALLOWED_ACTION_TYPES = new Set([
    "back",
    "close_modal",
    "continue_next_step",
    "fill_field",
    "open_apply_flow",
    "open_detail",
    "read",
    "scroll",
    "select_option",
    "unknown_action",
    "wait",
  ]);
  const FORBIDDEN_ACTION_TYPES = new Set([
    "confirm",
    "delete",
    "final_submit",
    "payment",
    "send",
    "submit",
  ]);

  function createLatestInterfaceWorkflowLoadGuard() {
    let latestToken = 0;
    return {
      begin() {
        latestToken += 1;
        return latestToken;
      },
      isCurrent(token) {
        return token === latestToken;
      },
    };
  }
  const EDITABLE_NODE_FIELDS = new Set([
    "display_name",
    "surface_type",
    "review_status",
    "regions",
    "controls",
    "action_candidates",
    "blockers",
    "content_descriptors",
    "verification_rules",
    "manual_revision",
  ]);
  const EDITABLE_EDGE_FIELDS = new Set([
    "display_name",
    "agent_description",
    "operation_id",
    "action_type",
    "target_node_id",
    "target_region_id",
    "target_control_id",
    "risk_level",
    "requires_user_confirmation",
    "preconditions",
    "success_conditions",
    "failure_conditions",
    "review_status",
  ]);

  function clone(value) {
    if (typeof structuredClone === "function") {
      return structuredClone(value);
    }
    return JSON.parse(JSON.stringify(value));
  }

  function nonEmptyString(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function userFacingLearningLabel(value) {
    return String(value || "")
      .trim()
      .replace(/\bUI hierarchy draft\b/gi, "UI hierarchy")
      .replace(
        /\blearning draft\b/gi,
        (match) => (match[0] === match[0].toUpperCase() ? "Learning result" : "learning result"),
      )
      .replace(/学习草稿/g, "学习结果");
  }

  function interfaceWorkflowControlChoices(node = {}) {
    const sourceItems = Array.isArray(node?.controls) && node.controls.length
      ? node.controls
      : Array.isArray(node?.regions)
        ? node.regions
        : [];
    return sourceItems.map((item) => ({
      control_id: String(item?.control_id || item?.region_id || "").trim(),
      label: String(
        item?.label
        || item?.name
        || item?.control_id
        || item?.region_id
        || "未命名控件",
      ).trim(),
      role: String(item?.role || item?.kind || "control").trim(),
    })).filter((item) => item.control_id);
  }

  function createInterfaceWorkflowWorkbenchState() {
    const state = {
      evidence_mode: "workflow",
      evidence_node_id: "",
      correction_open: false,
      link_source_node_id: "",
      link_target_node_id: "",
    };
    return {
      current() {
        return clone(state);
      },
      showWorkflowNode(nodeId) {
        state.evidence_mode = "workflow";
        state.evidence_node_id = String(nodeId || "").trim();
        return this.current();
      },
      showSourcePreview(nodeId) {
        state.evidence_mode = "source_preview";
        state.evidence_node_id = String(nodeId || "").trim();
        return this.current();
      },
      setCorrectionOpen(open) {
        state.correction_open = Boolean(open);
        return this.current();
      },
      startLink(sourceNodeId) {
        state.link_source_node_id = String(sourceNodeId || "").trim();
        state.link_target_node_id = "";
        return this.current();
      },
      chooseLinkTarget(targetNodeId) {
        state.link_target_node_id = String(targetNodeId || "").trim();
        return {
          source_node_id: state.link_source_node_id,
          target_node_id: state.link_target_node_id,
        };
      },
      clearLink() {
        state.link_source_node_id = "";
        state.link_target_node_id = "";
        return this.current();
      },
    };
  }

  function normalizedIdentifier(value, fallback) {
    const normalized = String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, "_")
      .replace(/^[_\-.]+|[_\-.]+$/g, "");
    return normalized || fallback;
  }

  function normalizedActionType(value) {
    const actionType = String(value || "unknown_action").trim().toLowerCase();
    if (FORBIDDEN_ACTION_TYPES.has(actionType)) {
      throw new Error(`forbidden review action type: ${actionType}`);
    }
    if (!ALLOWED_ACTION_TYPES.has(actionType)) {
      throw new Error(`unsupported review action type: ${actionType}`);
    }
    return actionType;
  }

  function createEmptyInterfaceWorkflowReview(options = {}) {
    const workflowId = normalizedIdentifier(options.workflowId, "software_workflow");
    const goal = String(options.goal || "").trim() || "Review learned interfaces";
    const applicationIdentity = options.applicationIdentity && typeof options.applicationIdentity === "object"
      ? clone(options.applicationIdentity)
      : {};
    return {
      contract_version: CONTRACT_VERSION,
      workflow: {
        workflow_id: workflowId,
        goal,
        application_identity: applicationIdentity,
        entry_node_id: "",
        node_ids: [],
        edge_ids: [],
        review_status: "needs_human_review",
        published_memory_version: null,
      },
      nodes: [],
      edges: [],
      display_only: true,
      artifact_is_authorization: false,
      execute_binding_enabled: false,
    };
  }

  function createInterfaceWorkflowReviewState(inputReview) {
    if (!inputReview || inputReview.contract_version !== CONTRACT_VERSION) {
      throw new Error("unsupported interface workflow review contract");
    }

    const review = clone(inputReview);
    const nodes = Array.isArray(review.nodes) ? review.nodes : [];
    const edges = Array.isArray(review.edges) ? review.edges : [];
    const nodeById = new Map(nodes.map((node) => [node.node_id, node]));
    const entryNodeId = review.workflow && review.workflow.entry_node_id;
    let selectedNodeId = nodeById.has(entryNodeId)
      ? entryNodeId
      : (nodes[0] && nodes[0].node_id) || "";
    let selectedLayer = "";
    let focusedNodeId = "";
    let selectedControlId = "";

    function nodeControls(node) {
      const controls = Array.isArray(node?.controls) ? node.controls : [];
      if (controls.length) return controls;
      return Array.isArray(node?.regions) ? node.regions : [];
    }

    function availableLayers(node) {
      const evidence = (node && node.evidence) || {};
      return DEFAULT_LAYER_ORDER
        .filter((layer) => nonEmptyString(evidence[LAYER_PATH_KEYS[layer]]))
        .map((layer) => ({
          layer,
          path: evidence[LAYER_PATH_KEYS[layer]],
        }));
    }

    function current() {
      const node = nodeById.get(selectedNodeId) || null;
      if (!node) {
        return {
          node: null,
          evidence_status: "node_missing",
          active_layer: "",
          active_image_path: "",
          available_layers: [],
          incoming_edges: [],
          outgoing_edges: [],
        };
      }

      const layers = availableLayers(node);
      const activeEntry = layers.find((entry) => entry.layer === selectedLayer) || layers[0] || null;

      return {
        node,
        selected_control: nodeControls(node).find(
          (control) => String(control?.control_id || control?.region_id || "") === selectedControlId,
        ) || null,
        evidence_status: node.evidence_status || (activeEntry ? "ready" : "screenshot_missing"),
        active_layer: activeEntry ? activeEntry.layer : "",
        active_image_path: activeEntry ? activeEntry.path : "",
        available_layers: layers,
        incoming_edges: edges.filter((edge) => edge.target_node_id === node.node_id),
        outgoing_edges: edges.filter((edge) => edge.source_node_id === node.node_id),
      };
    }

    function select(nodeId) {
      if (!nodeById.has(nodeId)) {
        throw new Error(`unknown interface workflow node: ${nodeId}`);
      }
      selectedNodeId = nodeId;
      selectedLayer = "";
      selectedControlId = "";
      return current();
    }

    function focusInterface(nodeId) {
      select(nodeId);
      focusedNodeId = nodeId;
      return graph();
    }

    function focusControl(controlId) {
      const node = nodeById.get(selectedNodeId);
      const controls = nodeControls(node);
      const normalizedControlId = String(controlId || "").trim();
      if (!controls.some(
        (control) => String(control?.control_id || control?.region_id || "").trim() === normalizedControlId,
      )) {
        throw new Error(`unknown interface workflow control: ${normalizedControlId}`);
      }
      focusedNodeId = selectedNodeId;
      selectedControlId = normalizedControlId;
      return graph();
    }

    function clearFocus() {
      focusedNodeId = "";
      selectedControlId = "";
      return graph();
    }

    function selectLayer(layer) {
      const node = nodeById.get(selectedNodeId);
      if (!node) {
        return current();
      }
      const layers = availableLayers(node);
      if (!layers.some((entry) => entry.layer === layer)) {
        throw new Error(`evidence layer is unavailable for node ${node.node_id}: ${layer}`);
      }
      selectedLayer = layer;
      return current();
    }

    function graph() {
      return {
        workflow: review.workflow || {},
        nodes: nodes.map((node) => ({
          node_id: node.node_id,
          label: userFacingLearningLabel(node.display_name || node.node_id),
          surface_type: node.surface_type || "unknown_surface",
          evidence_status: node.evidence_status || "unknown",
          selected: node.node_id === selectedNodeId,
          controls: nodeControls(node).map((control) => ({
            control_id: String(control?.control_id || control?.region_id || "").trim(),
            label: String(control?.label || control?.name || control?.control_id || control?.region_id || "Control"),
            role: String(control?.role || control?.kind || "control"),
          })).filter((control) => control.control_id),
        })),
        edges: edges.map((edge) => ({
          edge_id: edge.edge_id,
          source_node_id: edge.source_node_id,
          target_node_id: edge.target_node_id,
          display_name: edge.display_name || edge.action_type || edge.edge_id,
          action_type: edge.action_type || "unknown_action",
          target_control_id: edge.target_control_id || "",
          target_region_id: edge.target_region_id || "",
          review_status: edge.review_status || "needs_human_review",
        })),
        focus: {
          node_id: focusedNodeId,
          control_id: selectedControlId,
        },
      };
    }

    function applyEditablePatch(target, patch, editableFields) {
      if (!patch || typeof patch !== "object") return;
      Object.entries(patch).forEach(([key, value]) => {
        if (editableFields.has(key)) {
          target[key] = clone(value);
        }
      });
      target.display_only = true;
      target.artifact_is_authorization = false;
      target.execute_binding_enabled = false;
    }

    function updateNode(nodeId, patch) {
      const node = nodeById.get(nodeId);
      if (!node) {
        throw new Error(`unknown interface workflow node: ${nodeId}`);
      }
      applyEditablePatch(node, patch, EDITABLE_NODE_FIELDS);
      return current();
    }

    function updateEdge(edgeId, patch) {
      const edge = edges.find((item) => item.edge_id === edgeId);
      if (!edge) {
        throw new Error(`unknown interface workflow edge: ${edgeId}`);
      }
      const targetNodeId = patch && typeof patch === "object"
        ? String(patch.target_node_id || "").trim()
        : "";
      if (targetNodeId && !nodeById.has(targetNodeId)) {
        throw new Error(`unknown interface workflow target node: ${targetNodeId}`);
      }
      const normalizedPatch = patch && typeof patch === "object" ? { ...patch } : {};
      if (Object.prototype.hasOwnProperty.call(normalizedPatch, "action_type")) {
        normalizedPatch.action_type = normalizedActionType(normalizedPatch.action_type);
      }
      applyEditablePatch(edge, normalizedPatch, EDITABLE_EDGE_FIELDS);
      return current();
    }

    function uniqueId(prefix, preferred, existingIds) {
      const base = `${prefix}_${normalizedIdentifier(preferred, "item")}`;
      if (!existingIds.has(base)) return base;
      let suffix = 2;
      while (existingIds.has(`${base}_${suffix}`)) suffix += 1;
      return `${base}_${suffix}`;
    }

    function addPlaceholderNode(displayName, surfaceType = "unknown_surface") {
      const label = String(displayName || "").trim();
      if (!label) {
        throw new Error("placeholder interface name is required");
      }
      const nodeId = uniqueId(
        "interface",
        label,
        new Set(nodes.map((node) => String(node.node_id || ""))),
      );
      const node = {
        node_id: nodeId,
        display_name: label,
        surface_type: String(surfaceType || "unknown_surface").trim() || "unknown_surface",
        state_signature: `placeholder:${nodeId}`,
        source_paths: [],
        observation_count: 0,
        evidence: {
          source_screenshot_path: "",
          numbered_overlay_path: "",
          fused_overlay_path: "",
          human_review_overlay_path: "",
        },
        evidence_status: "needs_learning",
        page_details: {},
        ui_hierarchy: {},
        states: [],
        regions: [],
        controls: [],
        action_candidates: [],
        blockers: [],
        verification_rules: [],
        review_status: "needs_learning",
        execution_verification_status: "not_verified",
        manual_revision: {},
        display_only: true,
        artifact_is_authorization: false,
        execute_binding_enabled: false,
      };
      nodes.push(node);
      nodeById.set(nodeId, node);
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.node_ids = nodes.map((item) => item.node_id);
      if (!review.workflow.entry_node_id) review.workflow.entry_node_id = nodeId;
      return clone(node);
    }

    function addInterfaceNode(rawNode) {
      const source = rawNode && typeof rawNode === "object" ? clone(rawNode) : {};
      const nodeId = String(source.node_id || "").trim();
      if (!nodeId) throw new Error("interface workflow node_id is required");
      if (nodeById.has(nodeId)) {
        throw new Error(`interface workflow node already exists: ${nodeId}`);
      }
      const node = {
        ...source,
        node_id: nodeId,
        display_name: String(source.display_name || nodeId).trim() || nodeId,
        surface_type: String(source.surface_type || "unknown_surface").trim() || "unknown_surface",
        source_paths: Array.isArray(source.source_paths) ? clone(source.source_paths) : [],
        evidence: source.evidence && typeof source.evidence === "object"
          ? clone(source.evidence)
          : {},
        regions: Array.isArray(source.regions) ? clone(source.regions) : [],
        controls: Array.isArray(source.controls) ? clone(source.controls) : [],
        action_candidates: Array.isArray(source.action_candidates) ? clone(source.action_candidates) : [],
        blockers: Array.isArray(source.blockers) ? clone(source.blockers) : [],
        verification_rules: Array.isArray(source.verification_rules)
          ? clone(source.verification_rules)
          : [],
        review_status: String(source.review_status || "needs_human_review"),
        display_only: true,
        artifact_is_authorization: false,
        execute_binding_enabled: false,
      };
      nodes.push(node);
      nodeById.set(nodeId, node);
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.node_ids = nodes.map((item) => item.node_id);
      if (!review.workflow.entry_node_id) review.workflow.entry_node_id = nodeId;
      return clone(node);
    }

    function addOperation(sourceNodeId, operation) {
      if (!nodeById.has(sourceNodeId)) {
        throw new Error(`unknown interface workflow node: ${sourceNodeId}`);
      }
      const targetNodeId = String(operation?.target_node_id || "").trim();
      if (!nodeById.has(targetNodeId)) {
        throw new Error(`unknown interface workflow target node: ${targetNodeId}`);
      }
      const actionType = normalizedActionType(operation?.action_type);
      const operationId = normalizedIdentifier(
        operation?.operation_id,
        actionType,
      );
      const edgeId = uniqueId(
        "edge",
        operationId,
        new Set(edges.map((edge) => String(edge.edge_id || ""))),
      );
      const riskLevel = String(operation?.risk_level || "low").trim().toLowerCase();
      if (!["low", "medium", "high"].includes(riskLevel)) {
        throw new Error("workflow edge risk_level must be low, medium, or high");
      }
      const edge = {
        edge_id: edgeId,
        operation_id: operationId,
        source_node_id: sourceNodeId,
        target_node_id: targetNodeId,
        display_name: String(operation?.display_name || actionType).trim() || actionType,
        agent_description: String(operation?.agent_description || "").trim(),
        action_type: actionType,
        target_region_id: String(operation?.target_region_id || "").trim(),
        target_control_id: String(operation?.target_control_id || "").trim(),
        risk_level: riskLevel,
        requires_user_confirmation: Boolean(
          operation?.requires_user_confirmation || riskLevel === "high"
        ),
        preconditions: Array.isArray(operation?.preconditions) ? clone(operation.preconditions) : [],
        success_conditions: Array.isArray(operation?.success_conditions) ? clone(operation.success_conditions) : [],
        failure_conditions: Array.isArray(operation?.failure_conditions) ? clone(operation.failure_conditions) : [],
        gate_policy: "fresh_grounding_and_gate_required",
        verification_evidence: {},
        review_status: "needs_human_review",
        display_only: true,
        artifact_is_authorization: false,
        execute_binding_enabled: false,
      };
      edges.push(edge);
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.edge_ids = edges.map((item) => item.edge_id);
      return clone(edge);
    }

    function removeOperation(edgeId) {
      const index = edges.findIndex((item) => item.edge_id === edgeId);
      if (index < 0) {
        throw new Error(`unknown interface workflow edge: ${edgeId}`);
      }
      const [removed] = edges.splice(index, 1);
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.edge_ids = edges.map((item) => item.edge_id);
      return clone(removed);
    }

    function snapshot() {
      const result = clone(review);
      result.display_only = true;
      result.artifact_is_authorization = false;
      result.execute_binding_enabled = false;
      result.nodes = (result.nodes || []).map((node) => ({
        ...node,
        display_only: true,
        artifact_is_authorization: false,
        execute_binding_enabled: false,
      }));
      result.edges = (result.edges || []).map((edge) => ({
        ...edge,
        display_only: true,
        artifact_is_authorization: false,
        execute_binding_enabled: false,
      }));
      return result;
    }

    return {
      addInterfaceNode,
      addOperation,
      addPlaceholderNode,
      clearFocus,
      current,
      focusControl,
      focusInterface,
      graph,
      removeOperation,
      select,
      selectLayer,
      snapshot,
      updateEdge,
      updateNode,
    };
  }

  function mergeEditableWorkflowReview(nextReview, previousReview) {
    const state = createInterfaceWorkflowReviewState(nextReview);
    if (!previousReview || previousReview.contract_version !== CONTRACT_VERSION) {
      return state.snapshot();
    }

    const nextGraph = state.graph();
    const nextNodeIds = new Set(nextGraph.nodes.map((node) => node.node_id));
    const previousNodes = Array.isArray(previousReview.nodes) ? previousReview.nodes : [];
    previousNodes.forEach((node) => {
      const nodeId = String(node?.node_id || "").trim();
      if (nextNodeIds.has(nodeId)) {
        state.updateNode(nodeId, node);
      }
    });

    const nextEdges = nextGraph.edges;
    const previousEdges = Array.isArray(previousReview.edges) ? previousReview.edges : [];
    nextEdges.forEach((nextEdge) => {
      const previousEdge = previousEdges.find((edge) => (
        edge?.edge_id === nextEdge.edge_id
        || (
          edge?.source_node_id === nextEdge.source_node_id
          && edge?.target_node_id === nextEdge.target_node_id
        )
      ));
      if (!previousEdge) return;
      const targetNodeId = String(previousEdge.target_node_id || "").trim();
      if (targetNodeId && !nextNodeIds.has(targetNodeId)) return;
      state.updateEdge(nextEdge.edge_id, previousEdge);
    });
    previousEdges.forEach((previousEdge) => {
      const sourceNodeId = String(previousEdge?.source_node_id || "").trim();
      const targetNodeId = String(previousEdge?.target_node_id || "").trim();
      if (!nextNodeIds.has(sourceNodeId) || !nextNodeIds.has(targetNodeId)) return;
      const alreadyPresent = state.graph().edges.some((edge) => (
        edge.source_node_id === sourceNodeId
        && edge.target_node_id === targetNodeId
        && (
          edge.edge_id === previousEdge.edge_id
          || edge.display_name === previousEdge.display_name
        )
      ));
      if (alreadyPresent) return;
      const added = state.addOperation(sourceNodeId, previousEdge);
      state.updateEdge(added.edge_id, previousEdge);
    });
    const merged = state.snapshot();
    const previousWorkflow = previousReview.workflow && typeof previousReview.workflow === "object"
      ? previousReview.workflow
      : {};
    if (merged.workflow && typeof merged.workflow === "object") {
      for (const key of ["workflow_id", "goal", "application_identity", "review_status"]) {
        if (previousWorkflow[key] !== undefined && previousWorkflow[key] !== null) {
          merged.workflow[key] = clone(previousWorkflow[key]);
        }
      }
      merged.workflow.published_memory_version = null;
    }
    return merged;
  }

  const api = {
    CONTRACT_VERSION,
    createEmptyInterfaceWorkflowReview,
    createLatestInterfaceWorkflowLoadGuard,
    createInterfaceWorkflowWorkbenchState,
    createInterfaceWorkflowReviewState,
    interfaceWorkflowControlChoices,
    mergeEditableWorkflowReview,
    userFacingLearningLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  globalScope.InterfaceWorkflowReview = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
