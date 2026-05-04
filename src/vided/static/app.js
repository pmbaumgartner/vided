const state = {
  project: null,
  framesDoc: null,
  redactionsDoc: null,
  frames: [],
  video: null,
  currentIndex: 0,
  loadedFrameIndex: null,
  image: null,
  dragging: false,
  dragStart: null,
  draft: {
    startSeconds: null,
    rectDisplay: null,
    rectVideo: null,
  },
  redactionIdCounter: 0,
  blurLevel: "medium",
  dirty: false,
  selectedRedactionId: null,
  editingRedactionId: null,
  redactionEdit: null,
  saveState: "clean",
  saveError: "",
  saveVersion: 0,
  saveInFlight: false,
  saveQueued: false,
  filmstripDrag: {
    pointerId: null,
    startX: 0,
    startScrollLeft: 0,
    dragging: false,
    suppressClickUntil: 0,
  },
};

const BLUR_PRESETS = {
  low: 10,
  medium: 18,
  high: 30,
};

const EDIT_HANDLE_SIZE = 10;
const MIN_EDIT_RECT_SIZE = 8;

// Icons use path data from Lucide, ISC licensed: https://lucide.dev/license
const ICON_PATHS = {
  jump:
    '<circle cx="12" cy="12" r="10"></circle><path d="M8 12h8"></path><path d="m12 16 4-4-4-4"></path>',
  edit:
    '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"></path><path d="m15 5 4 4"></path>',
  frame: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><path d="M7 3v18"></path>',
  trash:
    '<path d="M3 6h18"></path><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path>',
};

const els = {
  projectMeta: document.getElementById("projectMeta"),
  currentFrameLabel: document.getElementById("currentFrameLabel"),
  currentTimeLabel: document.getElementById("currentTimeLabel"),
  draftStatus: document.getElementById("draftStatus"),
  draftActionBar: document.getElementById("draftActionBar"),
  canvas: document.getElementById("frameCanvas"),
  filmstrip: document.getElementById("filmstrip"),
  filmstripScrollLeftButton: document.getElementById("filmstripScrollLeft"),
  filmstripScrollRightButton: document.getElementById("filmstripScrollRight"),
  redactionList: document.getElementById("redactionList"),
  selectionPanel: document.getElementById("selectionPanel"),
  saveButton: document.getElementById("saveButton"),
  saveState: document.getElementById("saveState"),
  clearDraftButton: document.getElementById("clearDraftButton"),
  setStartButton: document.getElementById("setStartButton"),
  saveDraftButton: document.getElementById("saveDraftButton"),
  bufferPreInput: document.getElementById("bufferPreInput"),
  bufferPostInput: document.getElementById("bufferPostInput"),
  blurOptions: Array.from(document.querySelectorAll(".blur-option")),
};

const ctx = els.canvas.getContext("2d");

function fmtTime(seconds) {
  const value = Number(seconds || 0);
  const mins = Math.floor(value / 60);
  const secs = value - mins * 60;
  return `${mins}:${secs.toFixed(2).padStart(5, "0")}`;
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function currentFrame() {
  return state.frames[state.currentIndex] || null;
}

function displayFrameNumber(index) {
  return Number(index) + 1;
}

function nearestFrameIndexForTime(seconds) {
  if (state.frames.length === 0) return null;
  const target = Number(seconds || 0);
  let bestIndex = 0;
  let bestDiff = Infinity;
  state.frames.forEach((frame, index) => {
    const diff = Math.abs(Number(frame.time) - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function displayFrameRange(startSeconds, endSeconds) {
  const startIndex = nearestFrameIndexForTime(startSeconds);
  const endIndex = nearestFrameIndexForTime(endSeconds);
  if (startIndex === null || endIndex === null) return "—";
  const start = displayFrameNumber(Math.min(startIndex, endIndex));
  const end = displayFrameNumber(Math.max(startIndex, endIndex));
  return start === end ? `${start}` : `${start}-${end}`;
}

function detailRow(label, value) {
  const row = document.createElement("div");
  row.className = "detail-row";

  const labelEl = document.createElement("span");
  labelEl.textContent = label;

  const valueEl = document.createElement("strong");
  valueEl.textContent = value;

  row.appendChild(labelEl);
  row.appendChild(valueEl);
  return row;
}

function setShortcutButton(button, label, shortcut, ariaShortcut, ariaLabel = label) {
  button.replaceChildren(document.createTextNode(`${label} `));
  const key = document.createElement("kbd");
  key.textContent = shortcut;
  button.appendChild(key);
  button.setAttribute("aria-keyshortcuts", ariaShortcut);
  button.setAttribute("aria-label", ariaLabel);
}

function redactionDisplayInfo(redaction) {
  const selectedStart = redaction.selected_start_seconds ?? redaction.effective_start_seconds;
  const selectedEnd = redaction.selected_end_seconds ?? redaction.effective_end_seconds;
  const r = redaction.rect || {};
  return {
    frames: displayFrameRange(selectedStart, selectedEnd),
    time: `${fmtTime(redaction.effective_start_seconds)} to ${fmtTime(redaction.effective_end_seconds)}`,
    rect: `x ${r.x}, y ${r.y}, ${r.w}x${r.h}`,
  };
}

function updateSaveState(status = null) {
  if (status) {
    state.saveState = status;
  } else if (state.saveInFlight) {
    state.saveState = "saving";
  } else if (state.dirty && state.saveState !== "error") {
    state.saveState = "dirty";
  } else if (!state.dirty) {
    state.saveState = "clean";
  }

  const labels = {
    clean: "Saved",
    dirty: "Unsaved changes",
    saving: "Autosaving...",
    saved: "Saved",
    error: "Autosave failed",
  };
  const saveState = state.saveState || (state.dirty ? "dirty" : "clean");
  els.saveState.textContent = labels[saveState] || labels.clean;
  els.saveState.className = `save-state ${saveState}`;
  els.saveState.title = saveState === "error" ? state.saveError : "";
  els.saveButton.hidden = saveState !== "error";
  els.saveButton.disabled = saveState !== "error" || state.saveInFlight || !state.dirty;
  els.saveButton.textContent = "Retry save";
  els.saveButton.setAttribute("aria-label", "Retry autosave");
}

function markDirty() {
  state.dirty = true;
  state.saveVersion += 1;
  state.saveError = "";
  if (!state.saveInFlight) {
    state.saveState = "dirty";
  }
  updateSaveState();
}

function markClean() {
  state.dirty = false;
  state.saveState = "saved";
  state.saveError = "";
  updateSaveState();
}

function queueAutosave() {
  saveRedactions().catch(() => {});
}

function commitRedactionsChange() {
  markDirty();
  queueAutosave();
}

function filmstripMaxScroll() {
  return Math.max(0, els.filmstrip.scrollWidth - els.filmstrip.clientWidth);
}

function canScrollFilmstrip() {
  return filmstripMaxScroll() > 1;
}

function updateFilmstripScrollButtons() {
  const maxScroll = filmstripMaxScroll();
  const canScroll = maxScroll > 1;
  const atStart = els.filmstrip.scrollLeft <= 1;
  const atEnd = els.filmstrip.scrollLeft >= maxScroll - 1;

  els.filmstripScrollLeftButton.disabled = !canScroll || atStart;
  els.filmstripScrollRightButton.disabled = !canScroll || atEnd;
  els.filmstripScrollLeftButton.classList.toggle("is-hidden", !canScroll);
  els.filmstripScrollRightButton.classList.toggle("is-hidden", !canScroll);
}

function scrollFilmstripByPage(direction) {
  const amount = Math.max(160, els.filmstrip.clientWidth * 0.8);
  els.filmstrip.scrollBy({ left: direction * amount, behavior: "smooth" });
  window.setTimeout(updateFilmstripScrollButtons, 250);
}

function ensureActiveThumbVisible(align = "nearest") {
  const active = els.filmstrip.querySelector(".thumb.active");
  if (!active || !canScrollFilmstrip()) {
    updateFilmstripScrollButtons();
    return;
  }
  active.scrollIntoView({ block: "nearest", inline: align, behavior: "smooth" });
  window.setTimeout(updateFilmstripScrollButtons, 250);
}

function getDefault(name, fallback) {
  const docDefaults = state.redactionsDoc?.defaults || {};
  return Number(docDefaults[name] ?? fallback);
}

function blurLevelForRadius(radius) {
  const value = Number(radius || BLUR_PRESETS.medium);
  if (value <= (BLUR_PRESETS.low + BLUR_PRESETS.medium) / 2) return "low";
  if (value >= (BLUR_PRESETS.medium + BLUR_PRESETS.high) / 2) return "high";
  return "medium";
}

function selectedBlurRadius() {
  return BLUR_PRESETS[state.blurLevel] || BLUR_PRESETS.medium;
}

function iconSvg(name) {
  return `<svg aria-hidden="true" viewBox="0 0 24 24">${ICON_PATHS[name] || ""}</svg>`;
}

function makeIconButton(iconName, label, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = ["icon-button", className].filter(Boolean).join(" ");
  button.innerHTML = iconSvg(iconName);
  button.setAttribute("aria-label", label);
  button.title = label;
  return button;
}

function setBlurLevel(level) {
  state.blurLevel = BLUR_PRESETS[level] ? level : "medium";
  for (const button of els.blurOptions) {
    button.classList.toggle("active", button.dataset.blurLevel === state.blurLevel);
    button.setAttribute("aria-pressed", String(button.dataset.blurLevel === state.blurLevel));
  }
}

function hasDraft() {
  return state.draft.startSeconds !== null || Boolean(state.draft.rectVideo);
}

function isDraftReady() {
  return state.draft.startSeconds !== null && Boolean(state.draft.rectVideo);
}

function redactions() {
  return state.redactionsDoc?.redactions || [];
}

function redactionKey(redaction, index) {
  return redaction?.id || `redaction_index_${index}`;
}

function findRedactionEntry(key) {
  const list = redactions();
  const index = list.findIndex((redaction, idx) => redactionKey(redaction, idx) === key);
  if (index < 0) return null;
  return { redaction: list[index], index, key: redactionKey(list[index], index) };
}

function currentFrameTimeForCanvas() {
  return Number((state.frames[state.loadedFrameIndex] || currentFrame())?.time || 0);
}

function generateRedactionId() {
  state.redactionIdCounter += 1;
  const stamp = Date.now().toString(36);
  const suffix = state.redactionIdCounter.toString(36).padStart(2, "0");
  return `redaction_${stamp}_${suffix}`;
}

function isFrameInDraftRange(time) {
  if (!isDraftReady()) return false;
  const current = currentFrame();
  if (!current) return false;
  const start = Math.min(Number(state.draft.startSeconds), Number(current.time));
  const end = Math.max(Number(state.draft.startSeconds), Number(current.time));
  if (end <= start) {
    return Math.abs(Number(time) - start) < 0.000001;
  }
  return Number(time) >= start && Number(time) <= end;
}

async function loadProject() {
  const response = await fetch("/api/project");
  if (!response.ok) {
    throw new Error(`Failed to load project: ${response.status}`);
  }
  const payload = await response.json();
  state.project = payload.project;
  state.framesDoc = payload.frames;
  state.redactionsDoc = payload.redactions;
  state.frames = payload.frames.frames || [];
  state.video = payload.redactions.video || payload.frames.video || payload.project.trimmed_video || {};

  els.bufferPreInput.value = getDefault("buffer_pre_seconds", 0.5);
  els.bufferPostInput.value = getDefault("buffer_post_seconds", 0.5);
  setBlurLevel(blurLevelForRadius(state.redactionsDoc?.defaults?.style?.luma_radius));

  const duration = state.video.duration ? fmtTime(state.video.duration) : "unknown duration";
  const size = state.video.width && state.video.height ? `${state.video.width}×${state.video.height}` : "unknown size";
  els.projectMeta.textContent = `${size}, ${duration}, ${state.frames.length} thumbnails`;
  updateDraftStatus();

  renderFilmstrip();
  renderRedactionList();
  if (state.frames.length > 0) {
    await selectFrame(0);
  } else {
    els.draftStatus.textContent = "No thumbnails found. Restart `vided ui` to regenerate them.";
  }
}

function renderFilmstrip() {
  els.filmstrip.innerHTML = "";
  if (state.frames.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No thumbnails generated yet.";
    els.filmstrip.appendChild(empty);
    return;
  }

  for (const frame of state.frames) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "thumb";
    item.dataset.index = frame.index;
    item.title = `Frame ${displayFrameNumber(frame.index)} at ${fmtTime(frame.time)}`;

    const imageWrap = document.createElement("div");
    imageWrap.className = "thumb-image-wrap";

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = `/${frame.image}`;
    img.alt = `Frame ${displayFrameNumber(frame.index)}`;

    const overlayLayer = document.createElement("div");
    overlayLayer.className = "thumb-overlays";

    const label = document.createElement("span");
    label.className = "thumb-time";
    label.textContent = fmtTime(frame.time);

    imageWrap.appendChild(img);
    imageWrap.appendChild(overlayLayer);
    item.appendChild(imageWrap);
    item.appendChild(label);
    item.addEventListener("click", () => selectFrame(frame.index));
    els.filmstrip.appendChild(item);
  }
  updateFilmstripState();
  updateFilmstripScrollButtons();
}

function updateFilmstripState() {
  const current = currentFrame();
  for (const thumb of els.filmstrip.querySelectorAll(".thumb")) {
    const index = Number(thumb.dataset.index);
    const frame = state.frames[index];
    const time = Number(frame?.time || 0);
    const activeRedactions = frame ? visibleRedactionEntriesAt(time) : [];
    const overlayLayer = thumb.querySelector(".thumb-overlays");

    thumb.classList.toggle("active", index === state.currentIndex);
    thumb.classList.toggle(
      "draft-start",
      state.draft.startSeconds !== null && Math.abs(time - Number(state.draft.startSeconds)) < 0.000001,
    );
    thumb.classList.toggle("draft-range", isFrameInDraftRange(time));

    if (overlayLayer) {
      overlayLayer.innerHTML = "";
      activeRedactions
        .filter((entry) => entry.key !== state.selectedRedactionId)
        .forEach((entry, overlayIndex) => {
          appendThumbOverlay(overlayLayer, entry.redaction.rect, "saved", overlayIndex);
        });
      const selectedEntry = activeRedactions.find((entry) => entry.key === state.selectedRedactionId);
      if (selectedEntry) {
        const kind = selectedEntry.key === state.editingRedactionId ? "editing" : "selected";
        appendThumbOverlay(overlayLayer, selectedEntry.redaction.rect, kind, activeRedactions.length);
      }
      if (isFrameInDraftRange(time)) {
        appendThumbOverlay(overlayLayer, state.draft.rectVideo, "draft", activeRedactions.length);
      }
    }
  }
  if (current) {
    els.currentFrameLabel.textContent = `Frame ${displayFrameNumber(current.index)}`;
    els.currentTimeLabel.textContent = fmtTime(current.time);
  }
  updateDraftStatus();
}

async function selectFrame(index, options = {}) {
  if (index < 0 || index >= state.frames.length) return;
  const scrollAlign = options.scrollAlign || "nearest";
  state.currentIndex = index;
  const requestedIndex = index;
  const frame = state.frames[requestedIndex];
  updateFilmstripState();
  ensureActiveThumbVisible(scrollAlign);

  const image = new Image();
  image.onload = () => {
    if (state.currentIndex !== requestedIndex) return;
    state.image = image;
    state.loadedFrameIndex = requestedIndex;
    els.canvas.width = image.naturalWidth;
    els.canvas.height = image.naturalHeight;
    drawCanvas();
  };
  image.src = `/${frame.image}`;
}

function drawBlurPreview(rect) {
  if (!state.image || !rect) return;
  const x = clamp(Math.floor(Number(rect.x || 0)), 0, Math.max(0, els.canvas.width - 1));
  const y = clamp(Math.floor(Number(rect.y || 0)), 0, Math.max(0, els.canvas.height - 1));
  const maxW = els.canvas.width - x;
  const maxH = els.canvas.height - y;
  if (maxW <= 0 || maxH <= 0) return;
  const w = clamp(Math.ceil(Number(rect.w || 0)), 1, maxW);
  const h = clamp(Math.ceil(Number(rect.h || 0)), 1, maxH);

  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.filter = "blur(6px)";
  ctx.drawImage(state.image, x, y, w, h, x, y, w, h);
  ctx.restore();
}

function drawRedactionOverlay(rect, options = {}) {
  drawBlurPreview(rect);
  ctx.save();
  if (options.editing) {
    ctx.fillStyle = "rgba(255, 216, 107, 0.2)";
    ctx.strokeStyle = "rgba(255, 216, 107, 0.98)";
    ctx.lineWidth = 4;
  } else if (options.selected) {
    ctx.fillStyle = "rgba(244, 246, 248, 0.14)";
    ctx.strokeStyle = "rgba(244, 246, 248, 0.98)";
    ctx.lineWidth = 3;
  } else {
    ctx.fillStyle = "rgba(125, 184, 255, 0.22)";
    ctx.strokeStyle = "rgba(125, 184, 255, 0.95)";
    ctx.lineWidth = 3;
  }
  ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  ctx.restore();

  if (options.editing) {
    ctx.save();
    ctx.fillStyle = "#ffd86b";
    ctx.strokeStyle = "#101218";
    ctx.lineWidth = 2;
    const size = EDIT_HANDLE_SIZE;
    for (const handle of editHandlesForRect(rect)) {
      ctx.fillRect(handle.x - size / 2, handle.y - size / 2, size, size);
      ctx.strokeRect(handle.x - size / 2, handle.y - size / 2, size, size);
    }
    ctx.restore();
  }
}

function drawCanvas() {
  if (!state.image) return;
  ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
  ctx.drawImage(state.image, 0, 0);

  const frame = state.frames[state.loadedFrameIndex] || currentFrame();
  const t = frame?.time || 0;
  const entries = visibleRedactionEntriesAt(t);
  const selectedEntry = entries.find((entry) => entry.key === state.selectedRedactionId);

  for (const entry of entries) {
    if (entry.key === state.selectedRedactionId) continue;
    drawRedactionOverlay(videoRectToDisplay(entry.redaction.rect));
  }

  if (selectedEntry) {
    drawRedactionOverlay(videoRectToDisplay(selectedEntry.redaction.rect), {
      selected: true,
      editing: state.editingRedactionId === selectedEntry.key,
    });
  }

  if (state.draft.rectDisplay) {
    const rect = state.draft.rectDisplay;
    drawBlurPreview(rect);
    ctx.save();
    ctx.fillStyle = "rgba(255, 216, 107, 0.22)";
    ctx.strokeStyle = "rgba(255, 216, 107, 0.98)";
    ctx.lineWidth = 3;
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
    ctx.restore();
  }

  updateDraftStatus();
}

function isFrameInRedaction(time, redaction) {
  const start = Number(redaction.effective_start_seconds ?? redaction.selected_start_seconds ?? 0);
  const end = Number(redaction.effective_end_seconds ?? redaction.selected_end_seconds ?? start);
  return time >= start && time <= end;
}

function canvasPoint(event) {
  const rect = els.canvas.getBoundingClientRect();
  const x = ((event.clientX - rect.left) * els.canvas.width) / rect.width;
  const y = ((event.clientY - rect.top) * els.canvas.height) / rect.height;
  return {
    x: clamp(x, 0, els.canvas.width),
    y: clamp(y, 0, els.canvas.height),
  };
}

function normalizeDisplayRect(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const w = Math.abs(a.x - b.x);
  const h = Math.abs(a.y - b.y);
  return { x, y, w, h };
}

function displayRectToVideo(rect) {
  const sx = Number(state.video.width || els.canvas.width) / els.canvas.width;
  const sy = Number(state.video.height || els.canvas.height) / els.canvas.height;
  const x = Math.round(rect.x * sx);
  const y = Math.round(rect.y * sy);
  const w = Math.round(rect.w * sx);
  const h = Math.round(rect.h * sy);
  const videoW = Number(state.video.width || x + w);
  const videoH = Number(state.video.height || y + h);
  return {
    x: clamp(x, 0, Math.max(0, videoW - 1)),
    y: clamp(y, 0, Math.max(0, videoH - 1)),
    w: clamp(w, 1, videoW - x),
    h: clamp(h, 1, videoH - y),
  };
}

function videoRectToDisplay(rect) {
  const sx = els.canvas.width / Number(state.video.width || els.canvas.width);
  const sy = els.canvas.height / Number(state.video.height || els.canvas.height);
  return {
    x: Number(rect.x || 0) * sx,
    y: Number(rect.y || 0) * sy,
    w: Number(rect.w || 0) * sx,
    h: Number(rect.h || 0) * sy,
  };
}

function thumbOverlayStyle(rect) {
  const videoW = Number(state.video.width || 1);
  const videoH = Number(state.video.height || 1);
  return {
    left: `${clamp((Number(rect.x || 0) / videoW) * 100, 0, 100)}%`,
    top: `${clamp((Number(rect.y || 0) / videoH) * 100, 0, 100)}%`,
    width: `${clamp((Number(rect.w || 0) / videoW) * 100, 0, 100)}%`,
    height: `${clamp((Number(rect.h || 0) / videoH) * 100, 0, 100)}%`,
  };
}

function appendThumbOverlay(layer, rect, kind, index) {
  if (!rect) return;
  const overlay = document.createElement("span");
  overlay.className = `thumb-rect thumb-rect-${kind}`;
  overlay.style.setProperty("--overlay-index", String(index || 0));
  const style = thumbOverlayStyle(rect);
  overlay.style.left = style.left;
  overlay.style.top = style.top;
  overlay.style.width = style.width;
  overlay.style.height = style.height;
  layer.appendChild(overlay);
}

function visibleRedactionEntriesAt(time) {
  return redactions()
    .map((redaction, index) => ({ redaction, index, key: redactionKey(redaction, index) }))
    .filter((entry) => isFrameInRedaction(time, entry.redaction));
}

function pointInRect(point, rect) {
  return point.x >= rect.x && point.x <= rect.x + rect.w && point.y >= rect.y && point.y <= rect.y + rect.h;
}

function visibleRedactionAtPoint(point) {
  const entries = visibleRedactionEntriesAt(currentFrameTimeForCanvas());
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (pointInRect(point, videoRectToDisplay(entry.redaction.rect))) return entry;
  }
  return null;
}

function selectedRedactionEntry() {
  return state.selectedRedactionId ? findRedactionEntry(state.selectedRedactionId) : null;
}

function renderSelectionPanel() {
  els.selectionPanel.innerHTML = "";

  const title = document.createElement("div");
  title.className = "selection-title";
  const details = document.createElement("div");
  details.className = "detail-list";

  const editingEntry = state.editingRedactionId ? findRedactionEntry(state.editingRedactionId) : null;
  const selectedEntry = selectedRedactionEntry();

  if (editingEntry) {
    const info = redactionDisplayInfo(editingEntry.redaction);
    title.textContent = `Editing redaction ${editingEntry.index + 1}`;
    details.appendChild(detailRow("Frames", info.frames));
    details.appendChild(detailRow("Time", info.time));
    details.appendChild(detailRow("Rect", info.rect));
  } else if (hasDraft()) {
    title.textContent = "Draft redaction";
    const current = currentFrame();
    if (state.draft.startSeconds !== null) {
      details.appendChild(detailRow("Start", fmtTime(state.draft.startSeconds)));
    }
    if (current) {
      details.appendChild(detailRow("Current", fmtTime(current.time)));
    }
    if (state.draft.startSeconds !== null && current) {
      details.appendChild(detailRow("Frames", displayFrameRange(state.draft.startSeconds, current.time)));
    }
    if (state.draft.rectVideo) {
      const r = state.draft.rectVideo;
      details.appendChild(detailRow("Rect", `x ${r.x}, y ${r.y}, ${r.w}x${r.h}`));
    } else {
      details.appendChild(detailRow("Rect", "Not drawn"));
    }
  } else if (selectedEntry) {
    const info = redactionDisplayInfo(selectedEntry.redaction);
    title.textContent = `Selected redaction ${selectedEntry.index + 1}`;
    details.appendChild(detailRow("Frames", info.frames));
    details.appendChild(detailRow("Time", info.time));
    details.appendChild(detailRow("Rect", info.rect));
  } else {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No active selection.";
    els.selectionPanel.appendChild(empty);
    return;
  }

  els.selectionPanel.appendChild(title);
  els.selectionPanel.appendChild(details);
}

function selectedRedactionIsVisible() {
  const entry = selectedRedactionEntry();
  return Boolean(entry && isFrameInRedaction(currentFrameTimeForCanvas(), entry.redaction));
}

function editHandlesForRect(rect) {
  const left = rect.x;
  const centerX = rect.x + rect.w / 2;
  const right = rect.x + rect.w;
  const top = rect.y;
  const centerY = rect.y + rect.h / 2;
  const bottom = rect.y + rect.h;
  return [
    { name: "nw", x: left, y: top, cursor: "nwse-resize" },
    { name: "n", x: centerX, y: top, cursor: "ns-resize" },
    { name: "ne", x: right, y: top, cursor: "nesw-resize" },
    { name: "e", x: right, y: centerY, cursor: "ew-resize" },
    { name: "se", x: right, y: bottom, cursor: "nwse-resize" },
    { name: "s", x: centerX, y: bottom, cursor: "ns-resize" },
    { name: "sw", x: left, y: bottom, cursor: "nesw-resize" },
    { name: "w", x: left, y: centerY, cursor: "ew-resize" },
  ];
}

function hitTestSelectedRedaction(point) {
  if (!state.editingRedactionId || !selectedRedactionIsVisible()) return null;
  const entry = selectedRedactionEntry();
  const rect = videoRectToDisplay(entry.redaction.rect);
  const half = EDIT_HANDLE_SIZE / 2;
  for (const handle of editHandlesForRect(rect)) {
    if (Math.abs(point.x - handle.x) <= half && Math.abs(point.y - handle.y) <= half) {
      return { entry, mode: "resize", handle: handle.name, cursor: handle.cursor };
    }
  }
  if (pointInRect(point, rect)) return { entry, mode: "move", handle: null, cursor: "move" };
  return null;
}

function updateCanvasCursor(point = null) {
  if (!state.editingRedactionId || state.redactionEdit) {
    els.canvas.style.cursor = "";
    return;
  }
  const hit = point ? hitTestSelectedRedaction(point) : null;
  els.canvas.style.cursor = hit?.cursor || "";
}

function rectsEqual(a, b) {
  return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
}

function updateRedactionSelectionState() {
  for (const row of els.redactionList.querySelectorAll(".redaction-row")) {
    const selected = row.dataset.redactionId === state.selectedRedactionId;
    const editing = row.dataset.redactionId === state.editingRedactionId;
    row.classList.toggle("selected", selected);
    row.querySelector(".redaction-edit-button")?.classList.toggle("active", editing);
  }
}

function selectedRedactionRow() {
  return Array.from(els.redactionList.querySelectorAll(".redaction-row")).find(
    (row) => row.dataset.redactionId === state.selectedRedactionId,
  );
}

function selectRedaction(key, options = {}) {
  state.selectedRedactionId = key;
  if (state.editingRedactionId && state.editingRedactionId !== key) {
    state.editingRedactionId = null;
    state.redactionEdit = null;
  }
  updateRedactionSelectionState();
  updateFilmstripState();
  drawCanvas();
  updateDraftStatus();
  if (options.scrollRow) {
    selectedRedactionRow()?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function clearRedactionSelection() {
  state.selectedRedactionId = null;
  state.editingRedactionId = null;
  state.redactionEdit = null;
  updateCanvasCursor();
  updateRedactionSelectionState();
  updateFilmstripState();
  drawCanvas();
  updateDraftStatus();
}

function startEditRedaction(key) {
  const entry = findRedactionEntry(key);
  if (!entry) return;
  state.selectedRedactionId = key;
  state.editingRedactionId = key;
  state.redactionEdit = null;
  updateRedactionSelectionState();
  jumpToTime(entry.redaction.selected_start_seconds ?? entry.redaction.effective_start_seconds, { key });
  updateDraftStatus();
}

function stopEditRedaction() {
  state.editingRedactionId = null;
  state.redactionEdit = null;
  updateCanvasCursor();
  updateRedactionSelectionState();
  updateFilmstripState();
  drawCanvas();
  updateDraftStatus();
}

function displayRectFromEdit(point) {
  const edit = state.redactionEdit;
  const start = edit.startRectDisplay;
  const dx = point.x - edit.startPoint.x;
  const dy = point.y - edit.startPoint.y;

  if (edit.mode === "move") {
    return {
      x: clamp(start.x + dx, 0, Math.max(0, els.canvas.width - start.w)),
      y: clamp(start.y + dy, 0, Math.max(0, els.canvas.height - start.h)),
      w: start.w,
      h: start.h,
    };
  }

  let left = start.x;
  let top = start.y;
  let right = start.x + start.w;
  let bottom = start.y + start.h;

  if (edit.handle.includes("w")) {
    left = clamp(start.x + dx, 0, right - MIN_EDIT_RECT_SIZE);
  }
  if (edit.handle.includes("e")) {
    right = clamp(start.x + start.w + dx, left + MIN_EDIT_RECT_SIZE, els.canvas.width);
  }
  if (edit.handle.includes("n")) {
    top = clamp(start.y + dy, 0, bottom - MIN_EDIT_RECT_SIZE);
  }
  if (edit.handle.includes("s")) {
    bottom = clamp(start.y + start.h + dy, top + MIN_EDIT_RECT_SIZE, els.canvas.height);
  }

  return {
    x: left,
    y: top,
    w: right - left,
    h: bottom - top,
  };
}

function updateRedactionEdit(point) {
  if (!state.redactionEdit) return;
  const entry = findRedactionEntry(state.redactionEdit.key);
  if (!entry) return;
  entry.redaction.rect = displayRectToVideo(displayRectFromEdit(point));
  drawCanvas();
  updateFilmstripState();
}

function finishRedactionEdit() {
  if (!state.redactionEdit) return;
  const entry = findRedactionEntry(state.redactionEdit.key);
  if (entry && !rectsEqual(entry.redaction.rect, state.redactionEdit.startRectVideo)) {
    commitRedactionsChange();
  }
  state.redactionEdit = null;
  updateCanvasCursor();
  renderRedactionList();
  updateFilmstripState();
  drawCanvas();
  updateDraftStatus();
}

function setDraftStart() {
  if (state.editingRedactionId) return;
  const frame = currentFrame();
  if (!frame) return;
  state.draft.startSeconds = Number(frame.time);
  updateDraftStatus();
  updateFilmstripState();
}

function updateDraftStatus() {
  const editing = Boolean(state.editingRedactionId);
  els.draftStatus.classList.toggle("edit-active", editing);

  if (editing) {
    const entry = findRedactionEntry(state.editingRedactionId);
    const parts = [];
    if (entry) {
      const redaction = entry.redaction;
      const selectedStart = redaction.selected_start_seconds ?? redaction.effective_start_seconds;
      const selectedEnd = redaction.selected_end_seconds ?? redaction.effective_end_seconds;
      parts.push(`Editing ${entry.index + 1}`);
      parts.push(`Frames ${displayFrameRange(selectedStart, selectedEnd)}`);
    } else {
      parts.push("Editing redaction");
    }

    els.draftStatus.textContent = parts.join(" · ");
    els.draftStatus.classList.add("active");
    els.setStartButton.hidden = true;
    els.saveDraftButton.hidden = true;
    els.clearDraftButton.hidden = false;
    els.clearDraftButton.disabled = false;
    els.clearDraftButton.classList.remove("danger");
    setShortcutButton(els.clearDraftButton, "Done", "Enter", "Enter", "Done editing redaction");
    renderSelectionPanel();
    updateSaveState();
    return;
  }

  if (state.draft.startSeconds === null) {
    els.draftStatus.textContent = state.draft.rectVideo ? "Rectangle drawn · Set start" : "Ready";
  } else if (state.draft.rectVideo) {
    els.draftStatus.textContent = "Draft ready · Choose end frame";
  } else {
    els.draftStatus.textContent = `Start ${fmtTime(state.draft.startSeconds)} · Draw rectangle`;
  }

  const active = hasDraft();
  els.draftStatus.classList.toggle("active", active);
  els.setStartButton.hidden = false;
  els.saveDraftButton.hidden = false;
  els.clearDraftButton.hidden = false;
  els.clearDraftButton.classList.add("danger");
  setShortcutButton(els.clearDraftButton, "Clear", "Esc", "Escape", "Clear draft redaction");
  setShortcutButton(els.saveDraftButton, "Add redaction", "Enter", "Enter");
  setShortcutButton(els.setStartButton, "Set start", "S", "S");
  els.setStartButton.disabled = false;
  els.clearDraftButton.disabled = !active;
  els.saveDraftButton.disabled = !isDraftReady();
  renderSelectionPanel();
  updateSaveState();
}

function clearDraft() {
  state.draft = {
    startSeconds: null,
    rectDisplay: null,
    rectVideo: null,
  };
  drawCanvas();
  updateFilmstripState();
}

function saveDraftAsRedaction() {
  if (state.editingRedactionId) return;
  const frame = currentFrame();
  if (!frame) return;
  if (state.draft.startSeconds === null) {
    alert("Set a start frame first.");
    return;
  }
  if (!state.draft.rectVideo) {
    alert("Draw a rectangle first.");
    return;
  }

  const selectedA = Number(state.draft.startSeconds);
  const selectedB = Number(frame.time);
  let selectedStart = Math.min(selectedA, selectedB);
  let selectedEnd = Math.max(selectedA, selectedB);
  if (selectedEnd <= selectedStart) {
    selectedEnd = selectedStart + Number(state.framesDoc?.interval_seconds || 1.0);
  }

  const duration = Number(state.video.duration || selectedEnd);
  const pre = Number(els.bufferPreInput.value || 0);
  const post = Number(els.bufferPostInput.value || 0);
  const effectiveStart = clamp(selectedStart - pre, 0, duration);
  const effectiveEnd = clamp(selectedEnd + post, effectiveStart + 0.001, duration || selectedEnd + post);
  const radius = selectedBlurRadius();

  const redaction = {
    id: generateRedactionId(),
    selected_start_seconds: Number(selectedStart.toFixed(6)),
    selected_end_seconds: Number(selectedEnd.toFixed(6)),
    buffer_pre_seconds: pre,
    buffer_post_seconds: post,
    effective_start_seconds: Number(effectiveStart.toFixed(6)),
    effective_end_seconds: Number(effectiveEnd.toFixed(6)),
    rect: state.draft.rectVideo,
    style: {
      type: "blur",
      filter: "boxblur",
      luma_radius: radius,
      luma_power: 3,
    },
  };

  state.redactionsDoc.redactions ||= [];
  state.redactionsDoc.redactions.push(redaction);
  state.redactionsDoc.redactions.sort((a, b) => a.effective_start_seconds - b.effective_start_seconds);
  commitRedactionsChange();
  clearDraft();
  renderRedactionList();
  renderFilmstrip();
  updateDraftStatus();
}

function renderRedactionList() {
  const list = redactions();
  els.redactionList.innerHTML = "";
  if (list.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No redactions yet.";
    els.redactionList.appendChild(empty);
    return;
  }

  list.forEach((redaction, index) => {
    const key = redactionKey(redaction, index);
    const row = document.createElement("div");
    row.className = "redaction-row";
    row.dataset.redactionId = key;

    const header = document.createElement("div");
    header.className = "redaction-row-content";

    const title = document.createElement("strong");
    title.className = "redaction-index";
    title.textContent = String(index + 1);

    const r = redaction.rect || {};
    const timeRange = `${fmtTime(redaction.effective_start_seconds)} → ${fmtTime(redaction.effective_end_seconds)}`;
    const selectedFrameRange = displayFrameRange(
      redaction.selected_start_seconds ?? redaction.effective_start_seconds,
      redaction.selected_end_seconds ?? redaction.effective_end_seconds,
    );
    const effectiveFrameRange = displayFrameRange(redaction.effective_start_seconds, redaction.effective_end_seconds);
    const geometry = `x ${r.x}, y ${r.y}, ${r.w}×${r.h}`;

    const frames = document.createElement("span");
    frames.className = "redaction-frames";
    frames.innerHTML = iconSvg("frame");
    frames.append(document.createTextNode(selectedFrameRange));

    const time = document.createElement("span");
    time.className = "redaction-time";
    time.textContent = timeRange;

    row.title = `${selectedFrameRange} selected · ${effectiveFrameRange} effective · ${timeRange} · ${geometry}`;
    row.setAttribute(
      "aria-label",
      `Redaction ${index + 1}: ${selectedFrameRange} selected, ${timeRange}, ${geometry}`,
    );

    const actions = document.createElement("div");
    actions.className = "redaction-row-actions";

    const edit = makeIconButton("edit", "Edit redaction", "redaction-edit-button");
    edit.addEventListener("click", (event) => {
      event.stopPropagation();
      if (state.editingRedactionId === key) {
        stopEditRedaction();
      } else {
        startEditRedaction(key);
      }
    });

    const jump = makeIconButton("jump", "Jump to redaction");
    jump.addEventListener("click", (event) => {
      event.stopPropagation();
      selectRedaction(key);
      jumpToTime(redaction.selected_start_seconds, { key });
    });

    const remove = makeIconButton("trash", "Delete redaction", "danger");
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteRedaction(index);
    });

    row.addEventListener("click", () => selectRedaction(key));
    actions.appendChild(edit);
    actions.appendChild(jump);
    actions.appendChild(remove);
    header.appendChild(title);
    header.appendChild(frames);
    header.appendChild(time);
    header.appendChild(actions);
    row.appendChild(header);
    els.redactionList.appendChild(row);
  });
  updateRedactionSelectionState();
}

function jumpToTime(seconds, options = {}) {
  if (options.key) {
    state.selectedRedactionId = options.key;
    updateRedactionSelectionState();
  }
  const bestIndex = nearestFrameIndexForTime(seconds) ?? 0;
  selectFrame(bestIndex, { scrollAlign: "center" });
}

function deleteRedaction(index) {
  const deletedKey = redactionKey(state.redactionsDoc.redactions[index], index);
  state.redactionsDoc.redactions.splice(index, 1);
  if (state.selectedRedactionId === deletedKey) state.selectedRedactionId = null;
  if (state.editingRedactionId === deletedKey) {
    state.editingRedactionId = null;
    state.redactionEdit = null;
  }
  commitRedactionsChange();
  renderRedactionList();
  renderFilmstrip();
  drawCanvas();
  updateDraftStatus();
}

async function saveRedactions() {
  if (!state.dirty && !state.saveQueued) {
    updateSaveState();
    return;
  }
  if (state.saveInFlight) {
    state.saveQueued = true;
    updateSaveState();
    return;
  }

  state.saveInFlight = true;
  state.saveQueued = false;
  const saveVersion = state.saveVersion;
  const body = JSON.stringify(state.redactionsDoc);
  updateSaveState("saving");
  try {
    const response = await fetch("/api/redactions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Save failed: ${response.status}`);
    }
    state.saveInFlight = false;
    if (saveVersion === state.saveVersion) {
      markClean();
    } else {
      state.dirty = true;
      state.saveState = "dirty";
      updateSaveState();
    }
    updateDraftStatus();
    if (state.saveQueued || saveVersion !== state.saveVersion) {
      state.saveQueued = false;
      await saveRedactions();
    }
  } catch (error) {
    state.saveInFlight = false;
    state.saveQueued = false;
    state.dirty = true;
    state.saveError = error instanceof Error ? error.message : String(error);
    state.saveState = "error";
    updateSaveState();
    throw error;
  }
}

function finishFilmstripDrag(pointerId) {
  const drag = state.filmstripDrag;
  if (drag.pointerId !== pointerId) return;
  const shouldSuppressClick = drag.dragging;
  drag.pointerId = null;
  drag.dragging = false;
  els.filmstrip.classList.remove("is-dragging");
  updateFilmstripScrollButtons();
  if (shouldSuppressClick) {
    drag.suppressClickUntil = performance.now() + 150;
  }
}

els.canvas.addEventListener("mousedown", (event) => {
  if (!state.image) return;
  const point = canvasPoint(event);
  const editHit = hitTestSelectedRedaction(point);
  if (editHit) {
    state.redactionEdit = {
      key: editHit.entry.key,
      mode: editHit.mode,
      handle: editHit.handle,
      startPoint: point,
      startRectVideo: { ...editHit.entry.redaction.rect },
      startRectDisplay: videoRectToDisplay(editHit.entry.redaction.rect),
    };
    return;
  }
  if (state.editingRedactionId) return;

  const hitRedaction = visibleRedactionAtPoint(point);
  if (hitRedaction) {
    selectRedaction(hitRedaction.key, { scrollRow: true });
    return;
  }

  clearRedactionSelection();
  state.dragging = true;
  state.dragStart = point;
  state.draft.rectDisplay = { x: state.dragStart.x, y: state.dragStart.y, w: 1, h: 1 };
  state.draft.rectVideo = null;
  drawCanvas();
  updateFilmstripState();
});

els.canvas.addEventListener("mousemove", (event) => {
  const point = canvasPoint(event);
  if (state.redactionEdit) {
    updateRedactionEdit(point);
    return;
  }
  if (!state.dragging || !state.dragStart) return;
  state.draft.rectDisplay = normalizeDisplayRect(state.dragStart, point);
  drawCanvas();
});

els.canvas.addEventListener("mouseleave", () => updateCanvasCursor());

els.canvas.addEventListener("mousemove", (event) => {
  if (state.dragging || state.redactionEdit) return;
  updateCanvasCursor(canvasPoint(event));
});

window.addEventListener("mouseup", () => {
  if (state.redactionEdit) {
    finishRedactionEdit();
    return;
  }
  if (!state.dragging) return;
  state.dragging = false;
  if (state.draft.rectDisplay && state.draft.rectDisplay.w > 2 && state.draft.rectDisplay.h > 2) {
    state.draft.rectVideo = displayRectToVideo(state.draft.rectDisplay);
  }
  drawCanvas();
  updateFilmstripState();
});

els.setStartButton.addEventListener("click", setDraftStart);
els.saveDraftButton.addEventListener("click", saveDraftAsRedaction);
els.clearDraftButton.addEventListener("click", () => {
  if (state.editingRedactionId) {
    stopEditRedaction();
  } else {
    clearDraft();
  }
});
els.saveButton.addEventListener("click", () => saveRedactions().catch(() => {}));
for (const button of els.blurOptions) {
  button.addEventListener("click", () => setBlurLevel(button.dataset.blurLevel));
}

els.filmstripScrollLeftButton.addEventListener("click", () => scrollFilmstripByPage(-1));
els.filmstripScrollRightButton.addEventListener("click", () => scrollFilmstripByPage(1));
els.filmstrip.addEventListener("scroll", updateFilmstripScrollButtons);
window.addEventListener("resize", updateFilmstripScrollButtons);

els.filmstrip.addEventListener(
  "wheel",
  (event) => {
    if (!canScrollFilmstrip()) return;
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    if (delta === 0) return;
    const before = els.filmstrip.scrollLeft;
    els.filmstrip.scrollLeft += delta;
    if (els.filmstrip.scrollLeft !== before) {
      event.preventDefault();
      updateFilmstripScrollButtons();
    }
  },
  { passive: false },
);

els.filmstrip.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || !canScrollFilmstrip()) return;
  state.filmstripDrag.pointerId = event.pointerId;
  state.filmstripDrag.startX = event.clientX;
  state.filmstripDrag.startScrollLeft = els.filmstrip.scrollLeft;
  state.filmstripDrag.dragging = false;
});

window.addEventListener("pointermove", (event) => {
  const drag = state.filmstripDrag;
  if (drag.pointerId !== event.pointerId) return;
  const deltaX = event.clientX - drag.startX;
  if (!drag.dragging && Math.abs(deltaX) < 6) return;
  drag.dragging = true;
  els.filmstrip.classList.add("is-dragging");
  els.filmstrip.scrollLeft = drag.startScrollLeft - deltaX;
  event.preventDefault();
  updateFilmstripScrollButtons();
});

window.addEventListener("pointerup", (event) => finishFilmstripDrag(event.pointerId));
window.addEventListener("pointercancel", (event) => finishFilmstripDrag(event.pointerId));

els.filmstrip.addEventListener(
  "click",
  (event) => {
    if (performance.now() > state.filmstripDrag.suppressClickUntil) return;
    event.preventDefault();
    event.stopPropagation();
    state.filmstripDrag.suppressClickUntil = 0;
  },
  true,
);

window.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement) {
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    selectFrame(state.currentIndex - 1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    selectFrame(state.currentIndex + 1);
  } else if (event.key === "Home") {
    event.preventDefault();
    selectFrame(0, { scrollAlign: "center" });
  } else if (event.key === "End") {
    event.preventDefault();
    selectFrame(state.frames.length - 1, { scrollAlign: "center" });
  } else if (event.key.toLowerCase() === "s") {
    event.preventDefault();
    setDraftStart();
  } else if (event.key === "Enter") {
    event.preventDefault();
    if (state.editingRedactionId) {
      stopEditRedaction();
    } else {
      saveDraftAsRedaction();
    }
  } else if (event.key === "Escape") {
    event.preventDefault();
    if (state.editingRedactionId) {
      stopEditRedaction();
    } else {
      clearDraft();
    }
  }
});

window.addEventListener("beforeunload", (event) => {
  if (!state.dirty && !state.saveInFlight) return;
  event.preventDefault();
  event.returnValue = "";
});

loadProject().catch((error) => {
  els.projectMeta.textContent = error.message;
  els.draftStatus.textContent = "Could not load project.";
});
