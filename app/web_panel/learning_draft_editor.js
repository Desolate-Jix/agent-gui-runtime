(function attachLearningDraftEditor(globalScope) {
  function clone(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

  function key(kind, id) {
    return `${kind === "action" ? "action" : "region"}:${String(id || "").trim()}`;
  }

  const EDITABLE_METADATA_FIELDS = [
    "label",
    "description",
    "semantic_action",
    "action_type",
    "input_semantics",
    "destination",
    "verification_rule",
    "risk_level",
    "requires_confirmation",
  ];

  function editableMetadata(value) {
    const source = value && typeof value === "object" ? value : {};
    const metadata = {};
    EDITABLE_METADATA_FIELDS.forEach((field) => {
      if (Object.prototype.hasOwnProperty.call(source, field)) {
        metadata[field] = clone(source[field]);
      }
    });
    return metadata;
  }

  function normalizeBbox(value) {
    const source = value && typeof value === "object" ? value : {};
    const bbox = {
      x: Math.round(Number(source.x || 0)),
      y: Math.round(Number(source.y || 0)),
      w: Math.round(Number(source.w ?? source.width ?? 0)),
      h: Math.round(Number(source.h ?? source.height ?? 0)),
    };
    if (bbox.x < 0 || bbox.y < 0 || bbox.w <= 0 || bbox.h <= 0) throw new Error("invalid bbox");
    return bbox;
  }

  function clampBboxToImage(value, imageWidth, imageHeight, options = {}) {
    const bbox = normalizeBbox(value);
    const widthLimit = Math.max(2, Math.round(Number(imageWidth || 0)));
    const heightLimit = Math.max(2, Math.round(Number(imageHeight || 0)));
    if (options.resize === true) {
      const x = Math.min(bbox.x, widthLimit - 2);
      const y = Math.min(bbox.y, heightLimit - 2);
      return {
        x,
        y,
        w: Math.max(2, Math.min(bbox.w, widthLimit - x)),
        h: Math.max(2, Math.min(bbox.h, heightLimit - y)),
      };
    }
    const w = Math.min(bbox.w, widthLimit);
    const h = Math.min(bbox.h, heightLimit);
    return {
      x: Math.max(0, Math.min(widthLimit - w, bbox.x)),
      y: Math.max(0, Math.min(heightLimit - h, bbox.y)),
      w,
      h,
    };
  }

  function resizeBboxFromHandle(value, handle, deltaX, deltaY, imageWidth, imageHeight) {
    const bbox = clampBboxToImage(value, imageWidth, imageHeight, { resize: true });
    const widthLimit = Math.max(2, Math.round(Number(imageWidth || 0)));
    const heightLimit = Math.max(2, Math.round(Number(imageHeight || 0)));
    const direction = String(handle || "").trim().toLowerCase();
    let left = bbox.x;
    let top = bbox.y;
    let right = Math.min(widthLimit, bbox.x + bbox.w);
    let bottom = Math.min(heightLimit, bbox.y + bbox.h);
    const dx = Math.round(Number(deltaX || 0));
    const dy = Math.round(Number(deltaY || 0));

    if (direction.includes("w")) left = Math.max(0, Math.min(right - 2, left + dx));
    if (direction.includes("e")) right = Math.min(widthLimit, Math.max(left + 2, right + dx));
    if (direction.includes("n")) top = Math.max(0, Math.min(bottom - 2, top + dy));
    if (direction.includes("s")) bottom = Math.min(heightLimit, Math.max(top + 2, bottom + dy));

    return {
      x: left,
      y: top,
      w: right - left,
      h: bottom - top,
    };
  }

  function learningDraftEditorPointerMode(addMode, resizeHandle) {
    if (addMode) return "add";
    const handle = String(resizeHandle || "").trim().toLowerCase();
    return handle ? `resize:${handle}` : "move";
  }

  function safeBbox(value) {
    try {
      return normalizeBbox(value);
    } catch (_error) {
      return null;
    }
  }

  function bboxArea(bbox) {
    return bbox ? bbox.w * bbox.h : 0;
  }

  function containmentRatio(inner, outer) {
    if (!inner || !outer) return 0;
    const left = Math.max(inner.x, outer.x);
    const top = Math.max(inner.y, outer.y);
    const right = Math.min(inner.x + inner.w, outer.x + outer.w);
    const bottom = Math.min(inner.y + inner.h, outer.y + outer.h);
    const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
    return bboxArea(inner) ? intersection / bboxArea(inner) : 0;
  }

  function normalizedItemText(item) {
    return [
      item?.target_id,
      item?.label,
      item?.role,
      item?.kind,
      item?.element_kind,
      item?.visual_kind,
      item?.source,
    ].map((value) => String(value || "").trim().toLowerCase()).join(" ");
  }

  function isDangerousItem(item) {
    const action = `${item?.semantic_action || ""} ${item?.action_type || ""}`.toLowerCase();
    return String(item?.risk_level || "").toLowerCase() === "dangerous"
      || item?.requires_confirmation === true
      || /\b(final_submit|submit|send|confirm|payment|purchase|delete)\b/.test(action);
  }

  function hasDistinctInteraction(item) {
    const action = String(item?.semantic_action || item?.action_type || "").trim().toLowerCase();
    const input = String(item?.input_semantics || "").trim().toLowerCase();
    const destination = item?.destination && typeof item.destination === "object"
      ? item.destination
      : {};
    const destinationKind = String(destination.kind || "").trim().toLowerCase();
    return (action && !["none", "read_only", "display"].includes(action))
      || (input && input !== "none")
      || (destinationKind && destinationKind !== "none");
  }

  function isFragmentItem(item) {
    const text = normalizedItemText(item);
    return /\b(ocr|text|icon|glyph|partial|fragment|page_text|content_node)\b/.test(text)
      || /(^|[_-])(ocr|text|icon|glyph|partial|fragment)([_-]|$)/.test(text);
  }

  function isCredibleParent(item) {
    if (!item || item.target_kind === "action" || isFragmentItem(item)) return false;
    const text = normalizedItemText(item);
    return /\b(button|card|input|field|row|item|group|control|container|dialog|form|panel|toolbar|navigation|nav)\b/.test(text)
      || /(^|[_-])(button|card|input|field|row|item|group|control|container|dialog|form|panel|toolbar|navigation|nav)([_-]|$)/.test(text);
  }

  function buildLearningDraftDisplayProjection(rawItems = [], options = {}) {
    const items = Array.isArray(rawItems) ? rawItems.map((item) => clone(item)) : [];
    const compact = options.compact !== false;
    const selectedKey = options.selected
      ? key(options.selected.target_kind, options.selected.target_id)
      : "";
    const protectedKeys = new Set(
      Array.isArray(options.protectedKeys) ? options.protectedKeys.map((value) => String(value)) : [],
    );
    if (selectedKey) protectedKeys.add(selectedKey);
    if (!compact) {
      return { visibleItems: items, groups: [], hiddenKeys: [], decisions: [] };
    }

    const entries = items.map((item, index) => ({
      item,
      index,
      itemKey: key(item.target_kind, item.target_id),
      bbox: safeBbox(item.bbox),
    }));
    const owners = entries
      .filter((entry) => entry.bbox && isCredibleParent(entry.item))
      .sort((left, right) => bboxArea(left.bbox) - bboxArea(right.bbox));
    const hiddenKeys = new Set();
    const groupsByOwner = new Map();
    const decisions = [];

    entries.forEach((entry) => {
      if (
        !entry.bbox
        || entry.item.target_kind === "action"
        || protectedKeys.has(entry.itemKey)
        || isDangerousItem(entry.item)
        || hasDistinctInteraction(entry.item)
        || !isFragmentItem(entry.item)
      ) return;

      const explicitParentId = String(entry.item.parent_region_id || "").trim();
      const owner = owners.find((candidate) => {
        if (candidate.itemKey === entry.itemKey || protectedKeys.has(candidate.itemKey)) return false;
        const ratio = containmentRatio(entry.bbox, candidate.bbox);
        if (ratio < Number(options.containmentThreshold || 0.88)) return false;
        if (explicitParentId) return candidate.item.target_id === explicitParentId;
        const sizeRatio = bboxArea(candidate.bbox) / Math.max(1, bboxArea(entry.bbox));
        return sizeRatio > 1.15 && sizeRatio <= Number(options.maxParentAreaRatio || 40);
      });
      if (!owner) return;

      hiddenKeys.add(entry.itemKey);
      if (!groupsByOwner.has(owner.itemKey)) {
        groupsByOwner.set(owner.itemKey, {
          ownerKey: owner.itemKey,
          ownerKind: owner.item.target_kind,
          ownerId: owner.item.target_id,
          memberKeys: [],
          reason: "contained_fragment",
        });
      }
      groupsByOwner.get(owner.itemKey).memberKeys.push(entry.itemKey);
      decisions.push({
        itemKey: entry.itemKey,
        ownerKey: owner.itemKey,
        reason: "contained_fragment",
      });
    });

    return {
      visibleItems: entries
        .filter((entry) => !hiddenKeys.has(entry.itemKey))
        .sort((left, right) => left.index - right.index)
        .map((entry) => entry.item),
      groups: Array.from(groupsByOwner.values()),
      hiddenKeys: Array.from(hiddenKeys),
      decisions,
    };
  }

  function createLearningDraftEditorState(initialItems = []) {
    const items = new Map();
    const history = [];
    const future = [];

    initialItems.forEach((raw) => {
      const item = clone(raw) || {};
      const targetKind = item.target_kind === "action" ? "action" : "region";
      const targetId = String(item.target_id || "").trim();
      if (!targetId) return;
      item.target_kind = targetKind;
      item.target_id = targetId;
      item.bbox = normalizeBbox(item.bbox);
      items.set(key(targetKind, targetId), item);
    });

    function applyInternal(rawOperation) {
      const operation = clone(rawOperation) || {};
      const targetKind = operation.target_kind === "action" ? "action" : "region";
      const targetId = String(operation.target_id || "").trim();
      const itemKey = key(targetKind, targetId);
      const current = items.get(itemKey);
      if (!targetId) throw new Error("target_id is required");

      if (operation.op === "add") {
        if (current) throw new Error("target already exists");
        const item = {
          ...(clone(operation.item) || {}),
          target_kind: targetKind,
          target_id: targetId,
          candidate_only: true,
          requires_human_review: true,
          artifact_is_authorization: false,
          execute_binding_enabled: false,
          final_submit_forbidden: true,
        };
        item.bbox = normalizeBbox(item.bbox);
        items.set(itemKey, item);
        return {
          operation: { ...operation, target_kind: targetKind, target_id: targetId, item: clone(item) },
          inverse: { op: "delete", target_kind: targetKind, target_id: targetId },
        };
      }
      if (!current) throw new Error("target does not exist");
      if (operation.op === "delete") {
        items.delete(itemKey);
        return {
          operation: { ...operation, target_kind: targetKind, target_id: targetId, before_item: clone(current) },
          inverse: { op: "add", target_kind: targetKind, target_id: targetId, item: clone(current) },
        };
      }
      if (operation.op === "update_bbox") {
        const beforeBbox = normalizeBbox(current.bbox);
        const afterBbox = normalizeBbox(operation.after_bbox);
        current.bbox = clone(afterBbox);
        return {
          operation: {
            ...operation,
            target_kind: targetKind,
            target_id: targetId,
            before_bbox: beforeBbox,
            after_bbox: afterBbox,
          },
          inverse: {
            op: "update_bbox",
            target_kind: targetKind,
            target_id: targetId,
            after_bbox: beforeBbox,
          },
        };
      }
      if (operation.op === "update_role" || operation.op === "update_parent") {
        const field = operation.op === "update_role" ? "role" : "parent_region_id";
        const beforeValue = String(current[field] || "");
        const afterValue = String(operation.after_value || "");
        current[field] = afterValue;
        return {
          operation: {
            ...operation,
            target_kind: targetKind,
            target_id: targetId,
            before_value: beforeValue,
            after_value: afterValue,
          },
          inverse: {
            op: operation.op,
            target_kind: targetKind,
            target_id: targetId,
            after_value: beforeValue,
          },
        };
      }
      if (operation.op === "update_metadata") {
        const afterMetadata = editableMetadata(operation.after_metadata);
        const beforeMetadata = {};
        Object.keys(afterMetadata).forEach((field) => {
          beforeMetadata[field] = clone(current[field]);
          current[field] = clone(afterMetadata[field]);
        });
        current.candidate_only = true;
        current.requires_human_review = true;
        current.artifact_is_authorization = false;
        current.execute_binding_enabled = false;
        current.final_submit_forbidden = true;
        return {
          operation: {
            ...operation,
            target_kind: targetKind,
            target_id: targetId,
            before_metadata: beforeMetadata,
            after_metadata: clone(afterMetadata),
          },
          inverse: {
            op: "update_metadata",
            target_kind: targetKind,
            target_id: targetId,
            after_metadata: beforeMetadata,
          },
        };
      }
      throw new Error(`unsupported operation: ${operation.op}`);
    }

    return {
      apply(operation) {
        const applied = applyInternal(operation);
        history.push(applied);
        future.length = 0;
        return clone(applied.operation);
      },
      undo() {
        const entry = history.pop();
        if (!entry) return null;
        applyInternal(entry.inverse);
        future.push(entry);
        return clone(entry.operation);
      },
      redo() {
        const entry = future.pop();
        if (!entry) return null;
        const applied = applyInternal(entry.operation);
        history.push(applied);
        return clone(applied.operation);
      },
      getItem(targetKind, targetId) {
        return clone(items.get(key(targetKind, targetId)) || null);
      },
      listItems() {
        return Array.from(items.values(), (item) => clone(item));
      },
      exportOperations() {
        return history.map((entry) => clone(entry.operation));
      },
      editedKeys() {
        return Array.from(new Set(history.map((entry) => key(
          entry.operation.target_kind,
          entry.operation.target_id,
        ))));
      },
      canUndo() {
        return history.length > 0;
      },
      canRedo() {
        return future.length > 0;
      },
    };
  }

  const api = {
    buildLearningDraftDisplayProjection,
    clampBboxToImage,
    createLearningDraftEditorState,
    learningDraftEditorPointerMode,
    resizeBboxFromHandle,
  };
  globalScope.LearningDraftEditorState = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
