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
  const GRANULAR_CONFIRMATION_CONTRACTS = {
    action_candidate: "interface_action_candidate_human_review_confirmation_v1",
    edge: "interface_workflow_edge_human_review_confirmation_v1",
    target_control: "interface_target_control_human_review_confirmation_v1",
  };

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

  function resolveInterfaceAssetOpenTarget({ sourcePath, workflowId, nodeId } = {}) {
    const source = String(sourcePath || "").trim();
    const workflow = String(workflowId || "").trim();
    const node = String(nodeId || "").trim();
    if (workflow && node) {
      return {
        mode: "saved_workflow",
        workflow_id: workflow,
        node_id: node,
        source_path: source,
      };
    }
    if (source) {
      return {
        mode: "source_preview",
        workflow_id: "",
        node_id: "",
        source_path: source,
      };
    }
    return {
      mode: "unavailable",
      workflow_id: workflow,
      node_id: node,
      source_path: source,
    };
  }
  const EDITABLE_NODE_FIELDS = new Set([
    "display_name",
    "surface_type",
    "review_status",
    "evidence",
    "regions",
    "controls",
    "action_candidates",
    "blockers",
    "content_descriptors",
    "verification_rules",
    "manual_revision",
    "editable_review_source_path",
    "source_paths",
    "page_details",
  ]);
  const EDITABLE_EDGE_FIELDS = new Set([
    "display_name",
    "agent_description",
    "operation_id",
    "action_template_id",
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
  const REVISION_METADATA_FIELDS = new Set([
    "agent_eligibility_reason",
    "agent_usable",
    "artifact_is_authorization",
    "current_revision_hash",
    "display_only",
    "editable_review_source_path",
    "execute_binding_enabled",
    "execution_verification_status",
    "human_review_confirmation",
    "review_bucket",
    "review_status",
    "reviewed_by_human",
    "reviewed_revision_hash",
    "source_paths",
    "source_screenshot_sha256",
    "review_revision_source_screenshot_path",
    "review_revision_numbered_overlay_path",
    "review_revision_fused_overlay_path",
    "review_revision_human_review_overlay_path",
  ]);
  const RUNTIME_POINT_FIELDS = new Set([
    "actual_point",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "screen_point",
    "target_point",
  ]);

  function clone(value) {
    if (typeof structuredClone === "function") {
      return structuredClone(value);
    }
    return JSON.parse(JSON.stringify(value));
  }

  function projectLearningDraftOwnershipConflicts(draft = {}) {
    const pageDetails = draft?.page_details && typeof draft.page_details === "object"
      ? draft.page_details
      : {};
    const twoStage = pageDetails.two_stage_understanding
      && typeof pageDetails.two_stage_understanding === "object"
      ? pageDetails.two_stage_understanding
      : {};
    const stage2 = twoStage.stage2_numbering && typeof twoStage.stage2_numbering === "object"
      ? twoStage.stage2_numbering
      : {};
    const conflicts = [];
    (Array.isArray(stage2.regions) ? stage2.regions : []).forEach((region) => {
      if (!region || typeof region !== "object") return;
      const regionId = String(region.region_id || "").trim();
      if (!regionId) return;
      const groups = (Array.isArray(region.subregion_groups) ? region.subregion_groups : [])
        .filter((group) => group && typeof group === "object" && String(group.group_id || "").trim());
      const parentGroupIds = new Set(groups.map((group) => String(
        group.parent_group_id || group.resolved_parent_group_id || "",
      ).trim()).filter(Boolean));
      const leafGroups = groups.filter((group) => !parentGroupIds.has(String(group.group_id).trim()));
      const items = new Map((Array.isArray(region.numbered_items) ? region.numbered_items : [])
        .filter((item) => item && typeof item === "object" && String(item.item_id || "").trim())
        .map((item) => [String(item.item_id).trim(), item]));
      items.forEach((item, itemId) => {
        const owners = leafGroups.filter((group) => (
          Array.isArray(group.member_item_ids)
          && group.member_item_ids.some((memberId) => String(memberId || "").trim() === itemId)
        ));
        if (owners.length < 2) return;
        const parentGroups = owners.map((group) => ({
          group_id: String(group.group_id).trim(),
          label: String(group.label || group.display_name || group.group_id).trim(),
        })).sort((left, right) => left.group_id.localeCompare(right.group_id));
        conflicts.push({
          conflict_id: `${regionId}:${itemId}`,
          region_id: regionId,
          target_id: itemId,
          item_number: String(item.number || "").trim(),
          item_label: String(item.label || item.display_name || item.text || itemId).trim(),
          before_parent_group_ids: parentGroups.map((group) => group.group_id),
          parent_groups: parentGroups,
        });
      });
    });
    return conflicts.sort((left, right) => left.conflict_id.localeCompare(right.conflict_id));
  }

  function buildLearningDraftOwnershipOperations({ conflicts = [], selections = {}, reason = "" } = {}) {
    return (Array.isArray(conflicts) ? conflicts : []).map((conflict) => {
      const conflictId = String(conflict?.conflict_id || "").trim();
      const selectedParentId = String(selections?.[conflictId] || "").trim();
      if (!selectedParentId) {
        throw new Error(`ownership conflict explicit parent selection is required: ${conflictId}`);
      }
      const beforeParentIds = Array.isArray(conflict?.before_parent_group_ids)
        ? conflict.before_parent_group_ids.map((value) => String(value || "").trim()).filter(Boolean)
        : [];
      if (!beforeParentIds.includes(selectedParentId)) {
        throw new Error(`ownership conflict selected parent is not a current leaf owner: ${conflictId}`);
      }
      return {
        op: "resolve_ownership",
        target_kind: "ownership",
        target_id: String(conflict.target_id || "").trim(),
        region_id: String(conflict.region_id || "").trim(),
        before_parent_group_ids: beforeParentIds,
        after_parent_group_id: selectedParentId,
        reason: String(reason || "").trim(),
      };
    });
  }

  function withoutRuntimePoints(value) {
    if (Array.isArray(value)) return value.map(withoutRuntimePoints);
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !RUNTIME_POINT_FIELDS.has(String(key)))
      .map(([key, item]) => [key, withoutRuntimePoints(item)]));
  }

  function withoutReviewRevisionMetadata(value) {
    if (Array.isArray(value)) return value.map(withoutReviewRevisionMetadata);
    if (!value || typeof value !== "object") return clone(value);
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !REVISION_METADATA_FIELDS.has(String(key)))
      .map(([key, item]) => [key, withoutReviewRevisionMetadata(item)]));
  }

  function granularReviewRevision(value) {
    return withoutRuntimePoints(withoutReviewRevisionMetadata(value));
  }

  function canonicalReviewValue(value) {
    if (Array.isArray(value)) return value.map(canonicalReviewValue);
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(Object.keys(value).sort().map(
      (key) => [key, canonicalReviewValue(value[key])],
    ));
  }

  function granularHumanReviewIsCurrent(value, subjectKind) {
    const confirmation = value?.human_review_confirmation;
    return value?.review_status === "human_approved"
      && value?.reviewed_by_human === true
      && value?.display_only === true
      && value?.artifact_is_authorization === false
      && value?.execute_binding_enabled === false
      && confirmation?.contract_version === GRANULAR_CONFIRMATION_CONTRACTS[subjectKind]
      && JSON.stringify(canonicalReviewValue(confirmation?.revision))
        === JSON.stringify(canonicalReviewValue(granularReviewRevision(value)));
  }

  function buildInterfaceNodeReviewRevision(review, nodeId) {
    const normalizedNodeId = String(nodeId || "").trim();
    const nodes = Array.isArray(review?.nodes) ? review.nodes : [];
    const edges = Array.isArray(review?.edges) ? review.edges : [];
    const matches = nodes.filter((node) => String(node?.node_id || "").trim() === normalizedNodeId);
    if (matches.length !== 1) {
      throw new Error(`workflow review node must exist exactly once: ${normalizedNodeId}`);
    }
    const node = withoutReviewRevisionMetadata(matches[0]);
    const sourcePaths = matches[0]?.source_paths;
    if (Array.isArray(sourcePaths)) {
      const normalizedSourcePaths = sourcePaths
        .map((value) => String(value || "").trim())
        .filter((value) => value && !value.replace(/\\/g, "/").includes("node-review-sources"));
      if (normalizedSourcePaths.length) node.source_paths = normalizedSourcePaths;
    }
    const rawEvidence = matches[0]?.evidence;
    if (rawEvidence && typeof rawEvidence === "object" && node.evidence && typeof node.evidence === "object") {
      [
        "source_screenshot_path",
        "numbered_overlay_path",
        "fused_overlay_path",
        "human_review_overlay_path",
      ].forEach((evidenceKey) => {
        const currentPath = String(rawEvidence[evidenceKey] || "").trim();
        const originalPath = String(rawEvidence[`review_revision_${evidenceKey}`] || "").trim();
        if (originalPath && currentPath.replace(/\\/g, "/").includes("node-evidence")) {
          node.evidence[evidenceKey] = originalPath;
        }
      });
    }
    const outgoingEdges = edges
      .filter((edge) => String(edge?.source_node_id || "").trim() === normalizedNodeId)
      .map(withoutReviewRevisionMetadata)
      .sort((left, right) => String(left?.edge_id || "").localeCompare(String(right?.edge_id || "")));
    return withoutRuntimePoints({ node, outgoing_edges: outgoingEdges });
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

  function resolveDraftItemWorkflowBinding(node = {}, draftItem = {}, outgoingEdges = []) {
    const empty = (status, reason) => ({
      status,
      reason,
      control_id: "",
      control_label: "",
      action_template_id: "",
      edge_id: "",
      target_node_id: "",
    });
    const controls = Array.isArray(node?.controls) && node.controls.length
      ? node.controls
      : Array.isArray(node?.regions)
        ? node.regions
        : [];
    const controlId = (control) => String(control?.control_id || control?.region_id || "").trim();
    const draftId = String(
      draftItem?.target_id
      || draftItem?.region_id
      || draftItem?.action_template_id
      || "",
    ).trim();
    const explicitControlId = String(
      draftItem?.target_control_id
      || draftItem?.source_control_id
      || "",
    ).trim();
    const semanticAction = String(
      draftItem?.semantic_action
      || draftItem?.action_type
      || "",
    ).trim();

    let controlMatches = [];
    if (explicitControlId) {
      controlMatches = controls.filter((control) => controlId(control) === explicitControlId);
    } else if (draftId) {
      controlMatches = controls.filter((control) => (
        String(control?.evidence_region_id || "").trim() === draftId
        || controlId(control) === draftId
      ));
    }
    if (controlMatches.length > 1) {
      return empty("ambiguous", "workflow_control_mapping_ambiguous");
    }

    const actionCandidates = Array.isArray(node?.action_candidates) ? node.action_candidates : [];
    const explicitActionId = String(
      draftItem?.action_template_id
      || (draftItem?.target_kind === "action" ? draftId : "")
      || "",
    ).trim();
    let candidateMatches = actionCandidates.filter((candidate) => {
      const candidateId = String(candidate?.action_template_id || "").trim();
      const candidateAction = String(candidate?.semantic_action || candidate?.action_type || "").trim();
      if (explicitActionId && candidateId !== explicitActionId) return false;
      if (!explicitActionId && semanticAction && candidateAction !== semanticAction) return false;
      if (!explicitActionId && !semanticAction) return false;
      if (controlMatches.length === 1) {
        const targetId = String(
          candidate?.target_control_id
          || candidate?.target_region_id
          || candidate?.source_control_id
          || "",
        ).trim();
        return targetId === controlId(controlMatches[0]);
      }
      return true;
    });
    if (candidateMatches.length > 1) {
      return empty("ambiguous", "workflow_control_mapping_ambiguous");
    }
    const actionCandidate = candidateMatches[0] || null;

    if (!controlMatches.length && actionCandidate) {
      const candidateControlId = String(
        actionCandidate?.target_control_id
        || actionCandidate?.target_region_id
        || actionCandidate?.source_control_id
        || "",
      ).trim();
      controlMatches = controls.filter((control) => controlId(control) === candidateControlId);
    }
    if (controlMatches.length > 1) {
      return empty("ambiguous", "workflow_control_mapping_ambiguous");
    }
    if (controlMatches.length !== 1) {
      return empty("unmatched", "workflow_control_mapping_unavailable");
    }

    const control = controlMatches[0];
    const normalizedControlId = controlId(control);
    const actionTemplateId = String(actionCandidate?.action_template_id || explicitActionId || "").trim();
    const edges = (Array.isArray(outgoingEdges) ? outgoingEdges : []).filter((edge) => {
      const edgeControlId = String(edge?.target_control_id || edge?.target_region_id || "").trim();
      const edgeActionId = String(edge?.action_template_id || "").trim();
      const edgeAction = String(edge?.semantic_action || edge?.action_type || "").trim();
      return edgeControlId === normalizedControlId
        && (!actionTemplateId || edgeActionId === actionTemplateId)
        && (!semanticAction || edgeAction === semanticAction);
    });
    if (edges.length > 1) {
      return empty("ambiguous", "workflow_operation_mapping_ambiguous");
    }
    const actionable = Boolean(semanticAction && !["read", "read_only"].includes(semanticAction));
    if (actionable && edges.length !== 1) {
      return empty("unmatched", "workflow_operation_mapping_unavailable");
    }
    const edge = edges[0] || null;
    return {
      status: "matched",
      reason: "",
      control_id: normalizedControlId,
      control_label: String(
        control?.label
        || control?.name
        || control?.semantic_name
        || normalizedControlId,
      ).trim(),
      action_template_id: String(actionCandidate?.action_template_id || edge?.action_template_id || "").trim(),
      edge_id: String(edge?.edge_id || "").trim(),
      target_node_id: String(edge?.target_node_id || actionCandidate?.target_interface_id || "").trim(),
    };
  }

  function projectInterfaceWorkflowStepAudit(runtimeReport = {}, interfaceId = "") {
    const report = runtimeReport && typeof runtimeReport === "object" ? runtimeReport : {};
    const steps = Array.isArray(report.steps) ? report.steps : [];
    const normalizedInterfaceId = String(interfaceId || "").trim();
    let selectedIndex = -1;
    for (let index = steps.length - 1; index >= 0; index -= 1) {
      const stepInterfaceId = String(
        steps[index]?.interface_id
        || steps[index]?.source_interface_id
        || "",
      ).trim();
      if (!normalizedInterfaceId || stepInterfaceId === normalizedInterfaceId) {
        selectedIndex = index;
        break;
      }
    }
    if (selectedIndex < 0) {
      return {
        contract_version: "interface_workflow_step_audit_v1",
        coverage_status: "not_run",
        interpretation: "No recorded runtime step exists for this interface.",
        agent: { status: "not_recorded", semantic_action: "", reason: "" },
        gate: { status: "not_covered", allowed: null, reason: "" },
        dispatch: { status: "not_covered", attempted: false },
        effect: { status: "not_covered", verified: null },
        post_observe: { status: "not_covered", verified: null, interface_id: "" },
        trace: { status: "not_recorded", path: "" },
        stop: { status: "not_run", reason: "" },
      };
    }

    const step = steps[selectedIndex] || {};
    const decision = step.agent_decision && typeof step.agent_decision === "object"
      ? step.agent_decision
      : step.decision_plan && typeof step.decision_plan === "object"
        ? step.decision_plan
        : {};
    const decisionAudit = step.decision_audit && typeof step.decision_audit === "object"
      ? step.decision_audit
      : {};
    const semanticAction = String(
      decision.semantic_action || step.semantic_action || "",
    ).trim();
    const choiceId = String(decision.choice_id || step.choice_id || "").trim();
    const hasAgentDecision = Object.keys(decision).length > 0
      || Boolean(semanticAction || choiceId || String(step.decision_type || "").trim());
    const gateResult = step.gate_result && typeof step.gate_result === "object"
      ? step.gate_result
      : {};
    const gateAllowed = typeof step.gate_allowed === "boolean"
      ? step.gate_allowed
      : typeof gateResult.allowed === "boolean"
        ? gateResult.allowed
        : null;
    const dispatchValue = typeof step.dispatch_success === "boolean"
      ? step.dispatch_success
      : typeof step.action_dispatched === "boolean"
        ? step.action_dispatched
        : typeof step.action_executed === "boolean"
          ? step.action_executed
          : null;
    const effectValue = typeof step.effect_verified === "boolean"
      ? step.effect_verified
      : typeof step.post_action_verified === "boolean"
        ? step.post_action_verified
        : null;
    const postObserveValue = typeof step.destination_observation_verified === "boolean"
      ? step.destination_observation_verified
      : null;
    const tracePath = String(
      step.trace_path
      || step.execute_step_trace_path
      || step.available_actions_trace_path
      || report.trace_path
      || report.source_report_path
      || "",
    ).trim();
    const reportStoppedHere = selectedIndex === steps.length - 1
      && ["safe_stop", "safe_stopped", "needs_human_review", "failed"].includes(
        String(report.final_status || "").trim(),
      );

    return {
      contract_version: "interface_workflow_step_audit_v1",
      coverage_status: "recorded_runtime_step",
      interpretation: "Recorded runtime evidence for this interface only; learning assets do not authorize execution.",
      agent: {
        status: hasAgentDecision ? "decision_recorded" : "not_recorded",
        semantic_action: semanticAction,
        choice_id: choiceId,
        reason: String(
          decision.reason
          || decision.rationale
          || decisionAudit.reason
          || decisionAudit.rationale
          || "",
        ).trim(),
        source: String(step.decision_source || "").trim(),
      },
      gate: {
        status: gateAllowed === true ? "allowed" : gateAllowed === false ? "rejected" : "not_covered",
        allowed: gateAllowed,
        reason: String(gateResult.reason || step.gate_reason || "").trim(),
      },
      dispatch: {
        status: dispatchValue === true
          ? "dispatched"
          : dispatchValue === false || gateAllowed === false
            ? "not_dispatched"
            : "not_covered",
        attempted: dispatchValue !== null || gateAllowed === false,
      },
      effect: {
        status: dispatchValue === false || gateAllowed === false
          ? "not_attempted"
          : effectValue === true
            ? "verified"
            : effectValue === false
              ? "not_verified"
              : "not_covered",
        verified: effectValue,
      },
      post_observe: {
        status: postObserveValue === true
          ? "verified"
          : postObserveValue === false
            ? "not_verified"
            : "not_covered",
        verified: postObserveValue,
        interface_id: String(step.actual_target_interface_id || "").trim(),
      },
      trace: {
        status: tracePath ? "recorded" : "not_recorded",
        path: tracePath,
      },
      stop: {
        status: reportStoppedHere
          ? String(report.final_status || "safe_stop").trim()
          : "continuing",
        reason: reportStoppedHere ? String(report.stop_reason || step.stop_reason || "").trim() : "",
      },
      case_outcome: String(step.case_outcome || "").trim(),
    };
  }

  function projectLiveSafeFillPreflightReview(preflight = {}) {
    const source = preflight && typeof preflight === "object" ? preflight : {};
    if (source.contract_version !== "seek_live_safe_fill_preflight_v1") {
      return { visible: false, reason: "unsupported_contract" };
    }
    const field = source.field && typeof source.field === "object" ? source.field : {};
    const valueEvidence = source.value_evidence && typeof source.value_evidence === "object"
      ? source.value_evidence
      : {};
    const safety = source.safety && typeof source.safety === "object" ? source.safety : {};
    const redactionPassed = source.pii_redacted === true
      && valueEvidence.value_redacted === true
      && nonEmptyString(valueEvidence.value_hash)
      && Number(valueEvidence.value_length || 0) > 0;
    if (!redactionPassed) {
      return { visible: false, reason: "redaction_contract_failed" };
    }
    const target = source.target && typeof source.target === "object" ? source.target : {};
    const verification = source.expected_verification && typeof source.expected_verification === "object"
      ? source.expected_verification
      : {};
    const evidence = source.evidence && typeof source.evidence === "object" ? source.evidence : {};
    return {
      visible: true,
      contract_version: source.contract_version,
      status: String(source.status || "").trim(),
      approval_state: String(source.approval_state || "").trim(),
      interpretation: String(
        source.interpretation
        || "single-field review evidence only; not authorization and not live safe-fill evidence",
      ).trim(),
      field: {
        id: String(field.id || "").trim(),
        label: String(field.label || field.id || "").trim(),
        field_type: String(field.field_type || "").trim(),
        risk_class: String(field.risk_class || "").trim(),
        required: field.required === true,
      },
      value_evidence: {
        answer_source: String(valueEvidence.answer_source || "").trim(),
        value_length: Number(valueEvidence.value_length || 0),
        value_hash: String(valueEvidence.value_hash || "").trim(),
        value_redacted: true,
      },
      target: {
        state_type: String(target.state_type || "").trim(),
        current_step: String(target.current_step || "").trim(),
      },
      expected_verification: {
        mode: String(verification.mode || "").trim(),
        expected_value_hash: String(verification.expected_value_hash || "").trim(),
        expected_value_length: Number(verification.expected_value_length || 0),
        raw_value_must_not_be_recorded: verification.raw_value_must_not_be_recorded === true,
      },
      safety: {
        max_fields: Number(safety.max_fields || 0),
        cover_letter_fill_allowed: safety.cover_letter_fill_allowed === true,
        continue_allowed: safety.continue_allowed === true,
        final_submit_allowed: safety.final_submit_allowed === true,
        artifact_is_authorization: false,
      },
      evidence: {
        screenshot_path: String(evidence.screenshot_path || "").trim(),
        trace_path: String(evidence.trace_path || "").trim(),
        source_report_path: String(evidence.source_report_path || "").trim(),
      },
      source_path: String(source.source_path || "").trim(),
      artifact_is_authorization: false,
    };
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

  function resolveInterfaceWorkflowCorrectionTarget({
    workbench = {},
    workflowState = null,
    sourcePreviewState = null,
  } = {}) {
    const sourcePreviewActive = String(workbench?.evidence_mode || "workflow") === "source_preview";
    const authority = sourcePreviewActive ? "source_preview" : "workflow";
    const authoritativeState = sourcePreviewActive ? sourcePreviewState : workflowState;
    const view = authoritativeState?.current?.() || null;
    if (!view?.node) {
      return {
        authority,
        view: null,
        reason: sourcePreviewActive
          ? "displayed_source_preview_unavailable"
          : "displayed_workflow_node_unavailable",
      };
    }
    const displayedNodeId = String(workbench?.evidence_node_id || "").trim();
    const currentNodeId = String(view.node.node_id || "").trim();
    if (displayedNodeId && displayedNodeId !== currentNodeId) {
      return {
        authority,
        view: null,
        reason: "displayed_evidence_selection_mismatch",
      };
    }
    return { authority, view, reason: "" };
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
    const stopBoundaryNodeIds = new Set(nodes.filter(
      (node) => String(node?.review_status || "").trim() === "needs_learning",
    ).map((node) => String(node.node_id || "").trim()));
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
        step_audit: projectInterfaceWorkflowStepAudit(review.runtime_report, node.node_id),
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
          review_status: node.review_status || "needs_human_review",
          reviewed_by_human: node.reviewed_by_human === true,
          agent_usable: node.agent_usable === true,
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
          action_template_id: edge.action_template_id || "",
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

    function revokeNodeHumanReview(node) {
      node.review_status = "needs_human_review";
      node.reviewed_by_human = false;
      delete node.human_review_confirmation;
      delete node.reviewed_revision_hash;
      delete node.current_revision_hash;
    }

    function revokeGranularHumanReview(subject) {
      subject.review_status = "needs_human_review";
      subject.reviewed_by_human = false;
      delete subject.human_review_confirmation;
      subject.display_only = true;
      subject.artifact_is_authorization = false;
      subject.execute_binding_enabled = false;
    }

    function confirmGranularHumanReview(subject, subjectKind) {
      subject.review_status = "human_approved";
      subject.reviewed_by_human = true;
      subject.display_only = true;
      subject.artifact_is_authorization = false;
      subject.execute_binding_enabled = false;
      subject.human_review_confirmation = {
        contract_version: GRANULAR_CONFIRMATION_CONTRACTS[subjectKind],
        revision: granularReviewRevision(subject),
      };
    }

    function resolveOperationSubjects(edgeId) {
      const normalizedEdgeId = String(edgeId || "").trim();
      const edgeMatches = edges.filter((item) => String(item?.edge_id || "").trim() === normalizedEdgeId);
      if (edgeMatches.length !== 1) {
        throw new Error(`workflow operation edge must exist exactly once: ${normalizedEdgeId}`);
      }
      const edge = edgeMatches[0];
      const sourceNodeId = String(edge.source_node_id || "").trim();
      const sourceNode = nodeById.get(sourceNodeId);
      if (!sourceNode) throw new Error(`workflow operation source node is invalid: ${sourceNodeId}`);

      const targetControlId = String(edge.target_control_id || "").trim();
      const targetRegionId = String(edge.target_region_id || "").trim();
      if (Boolean(targetControlId) === Boolean(targetRegionId)) {
        throw new Error(`workflow operation must reference exactly one target control or region: ${normalizedEdgeId}`);
      }
      const targetCollection = targetControlId ? sourceNode.controls : sourceNode.regions;
      const targetIdKey = targetControlId ? "control_id" : "region_id";
      const targetId = targetControlId || targetRegionId;
      const targetMatches = (Array.isArray(targetCollection) ? targetCollection : []).filter(
        (item) => String(item?.[targetIdKey] || "").trim() === targetId,
      );
      if (targetMatches.length !== 1) {
        throw new Error(`workflow operation must match exactly one target control or region: ${normalizedEdgeId}`);
      }

      const actionTemplateId = String(edge.action_template_id || "").trim();
      const actionMatches = (Array.isArray(sourceNode.action_candidates)
        ? sourceNode.action_candidates
        : []).filter((item) => (
        String(item?.action_template_id || "").trim() === actionTemplateId
      ));
      if (!actionTemplateId || actionMatches.length !== 1) {
        throw new Error(`workflow operation must match exactly one action candidate: ${normalizedEdgeId}`);
      }
      const actionCandidate = actionMatches[0];
      const edgeAction = String(edge.action_type || "").trim();
      const edgeSemanticAction = String(edge.semantic_action || "").trim();
      const candidateSemanticAction = String(actionCandidate.semantic_action || "").trim();
      const candidateActionType = String(actionCandidate.action_type || "").trim();
      const candidateAction = candidateSemanticAction || candidateActionType;
      const candidateTargetControlId = String(actionCandidate.target_control_id || "").trim();
      const candidateTargetRegionId = String(actionCandidate.target_region_id || "").trim();
      const candidateTargetNodeIds = [
        actionCandidate.target_interface_id,
        actionCandidate.target_node_id,
      ].map((value) => String(value || "").trim()).filter(Boolean);
      if (
        (edgeSemanticAction && edgeSemanticAction !== edgeAction)
        || (candidateSemanticAction && candidateActionType && candidateSemanticAction !== candidateActionType)
        || candidateAction !== edgeAction
        || candidateTargetControlId !== targetControlId
        || candidateTargetRegionId !== targetRegionId
        || (
          String(actionCandidate.source_control_id || "").trim()
          && String(actionCandidate.source_control_id || "").trim() !== targetId
        )
        || candidateTargetNodeIds.length < 1
        || candidateTargetNodeIds.some((value) => value !== String(edge.target_node_id || "").trim())
      ) {
        throw new Error(`workflow action candidate does not match edge type, control, or target: ${normalizedEdgeId}`);
      }
      return { edge, sourceNode, targetControl: targetMatches[0], actionCandidate };
    }

    function operationGranularReview(edgeId) {
      try {
        const subjects = resolveOperationSubjects(edgeId);
        return {
          edge_id: String(subjects.edge.edge_id || ""),
          target_control: {
            current: granularHumanReviewIsCurrent(subjects.targetControl, "target_control"),
            review_status: String(subjects.targetControl.review_status || "needs_human_review"),
          },
          action_candidate: {
            current: granularHumanReviewIsCurrent(subjects.actionCandidate, "action_candidate"),
            review_status: String(subjects.actionCandidate.review_status || "needs_human_review"),
          },
          edge: {
            current: granularHumanReviewIsCurrent(subjects.edge, "edge"),
            review_status: String(subjects.edge.review_status || "needs_human_review"),
          },
          error: "",
        };
      } catch (error) {
        return {
          edge_id: String(edgeId || "").trim(),
          target_control: { current: false, review_status: "invalid" },
          action_candidate: { current: false, review_status: "invalid" },
          edge: { current: false, review_status: "invalid" },
          error: String(error?.message || error || "invalid granular operation review"),
        };
      }
    }

    function confirmOperationTargetControlHumanReview(edgeId) {
      const subjects = resolveOperationSubjects(edgeId);
      confirmGranularHumanReview(subjects.targetControl, "target_control");
      revokeNodeHumanReview(subjects.sourceNode);
      return operationGranularReview(edgeId);
    }

    function confirmOperationActionCandidateHumanReview(edgeId) {
      const subjects = resolveOperationSubjects(edgeId);
      confirmGranularHumanReview(subjects.actionCandidate, "action_candidate");
      revokeNodeHumanReview(subjects.sourceNode);
      return operationGranularReview(edgeId);
    }

    function confirmOperationEdgeHumanReview(edgeId) {
      const subjects = resolveOperationSubjects(edgeId);
      confirmGranularHumanReview(subjects.edge, "edge");
      revokeNodeHumanReview(subjects.sourceNode);
      return operationGranularReview(edgeId);
    }

    function confirmOperationHumanReviewBundle(edgeId) {
      // 一次用户确认对应一条完整操作路径；底层仍保留三个可独立失效的审核事实。
      const subjects = resolveOperationSubjects(edgeId);
      confirmGranularHumanReview(subjects.targetControl, "target_control");
      confirmGranularHumanReview(subjects.actionCandidate, "action_candidate");
      confirmGranularHumanReview(subjects.edge, "edge");
      revokeNodeHumanReview(subjects.sourceNode);
      return operationGranularReview(edgeId);
    }

    function revokeOperationEdgeHumanReview(edgeId) {
      const normalizedEdgeId = String(edgeId || "").trim();
      const matches = edges.filter((edge) => String(edge?.edge_id || "").trim() === normalizedEdgeId);
      if (matches.length !== 1) {
        throw new Error(`workflow operation edge must exist exactly once: ${normalizedEdgeId}`);
      }
      const edge = matches[0];
      revokeGranularHumanReview(edge);
      const sourceNode = nodeById.get(String(edge.source_node_id || "").trim());
      if (sourceNode) revokeNodeHumanReview(sourceNode);
      return operationGranularReview(normalizedEdgeId);
    }

    function confirmNodeHumanReview(nodeId) {
      const node = nodeById.get(nodeId);
      if (!node) {
        throw new Error(`unknown interface workflow node: ${nodeId}`);
      }
      if (stopBoundaryNodeIds.has(String(nodeId || "").trim())) {
        throw new Error(`needs_learning stop-boundary node cannot be human approved: ${nodeId}`);
      }
      const outgoing = edges.filter((edge) => String(edge?.source_node_id || "").trim() === nodeId);
      const invalid = outgoing.find((edge) => {
        const status = operationGranularReview(edge.edge_id);
        return !status.target_control.current || !status.action_candidate.current || !status.edge.current;
      });
      if (invalid) {
        throw new Error(`current granular human approval is required for outgoing edge: ${invalid.edge_id}`);
      }
      node.review_status = "human_approved";
      node.reviewed_by_human = true;
      node.human_review_confirmation = {
        contract_version: "interface_node_human_review_confirmation_v1",
        revision: buildInterfaceNodeReviewRevision({ nodes, edges }, nodeId),
      };
      node.display_only = true;
      node.artifact_is_authorization = false;
      node.execute_binding_enabled = false;
      return current();
    }

    function confirmNodeAndOutgoingHumanReview(nodeId) {
      const node = nodeById.get(nodeId);
      if (!node) {
        throw new Error(`unknown interface workflow node: ${nodeId}`);
      }
      if (stopBoundaryNodeIds.has(String(nodeId || "").trim())) {
        throw new Error(`needs_learning stop-boundary node cannot be human approved: ${nodeId}`);
      }
      const outgoing = edges.filter((edge) => String(edge?.source_node_id || "").trim() === nodeId);
      // 先验证全部路径，再写入任何审核事实，避免一次确认留下部分批准。
      outgoing.forEach((edge) => resolveOperationSubjects(edge.edge_id));
      outgoing.forEach((edge) => confirmOperationHumanReviewBundle(edge.edge_id));
      return confirmNodeHumanReview(nodeId);
    }

    function updateNode(nodeId, patch) {
      const node = nodeById.get(nodeId);
      if (!node) {
        throw new Error(`unknown interface workflow node: ${nodeId}`);
      }
      const normalizedPatch = patch && typeof patch === "object" ? { ...patch } : {};
      if (String(normalizedPatch.review_status || "").trim() === "needs_learning") {
        stopBoundaryNodeIds.add(String(nodeId || "").trim());
      }
      if (stopBoundaryNodeIds.has(String(nodeId || "").trim())) {
        normalizedPatch.review_status = "needs_learning";
      }
      const changedEvidenceFields = Object.entries(normalizedPatch).some(([key, value]) => (
        key !== "review_status"
        && EDITABLE_NODE_FIELDS.has(key)
        && JSON.stringify(node[key]) !== JSON.stringify(value)
      ));
      applyEditablePatch(node, normalizedPatch, EDITABLE_NODE_FIELDS);
      for (const [items, subjectKind] of [
        [node.controls, "target_control"],
        [node.regions, "target_control"],
        [node.action_candidates, "action_candidate"],
      ]) {
        (Array.isArray(items) ? items : []).forEach((item) => {
          if (
            (item?.review_status === "human_approved" || item?.reviewed_by_human === true || item?.human_review_confirmation)
            && !granularHumanReviewIsCurrent(item, subjectKind)
          ) revokeGranularHumanReview(item);
        });
      }
      if (changedEvidenceFields) {
        revokeNodeHumanReview(node);
      } else if (
        Object.prototype.hasOwnProperty.call(normalizedPatch, "review_status")
        && String(normalizedPatch.review_status || "") !== "human_approved"
      ) {
        node.reviewed_by_human = false;
      }
      if (stopBoundaryNodeIds.has(String(nodeId || "").trim())) {
        node.review_status = "needs_learning";
        node.reviewed_by_human = false;
        delete node.human_review_confirmation;
        delete node.reviewed_revision_hash;
        delete node.current_revision_hash;
      }
      return current();
    }

    function replaceReviewedNodeEvidenceBySource(previousSourcePath, reviewedSourcePath, patch) {
      const normalizedPrevious = String(previousSourcePath || "")
        .trim()
        .replace(/\\/g, "/")
        .toLowerCase();
      const normalizedReviewed = String(reviewedSourcePath || "").trim();
      if (!normalizedPrevious || !normalizedReviewed) {
        throw new Error("reviewed workflow evidence source paths are required");
      }
      const matches = nodes.filter((node) => [
        node?.editable_review_source_path,
        ...(Array.isArray(node?.source_paths) ? node.source_paths : []),
      ].some((value) => (
        String(value || "").trim().replace(/\\/g, "/").toLowerCase() === normalizedPrevious
      )));
      if (matches.length !== 1) {
        throw new Error(`reviewed workflow evidence source must match exactly one node: ${matches.length}`);
      }

      const node = matches[0];
      const normalizedPatch = patch && typeof patch === "object" ? { ...patch } : {};
      const reviewedRegions = Array.isArray(normalizedPatch.regions) ? normalizedPatch.regions : [];
      const reviewedActions = clone(Array.isArray(normalizedPatch.action_candidates)
        ? normalizedPatch.action_candidates
        : (Array.isArray(node.action_candidates) ? node.action_candidates : []));
      const existingControls = Array.isArray(node.controls) ? clone(node.controls) : [];
      let reviewedActionsChanged = false;
      for (const action of reviewedActions) {
        const controlId = String(action?.target_control_id || action?.source_control_id || "").trim();
        const targetRegionId = String(action?.target_region_id || "").trim();
        if (!controlId || !targetRegionId) continue;
        if (targetRegionId !== controlId) {
          throw new Error(`reviewed action candidate has conflicting target control and region: ${String(action?.semantic_action || action?.action_type || "").trim()}`);
        }
        const controlMatches = existingControls.filter((control) => (
          String(control?.control_id || "").trim() === controlId
        ));
        if (controlMatches.length !== 1) {
          throw new Error(`reviewed action candidate must match exactly one target control: ${controlId}`);
        }
        action.target_control_id = controlId;
        action.target_region_id = "";
        reviewedActionsChanged = true;
      }
      if (reviewedActionsChanged) normalizedPatch.action_candidates = reviewedActions;
      const actionableReviewedRegions = reviewedRegions.filter((region) => {
        const semanticAction = String(region?.semantic_action || region?.action_type || "").trim();
        return semanticAction
          && semanticAction !== "read"
          && semanticAction !== "read_only"
          && region?.bbox;
      });
      for (const region of actionableReviewedRegions) {
        const bbox = region?.bbox;
        const semanticAction = String(region?.semantic_action || region?.action_type || "").trim();
        if (
          !Number.isFinite(Number(bbox.x))
          || !Number.isFinite(Number(bbox.y))
          || !Number.isFinite(Number(bbox.w))
          || !Number.isFinite(Number(bbox.h))
          || Number(bbox.x) < 0
          || Number(bbox.y) < 0
          || Number(bbox.w) <= 0
          || Number(bbox.h) <= 0
        ) {
          throw new Error(`reviewed bbox must contain finite non-negative position and positive size: ${semanticAction}`);
        }
        const regionId = String(region?.region_id || region?.target_id || "").trim();
        if (!regionId) {
          throw new Error(`reviewed bbox must have an evidence region id: ${semanticAction}`);
        }
        const regionMatches = actionableReviewedRegions.filter((candidate) => (
          String(candidate?.semantic_action || candidate?.action_type || "").trim() === semanticAction
        ));
        if (regionMatches.length !== 1) {
          throw new Error(`reviewed bbox semantic action must match exactly one reviewed region: ${semanticAction}`);
        }
        const actionMatches = reviewedActions.filter((action) => (
          String(action?.semantic_action || action?.action_type || "").trim() === semanticAction
        ));
        if (actionMatches.length !== 1) {
          throw new Error(`reviewed bbox semantic action must match exactly one action candidate: ${semanticAction}`);
        }
        const action = actionMatches[0];
        const controlId = String(action?.target_control_id || action?.source_control_id || "").trim();
        const controlMatches = existingControls.filter((control) => String(control?.control_id || "").trim() === controlId);
        if (!controlId || controlMatches.length !== 1) {
          throw new Error(`reviewed bbox action candidate must match exactly one target control: ${controlId || semanticAction}`);
        }
        const controlIndex = existingControls.indexOf(controlMatches[0]);
        const updatedControl = {
          ...controlMatches[0],
          bbox: {
            x: Number(bbox.x),
            y: Number(bbox.y),
            w: Number(bbox.w),
            h: Number(bbox.h),
          },
          evidence_region_id: regionId,
          review_status: "needs_human_review",
          reviewed_by_human: false,
          display_only: true,
          artifact_is_authorization: false,
          execute_binding_enabled: false,
        };
        delete updatedControl.human_review_confirmation;
        delete updatedControl.reviewed_revision_hash;
        existingControls[controlIndex] = updatedControl;
      }
      if (existingControls.length) normalizedPatch.controls = existingControls;
      const nextSourcePaths = [
        normalizedReviewed,
        ...(Array.isArray(node.source_paths) ? node.source_paths : []),
      ].filter((value, index, values) => {
        const normalized = String(value || "").trim().replace(/\\/g, "/").toLowerCase();
        return normalized && normalized !== normalizedPrevious && values.findIndex((candidate) => (
          String(candidate || "").trim().replace(/\\/g, "/").toLowerCase() === normalized
        )) === index;
      });
      normalizedPatch.editable_review_source_path = normalizedReviewed;
      normalizedPatch.source_paths = nextSourcePaths;
      applyEditablePatch(node, normalizedPatch, EDITABLE_NODE_FIELDS);
      revokeNodeHumanReview(node);
      selectedNodeId = node.node_id;
      selectedLayer = "";
      selectedControlId = "";
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
      const changedActionFields = Object.entries(normalizedPatch).some(([key, value]) => (
        key !== "review_status"
        && EDITABLE_EDGE_FIELDS.has(key)
        && JSON.stringify(edge[key]) !== JSON.stringify(value)
      ));
      applyEditablePatch(edge, normalizedPatch, EDITABLE_EDGE_FIELDS);
      if (changedActionFields) {
        revokeGranularHumanReview(edge);
        const sourceNode = nodeById.get(edge.source_node_id);
        if (sourceNode) revokeNodeHumanReview(sourceNode);
      }
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
      stopBoundaryNodeIds.add(nodeId);
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
      if (node.review_status === "needs_learning") stopBoundaryNodeIds.add(nodeId);
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
        action_template_id: String(operation?.action_template_id || "").trim(),
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
      revokeNodeHumanReview(nodeById.get(sourceNodeId));
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
      const sourceNode = nodeById.get(removed.source_node_id);
      if (sourceNode) revokeNodeHumanReview(sourceNode);
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.edge_ids = edges.map((item) => item.edge_id);
      return clone(removed);
    }

    function removeInterfaceNode(nodeId) {
      const normalizedNodeId = String(nodeId || "").trim();
      const index = nodes.findIndex((item) => item.node_id === normalizedNodeId);
      if (index < 0) {
        throw new Error(`unknown interface workflow node: ${normalizedNodeId}`);
      }
      const [removed] = nodes.splice(index, 1);
      nodeById.delete(normalizedNodeId);
      for (let edgeIndex = edges.length - 1; edgeIndex >= 0; edgeIndex -= 1) {
        const edge = edges[edgeIndex];
        if (
          edge.source_node_id === normalizedNodeId
          || edge.target_node_id === normalizedNodeId
        ) {
          edges.splice(edgeIndex, 1);
        }
      }
      if (!review.workflow || typeof review.workflow !== "object") review.workflow = {};
      review.workflow.node_ids = nodes.map((item) => item.node_id);
      review.workflow.edge_ids = edges.map((item) => item.edge_id);
      if (review.workflow.entry_node_id === normalizedNodeId) {
        review.workflow.entry_node_id = nodes[0]?.node_id || "";
      }
      if (selectedNodeId === normalizedNodeId) selectedNodeId = nodes[0]?.node_id || "";
      if (focusedNodeId === normalizedNodeId) focusedNodeId = "";
      selectedLayer = "";
      selectedControlId = "";
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
      confirmNodeAndOutgoingHumanReview,
      confirmNodeHumanReview,
      confirmOperationActionCandidateHumanReview,
      confirmOperationEdgeHumanReview,
      confirmOperationHumanReviewBundle,
      confirmOperationTargetControlHumanReview,
      current,
      focusControl,
      focusInterface,
      graph,
      operationGranularReview,
      revokeOperationEdgeHumanReview,
      removeInterfaceNode,
      removeOperation,
      select,
      selectLayer,
      snapshot,
      updateEdge,
      updateNode,
      replaceReviewedNodeEvidenceBySource,
    };
  }

  function commitInterfaceWorkflowReviewForSave({
    state,
    nodeId,
    nodePatch,
    commitOperation,
    humanReviewConfirmed = false,
  } = {}) {
    if (!state) return null;
    const normalizedNodeId = String(nodeId || "").trim();
    if (normalizedNodeId) state.updateNode(normalizedNodeId, nodePatch || {});
    if (typeof commitOperation === "function") commitOperation();
    if (normalizedNodeId && humanReviewConfirmed) {
      const node = state.snapshot().nodes.find((item) => item.node_id === normalizedNodeId);
      if (node?.review_status !== "needs_learning") state.confirmNodeHumanReview(normalizedNodeId);
    }
    return state.snapshot();
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

  function buildLearningResultsReviewGroups(registry = {}, sources = []) {
    const groups = { reviewed: [], unreviewed: [] };
    const applications = registry && typeof registry.applications === "object"
      ? registry.applications
      : {};
    const workflows = registry && typeof registry.workflows === "object"
      ? registry.workflows
      : {};
    const applicationByWorkflow = new Map();
    const attachedSourcePaths = new Set();
    Object.entries(applications).forEach(([identityKey, application]) => {
      (Array.isArray(application?.workflow_ids) ? application.workflow_ids : []).forEach((workflowId) => {
        applicationByWorkflow.set(workflowId, {
          identity_key: identityKey,
          identity: clone(application?.application_identity || {}),
        });
      });
    });

    Object.entries(workflows).forEach(([workflowId, record]) => {
      if (!record || typeof record !== "object") return;
      const application = applicationByWorkflow.get(workflowId) || {
        identity_key: String(record.application_identity_key || ""),
        identity: {},
      };
      for (const bucket of ["unreviewed", "reviewed"]) {
        const interfaces = Array.isArray(record?.review_groups?.[bucket])
          ? record.review_groups[bucket].map((item) => clone(item))
          : [];
        interfaces.forEach((item) => {
          const candidates = [
            item?.editable_review_source_path,
            ...(Array.isArray(item?.source_paths) ? item.source_paths : []),
          ];
          candidates.forEach((value) => {
            const normalized = String(value || "").trim().replace(/\\/g, "/");
            if (normalized) attachedSourcePaths.add(normalized);
          });
        });
        if (!interfaces.length) continue;
        groups[bucket].push({
          workflow_id: workflowId,
          goal: String(record.goal || workflowId),
          application_identity_key: application.identity_key,
          application_identity: application.identity,
          interfaces,
        });
      }
    });
    const standalone = (Array.isArray(sources) ? sources : []).flatMap((source) => {
      if (!source || typeof source !== "object") return [];
      const candidates = [
        source.reviewed_template_candidate_path,
        source.source_path,
        source.source_trial_path,
        source.trial_result_path,
      ].map((value) => String(value || "").trim().replace(/\\/g, "/")).filter(Boolean);
      if (!candidates.length || candidates.some((value) => attachedSourcePaths.has(value))) return [];
      return [{
        node_id: "",
        display_name: String(source.screen_summary || source.state_guess || "未命名界面"),
        review_status: String(source.review_status || "needs_human_review"),
        source_path: candidates[0],
      }];
    });
    if (standalone.length) {
      groups.unreviewed.unshift({
        workflow_id: "",
        goal: "待加入流程",
        application_identity_key: "",
        application_identity: {},
        interfaces: standalone,
      });
    }
    return groups;
  }

  function buildInterfaceAssetLibrary(registry = {}, sources = []) {
    const applications = registry && typeof registry.applications === "object"
      ? registry.applications
      : {};
    const workflows = registry && typeof registry.workflows === "object"
      ? registry.workflows
      : {};
    const applicationByWorkflow = new Map();
    Object.entries(applications).forEach(([identityKey, application]) => {
      (Array.isArray(application?.workflow_ids) ? application.workflow_ids : []).forEach((workflowId) => {
        applicationByWorkflow.set(String(workflowId), {
          identity_key: String(identityKey || ""),
          identity: clone(application?.application_identity || {}),
        });
      });
    });

    const assets = new Map();
    const normalizedPath = (value) => String(value || "").trim().replace(/\\/g, "/");
    const assetKeyFor = (item, applicationIdentityKey = "") => {
      const sourcePath = normalizedPath(
        item?.editable_review_source_path
        || item?.source_path
        || (Array.isArray(item?.source_paths) ? item.source_paths[0] : ""),
      );
      if (sourcePath) return { asset_key: `path:${sourcePath.toLowerCase()}`, source_path: sourcePath };
      const nodeId = String(item?.node_id || item?.interface_id || "").trim();
      return {
        asset_key: `node:${String(applicationIdentityKey || "unknown").toLowerCase()}:${nodeId || "unknown"}`,
        source_path: "",
      };
    };
    const mergeAsset = (
      item,
      membership = null,
      application = {},
      projectionSource = "untrusted_parallel_projection",
    ) => {
      if (!item || typeof item !== "object") return;
      const identityKey = String(application.identity_key || "");
      const key = assetKeyFor(item, identityKey);
      const explicitlyUsable = (
        projectionSource === "server_reviewed"
        && String(item.review_status || "").trim() === "human_approved"
        && item.agent_usable === true
        && item.reviewed_by_human === true
        && item.agent_eligibility_reason === "human_reviewed_current_revision"
      );
      const blockedReason = projectionSource === "untrusted_parallel_projection"
        ? projectionSource
        : String(item.agent_eligibility_reason || "human_review_required");
      const existing = assets.get(key.asset_key);
      if (!existing) {
        assets.set(key.asset_key, {
          asset_key: key.asset_key,
          node_id: String(item.node_id || item.interface_id || ""),
          display_name: String(item.display_name || item.screen_summary || item.state_guess || "未命名界面"),
          review_status: String(item.review_status || "needs_human_review"),
          agent_usable: explicitlyUsable,
          agent_eligibility_reason: explicitlyUsable
            ? "human_reviewed_current_revision"
            : blockedReason,
          application_identity_key: identityKey,
          application_identity: clone(application.identity || {}),
          workflow_memberships: membership ? [membership] : [],
          source_path: key.source_path,
          source_paths: Array.from(new Set([
            key.source_path,
            ...(Array.isArray(item.source_paths) ? item.source_paths.map(normalizedPath) : []),
          ].filter(Boolean))),
        });
        return;
      }
      if (membership && !existing.workflow_memberships.some((entry) => entry.workflow_id === membership.workflow_id)) {
        existing.workflow_memberships.push(membership);
      }
      existing.source_paths = Array.from(new Set([
        ...existing.source_paths,
        ...(Array.isArray(item.source_paths) ? item.source_paths.map(normalizedPath) : []),
      ].filter(Boolean)));
      if (!explicitlyUsable) {
        existing.agent_usable = false;
        existing.review_status = String(item.review_status || "needs_human_review");
        existing.agent_eligibility_reason = blockedReason;
      }
    };

    Object.entries(workflows).forEach(([workflowId, record]) => {
      if (!record || typeof record !== "object") return;
      const application = applicationByWorkflow.get(String(workflowId)) || {
        identity_key: String(record.application_identity_key || ""),
        identity: {},
      };
      const membership = {
        workflow_id: String(workflowId),
        goal: String(record.goal || workflowId),
      };
      for (const bucket of ["reviewed", "unreviewed"]) {
        (Array.isArray(record?.review_groups?.[bucket]) ? record.review_groups[bucket] : [])
          .forEach((item) => mergeAsset(
            item,
            membership,
            application,
            bucket === "reviewed" ? "server_reviewed" : "server_unreviewed",
          ));
      }
    });

    (Array.isArray(sources) ? sources : []).forEach((source) => {
      if (!source || typeof source !== "object") return;
      const sourcePath = normalizedPath(
        source.reviewed_template_candidate_path
        || source.source_path
        || source.source_trial_path
        || source.trial_result_path,
      );
      if (!sourcePath) return;
      const key = `path:${sourcePath.toLowerCase()}`;
      if (assets.has(key)) return;
      mergeAsset(
        { ...source, source_path: sourcePath },
        null,
        {},
        "untrusted_parallel_projection",
      );
    });

    const result = { reviewed: [], unreviewed: [] };
    Array.from(assets.values())
      .sort((left, right) => left.display_name.localeCompare(right.display_name, "zh-CN"))
      .forEach((asset) => {
        asset.workflow_memberships.sort((left, right) => left.workflow_id.localeCompare(right.workflow_id));
        result[asset.agent_usable ? "reviewed" : "unreviewed"].push(asset);
      });
    return result;
  }

  function buildInterfaceAssetLibraryRows(registry = {}, sources = []) {
    const library = buildInterfaceAssetLibrary(registry, sources);
    return [...library.unreviewed, ...library.reviewed]
      .map((asset) => {
        const memberships = Array.isArray(asset.workflow_memberships)
          ? asset.workflow_memberships
          : [];
        const status = String(asset.review_status || "needs_human_review").trim();
        const reason = String(asset.agent_eligibility_reason || "").trim();
        const statusKind = asset.agent_usable === true
          ? "reviewed_current"
          : status === "needs_learning"
            ? "needs_learning"
            : ["human_review_revision_missing", "human_review_revision_mismatch"].includes(reason)
              ? "review_stale"
              : "needs_human_review";
        return {
          ...clone(asset),
          workflow_memberships: memberships.map((membership) => clone(membership)),
          status_kind: statusKind,
          primary_action: memberships.length === 0
            ? "attach_workflow"
            : memberships.length === 1
              ? "open_workflow"
              : "choose_workflow",
        };
      })
      .sort((left, right) => left.display_name.localeCompare(right.display_name, "zh-CN"));
  }

  function buildAttachDialogModel(asset = {}, workflows = []) {
    const sourcePath = String(
      asset.source_path
      || (Array.isArray(asset.source_paths) ? asset.source_paths[0] : "")
      || "",
    ).trim();
    const agentUsable = asset.agent_usable === true;
    return {
      asset_key: String(asset.asset_key || ""),
      display_name: userFacingLearningLabel(
        asset.display_name || asset.node_id || "未命名界面",
      ),
      source_path: sourcePath,
      review_status: String(asset.review_status || "needs_human_review"),
      agent_usable: agentUsable,
      can_attach: Boolean(sourcePath),
      can_agent_use: agentUsable,
      warning: agentUsable
        ? "审核通过仍不是执行授权；真实动作必须重新定位并经过 Gate。"
        : "未审核界面仅可加入流程继续人工整理，Agent 不可直接使用。",
      workflows: (Array.isArray(workflows) ? workflows : []).map((workflow) => ({
        workflow_id: String(workflow?.workflow_id || ""),
        label: String(workflow?.label || workflow?.goal || workflow?.workflow_id || "未命名流程"),
      })).filter((workflow) => workflow.workflow_id),
    };
  }

  const api = {
    CONTRACT_VERSION,
    buildAttachDialogModel,
    buildInterfaceAssetLibrary,
    buildInterfaceAssetLibraryRows,
    buildLearningResultsReviewGroups,
    commitInterfaceWorkflowReviewForSave,
    createEmptyInterfaceWorkflowReview,
    createLatestInterfaceWorkflowLoadGuard,
    createInterfaceWorkflowWorkbenchState,
    createInterfaceWorkflowReviewState,
    interfaceWorkflowControlChoices,
    mergeEditableWorkflowReview,
    projectLiveSafeFillPreflightReview,
    projectInterfaceWorkflowStepAudit,
    projectLearningDraftOwnershipConflicts,
    buildLearningDraftOwnershipOperations,
    resolveInterfaceAssetOpenTarget,
    resolveDraftItemWorkflowBinding,
    resolveInterfaceWorkflowCorrectionTarget,
    userFacingLearningLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  globalScope.InterfaceWorkflowReview = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
