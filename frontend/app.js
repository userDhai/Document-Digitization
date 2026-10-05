const form = document.querySelector("#upload-form");
const input = document.querySelector("#file-input");
const drop = document.querySelector("#drop-zone");
const fileRow = document.querySelector("#file-row");
const processButton = document.querySelector("#process-button");
const message = document.querySelector("#message");
const progress = document.querySelector("#progress");
const localReview = document.querySelector("#local-review");
const aiReview = document.querySelector("#ai-review");
const aiProgress = document.querySelector("#ai-progress");
const completion = document.querySelector("#completion");
const fieldsBody = document.querySelector("#fields-body");
const previewContainer = document.querySelector("#previews");
const maskInstruction = document.querySelector("#mask-instruction");
let selectedFile = null;
let jobId = null;
let currentDocument = null;
let finalApproved = false;
let maskMode = false;
let selectedMaskIndex = -1;
let maskBusy = false;

function setMessage(text, kind = "error") {
  message.textContent = text;
  message.className = `message ${kind}`;
  message.hidden = !text;
}

function setStep(active) {
  document.querySelectorAll("#step-list li").forEach((item, index) => {
    item.classList.toggle("complete", index < active);
    item.classList.toggle("active", index === active);
  });
}

async function readResponse(response) {
  let data;
  try { data = await response.json(); }
  catch { throw new Error("The server returned an unreadable response. Please try again."); }
  if (!response.ok) {
    const error = new Error(data.error || "The request could not be completed.");
    error.data = data;
    throw error;
  }
  return data;
}

function chooseFile(file) {
  if (!file) return;
  selectedFile = file;
  fileRow.hidden = false;
  fileRow.innerHTML = `<span aria-hidden="true">▧</span><strong>${escapeHtml(file.name)}</strong><small>${(file.size / 1024 / 1024).toFixed(2)} MB</small><button type="button" aria-label="Remove file">×</button>`;
  fileRow.querySelector("button").onclick = () => { selectedFile = null; input.value = ""; fileRow.hidden = true; };
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

input.addEventListener("change", () => chooseFile(input.files[0]));
for (const event of ["dragenter", "dragover"]) drop.addEventListener(event, eventObject => {
  eventObject.preventDefault(); drop.classList.add("dragging");
});
for (const event of ["dragleave", "drop"]) drop.addEventListener(event, eventObject => {
  eventObject.preventDefault(); drop.classList.remove("dragging");
});
drop.addEventListener("drop", event => chooseFile(event.dataTransfer.files[0]));

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedFile) return;
  processButton.disabled = true;
  finalApproved = false;
  document.querySelector("#approve-export-button").textContent = "Approve & export Excel ↓";
  progress.hidden = false;
  document.querySelector("#progress-text").textContent = "Running local OCR, PII detection, redaction, and verification…";
  setStep(1); setMessage("");
  localReview.hidden = true; aiReview.hidden = true; completion.hidden = true;
  try {
    const body = new FormData(); body.append("file", selectedFile);
    const response = await fetch("/api/process", { method: "POST", body });
    let data;
    try { data = await response.json(); }
    catch { throw new Error("Upload or local processing failed. Please try another file."); }
    if (data.job_id) jobId = data.job_id;
    if (!response.ok && !data.job_id) throw new Error(data.error || "Upload failed.");
    currentDocument = data;
    renderLocal(data);
    localReview.hidden = false;
    localReview.scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(data.privacy_verified ? 3 : 2);
    if (!response.ok) setMessage(data.error || "Privacy verification failed. The document was not sent to external AI.");
  } catch (error) {
    setMessage(error.message || "Local processing failed.");
  } finally {
    progress.hidden = true;
    processButton.disabled = false;
  }
});

function renderMetadata(metadata = {}) {
  const entries = [
    ["File name", metadata.file_name || "—"],
    ["File type", metadata.file_type || "—"],
    ["Pages", metadata.page_count ?? "—"],
    ["Processing", metadata.processing_status || "—"],
    ["OCR", metadata.ocr_status || "—"],
    ["Sensitive fields", metadata.sensitive_field_count ?? 0],
  ];
  document.querySelector("#metadata-grid").innerHTML = entries.map(([label, value]) =>
    `<div class="metadata-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function renderLocal(data) {
  const metadata = data.metadata || {};
  const passed = data.privacy_verified === true && metadata.privacy_status === "PASSED";
  renderMetadata(metadata);
  const badge = document.querySelector("#privacy-status");
  badge.textContent = `Privacy Verification: ${passed ? "PASSED" : "BLOCKED"}`;
  badge.className = `status-pill ${passed ? "passed" : "blocked"}`;
  document.querySelector("#privacy-banner").textContent = passed
    ? `${(metadata.sensitive_field_count || 0)} sensitive value(s) tokenized · ${escapeHtml((metadata.sensitive_field_types || []).join(", ") || "No patterns detected")}. The original document stays local.`
    : data.error || "Privacy verification failed. The document was not sent to external AI.";
  previewContainer.replaceChildren();
  maskMode = false;
  document.querySelector("#add-mask-button").textContent = "Add Mask";
  selectedMaskIndex = -1;
  const masks = data.manual_masks || [];
  (data.redacted_previews || []).forEach((url, index) => {
    const figure = document.createElement("figure");
    const canvas = document.createElement("canvas");
    canvas.className = "mask-canvas";
    canvas.dataset.page = String(index);
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `Privacy-sanitized page ${index + 1}; use Add Mask to redact an area`);
    const image = new Image();
    canvas.previewImage = image;
    image.onload = () => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      redrawCanvas(canvas, image, index, masks, null);
    };
    image.src = url;
    bindMaskCanvas(canvas, image, index);
    const caption = document.createElement("figcaption"); caption.textContent = `Page ${index + 1}`;
    figure.append(canvas, caption); previewContainer.append(figure);
  });
  const findings = document.querySelector("#findings");
  findings.innerHTML = (data.findings || []).length
    ? `<h3>Locally masked values</h3>${data.findings.map(item => `<span class="finding-chip"><b>${escapeHtml(item.category)}</b><code>${escapeHtml(item.token)}</code></span>`).join("")}`
    : `<p class="quiet-note">No sensitive patterns were detected. Review the preview carefully; low-quality scans and handwriting may be missed.</p>`;
  const canSend = passed && data.visual_verified === true && data.status === "awaiting_ai_approval";
  const maskCount = masks.length;
  document.querySelector("#mask-count").textContent = `Manual Masks: ${maskCount}`;
  document.querySelector("#add-mask-button").hidden = !canSend;
  document.querySelector("#add-mask-button").disabled = maskBusy || !canSend;
  document.querySelector("#add-mask-button").setAttribute("aria-pressed", "false");
  document.querySelector("#undo-mask-button").disabled = maskBusy || maskCount === 0 || !canSend;
  document.querySelector("#remove-mask-button").disabled = maskBusy || selectedMaskIndex < 0 || !canSend;
  document.querySelector("#clear-masks-button").disabled = maskBusy || maskCount === 0 || !canSend;
  document.querySelector(".mask-toolbar").hidden = !canSend;
  maskInstruction.textContent = maskMode ? "Click and drag over sensitive information. The selection will be redacted locally." :
    (maskBusy ? "Updating the sanitized OCR and preview locally…" : "Review the sanitized pages. Add masks for sensitive areas OCR may have missed.");
  document.querySelector("#send-ai-button").disabled = !canSend || maskBusy;
  document.querySelector("#send-ai-button").hidden = !canSend;
  document.querySelector("#reject-local-button").hidden = !canSend;
  document.querySelector("#retry-button").hidden = !["rejected", "ai_failed"].includes(data.status);
  document.querySelector("#pre-ai-instruction").hidden = !canSend;
}

function redrawCanvas(canvas, image, page, masks, draft) {
  if (!canvas.width || !canvas.height || !image.complete) return;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  masks.forEach((mask, index) => {
    if (mask.page !== page) return;
    context.fillStyle = "#000";
    context.fillRect(mask.x, mask.y, mask.width, mask.height);
    if (index === selectedMaskIndex) {
      context.strokeStyle = "#f1c75b"; context.lineWidth = Math.max(2, canvas.width / 500);
      context.strokeRect(mask.x, mask.y, mask.width, mask.height);
    }
  });
  if (draft) {
    context.strokeStyle = "#d65742"; context.lineWidth = Math.max(2, canvas.width / 500);
    context.setLineDash([8, 5]); context.strokeRect(draft.x, draft.y, draft.width, draft.height);
    context.setLineDash([]);
  }
  canvas.classList.toggle("is-active", maskMode);
  canvas.classList.toggle("is-busy", maskBusy);
}

function canvasPoint(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width, (event.clientX - rect.left) * canvas.width / rect.width)),
    y: Math.max(0, Math.min(canvas.height, (event.clientY - rect.top) * canvas.height / rect.height)),
  };
}

function bindMaskCanvas(canvas, image, page) {
  let start = null;
  let draft = null;
  canvas.addEventListener("pointerdown", event => {
    if (maskBusy || !canvas.width) return;
    const point = canvasPoint(event, canvas);
    if (!maskMode) {
      const masks = currentDocument?.manual_masks || [];
      selectedMaskIndex = -1;
      for (let index = masks.length - 1; index >= 0; index--) {
        const mask = masks[index];
        if (mask.page === page && point.x >= mask.x && point.x <= mask.x + mask.width &&
            point.y >= mask.y && point.y <= mask.y + mask.height) { selectedMaskIndex = index; break; }
      }
      redrawCanvas(canvas, image, page, masks, null);
      document.querySelector("#remove-mask-button").disabled = selectedMaskIndex < 0;
      return;
    }
    event.preventDefault();
    start = point; draft = { x: point.x, y: point.y, width: 0, height: 0 };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!start) return;
    const point = canvasPoint(event, canvas);
    draft = { x: Math.min(start.x, point.x), y: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x), height: Math.abs(point.y - start.y) };
    redrawCanvas(canvas, image, page, currentDocument?.manual_masks || [], draft);
  });
  const finish = event => {
    if (!start) return;
    const point = canvasPoint(event, canvas);
    const mask = { page, x: Math.round(Math.min(start.x, point.x)), y: Math.round(Math.min(start.y, point.y)),
      width: Math.round(Math.abs(point.x - start.x)), height: Math.round(Math.abs(point.y - start.y)) };
    start = null; draft = null;
    redrawCanvas(canvas, image, page, currentDocument?.manual_masks || [], null);
    if (mask.width > 2 && mask.height > 2) {
      const candidate = [...(currentDocument?.manual_masks || []), mask];
      redrawCanvas(canvas, image, page, candidate, null);
      persistManualMasks(candidate);
    }
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

async function persistManualMasks(masks) {
  if (!jobId || maskBusy) return;
  maskBusy = true;
  document.querySelector("#send-ai-button").disabled = true;
  document.querySelector("#add-mask-button").disabled = true;
  document.querySelector("#mask-instruction").textContent = "Updating the sanitized OCR and preview locally…";
  previewContainer.querySelectorAll("canvas").forEach(canvas => canvas.classList.add("is-busy"));
  try {
    const response = await fetch(`/api/manual-masks/${jobId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ masks }),
    });
    const data = await readResponse(response);
    currentDocument = data; selectedMaskIndex = -1;
    setMessage("Mask added and applied to the local sanitized document.", "notice");
  } catch (error) {
    setMessage(error.message);
  } finally {
    maskBusy = false;
    renderLocal(currentDocument);
  }
}

function redrawCandidateMasks(masks) {
  previewContainer.querySelectorAll("canvas").forEach(canvas => {
    redrawCanvas(canvas, canvas.previewImage, Number(canvas.dataset.page), masks, null);
  });
  document.querySelector("#mask-count").textContent = `Manual Masks: ${masks.length}`;
}

document.querySelector("#add-mask-button").addEventListener("click", event => {
  maskMode = !maskMode;
  event.currentTarget.textContent = maskMode ? "Cancel Mask" : "Add Mask";
  event.currentTarget.setAttribute("aria-pressed", String(maskMode));
  maskInstruction.textContent = maskMode ? "Click and drag over sensitive information." :
    "Review the sanitized pages. Add masks for sensitive areas OCR may have missed.";
  previewContainer.querySelectorAll("canvas").forEach(canvas => {
    canvas.classList.toggle("is-active", maskMode);
  });
});
document.querySelector("#undo-mask-button").addEventListener("click", () => {
  const masks = [...(currentDocument?.manual_masks || [])]; masks.pop(); selectedMaskIndex = -1;
  redrawCandidateMasks(masks); persistManualMasks(masks);
});
document.querySelector("#remove-mask-button").addEventListener("click", () => {
  const masks = [...(currentDocument?.manual_masks || [])];
  if (selectedMaskIndex >= 0) masks.splice(selectedMaskIndex, 1);
  selectedMaskIndex = -1; redrawCandidateMasks(masks); persistManualMasks(masks);
});
document.querySelector("#clear-masks-button").addEventListener("click", () => {
  selectedMaskIndex = -1; redrawCandidateMasks([]); persistManualMasks([]);
});

async function postReview(action, result) {
  const response = await fetch(`/api/review/${jobId}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...(result ? { result } : {}) }),
  });
  return readResponse(response);
}

document.querySelector("#reject-local-button").addEventListener("click", async () => {
  try {
    const data = await postReview("reject");
    currentDocument = data; renderLocal(data);
    document.querySelector("#retry-button").hidden = false;
    setMessage("Document rejected. Local review data is retained; return to review whenever you are ready.", "notice");
  } catch (error) { setMessage(error.message); }
});

document.querySelector("#retry-button").addEventListener("click", async () => {
  try {
    const data = await postReview("retry");
    currentDocument = data; renderLocal(data); setMessage(""); setStep(3);
  } catch (error) { setMessage(error.message); }
});

document.querySelector("#send-ai-button").addEventListener("click", async () => {
  if (!jobId || !currentDocument?.privacy_verified || currentDocument?.metadata?.privacy_status !== "PASSED") {
    setMessage("Privacy verification failed. The document was not sent to external AI."); return;
  }
  const button = document.querySelector("#send-ai-button");
  button.disabled = true; aiProgress.hidden = false; setMessage(""); setStep(4);
  try {
    const response = await fetch(`/api/ai/${jobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const data = await readResponse(response);
    currentDocument = data;
    localReview.hidden = true;
    setMessage("");
    renderAiReview(data);
    aiReview.hidden = false;
    aiReview.scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(6);
  } catch (error) {
    if (!error.data && jobId) {
      try {
        const latest = await readResponse(await fetch(`/api/review/${jobId}`));
        if (latest.status === "awaiting_final_approval") {
          currentDocument = latest; localReview.hidden = true; renderAiReview(latest);
          aiReview.hidden = false; setStep(6);
          setMessage("AI processing completed. The connection interrupted the response; review the result below.", "notice");
          return;
        }
      } catch {}
    }
    if (error.data?.status === "blocked") {
      currentDocument = { ...currentDocument, ...error.data, privacy_verified: false,
        metadata: { ...currentDocument.metadata, privacy_status: "BLOCKED", processing_status: "BLOCKED" } };
      renderLocal(currentDocument);
    } else if (error.data?.status === "ai_failed") {
      currentDocument.status = "ai_failed";
      currentDocument.metadata.processing_status = "AI_FAILED";
      renderLocal(currentDocument); setStep(3);
      document.querySelector("#retry-button").hidden = false;
    }
    setMessage(error.message);
  } finally { aiProgress.hidden = true; }
});

function normalizeFields(fields) {
  if (Array.isArray(fields)) {
    return Object.fromEntries(fields.map((item, index) => [
      String(item?.label || `field_${index + 1}`), item?.value ?? "",
    ]));
  }
  return fields && typeof fields === "object" ? fields : {};
}

function renderAiReview(data) {
  finalApproved = false;
  document.querySelector("#approve-export-button").textContent = "Approve & export Excel ↓";
  document.querySelector("#safe-ocr-text").textContent = data.safe_ocr_text || "No OCR text was returned.";
  document.querySelector("#safe-payload").textContent = data.sanitized_payload || "No sanitized payload was returned.";
  const result = data.ai_result || {};
  document.querySelector("#document-type").value = result.document_type ?? "";
  document.querySelector("#summary").value = typeof result.summary === "string" ? result.summary : JSON.stringify(result.summary ?? "", null, 2);
  fieldsBody.replaceChildren();
  const fields = normalizeFields(result.fields);
  Object.entries(fields).forEach(([key, value]) => addFieldRow(key, value));
  if (!Object.keys(fields).length) {
    addFieldRow("", "");
    setMessage("The AI returned no fields. Add or correct fields before final approval.", "notice");
  }
}

function addFieldRow(key = "", value = "") {
  const row = document.createElement("tr");
  row.innerHTML = `<td><input class="field-key" aria-label="Field name"></td><td><textarea class="field-value" rows="2" aria-label="Field value"></textarea></td><td><button type="button" class="remove-field" aria-label="Remove field">×</button></td>`;
  row.querySelector(".field-key").value = key;
  row.querySelector(".field-value").value = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  row.querySelector(".remove-field").addEventListener("click", () => row.remove());
  fieldsBody.append(row);
}

document.querySelector("#add-field-button").addEventListener("click", () => addFieldRow());

function collectResult() {
  const fields = Object.create(null);
  for (const row of fieldsBody.rows) {
    const key = row.querySelector(".field-key").value.trim();
    const text = row.querySelector(".field-value").value;
    if (!key) throw new Error("Each field needs a name, or remove the empty row.");
    if (Object.hasOwn(fields, key)) throw new Error(`Field “${key}” appears more than once.`);
    let value = text;
    const trimmed = text.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try { value = JSON.parse(trimmed); }
      catch { throw new Error(`The value for “${key}” must contain valid JSON or plain text.`); }
    }
    fields[key] = value;
  }
  return {
    document_type: document.querySelector("#document-type").value.trim(),
    summary: document.querySelector("#summary").value,
    fields,
  };
}

async function downloadApprovedExcel() {
  const response = await fetch(`/api/export/${jobId}`);
  if (!response.ok) {
    let data = {};
    try { data = await response.json(); } catch {}
    throw new Error(data.error || "Excel export failed. Please try again.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = "digitized-document.xlsx";
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.querySelector("#approve-export-button").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true; setMessage("");
  try {
    if (!finalApproved) {
      let result;
      try { result = collectResult(); }
      catch (error) { throw error; }
      const approved = await postReview("approve", result);
      if (approved.status !== "approved") throw new Error("The final approval was not recorded.");
      finalApproved = true;
      button.textContent = "Download approved Excel";
    }
    await downloadApprovedExcel();
    aiReview.hidden = true; completion.hidden = false; completion.scrollIntoView({ behavior: "smooth" }); setStep(8);
    setMessage("");
  } catch (error) {
    setMessage(finalApproved ? `${error.message} Your approval is saved; retry the download.` : error.message);
    if (finalApproved) button.textContent = "Retry Excel export";
  } finally { button.disabled = false; }
});

document.querySelector("#reject-result-button").addEventListener("click", async () => {
  try {
    const data = await postReview("reject");
    currentDocument = data; renderLocal(data);
    aiReview.hidden = true; localReview.hidden = false;
    document.querySelector("#retry-button").hidden = false;
    setStep(3); setMessage("Extraction rejected. The local review data is retained; you can review and retry.", "notice");
  } catch (error) { setMessage(error.message); }
});

document.querySelector("#download-again-button").addEventListener("click", async () => {
  try { await downloadApprovedExcel(); setMessage(""); }
  catch (error) { setMessage(error.message); }
});
