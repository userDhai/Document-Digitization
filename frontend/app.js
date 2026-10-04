const form = document.querySelector("#upload-form");
const input = document.querySelector("#file-input");
const drop = document.querySelector("#drop-zone");
const fileRow = document.querySelector("#file-row");
const processButton = document.querySelector("#process-button");
const progress = document.querySelector("#progress");
const message = document.querySelector("#message");
const reviewCard = document.querySelector("#review-card");
const resultJson = document.querySelector("#result-json");
const findings = document.querySelector("#findings");
const exportButton = document.querySelector("#export-button");
let selectedFile;
let jobId;

function chooseFile(file) {
  if (!file) return;
  selectedFile = file;
  fileRow.hidden = false;
  fileRow.innerHTML = `<span>▧</span><strong>${escapeHtml(file.name)}</strong><small>${(file.size / 1024 / 1024).toFixed(2)} MB</small><button type="button" aria-label="Remove file">×</button>`;
  fileRow.querySelector("button").onclick = () => { selectedFile = null; input.value = ""; fileRow.hidden = true; };
}

function escapeHtml(value) { return value.replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
input.addEventListener("change", () => chooseFile(input.files[0]));
for (const event of ["dragenter", "dragover"]) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.add("dragging"); });
for (const event of ["dragleave", "drop"]) drop.addEventListener(event, e => { e.preventDefault(); drop.classList.remove("dragging"); });
drop.addEventListener("drop", e => chooseFile(e.dataTransfer.files[0]));

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedFile) return;
  processButton.disabled = true; progress.hidden = false; message.hidden = true; reviewCard.hidden = true;
  const body = new FormData(); body.append("file", selectedFile);
  try {
    const response = await fetch("/api/process", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Processing failed.");
    jobId = data.job_id;
    renderReview(data);
    reviewCard.hidden = false;
    reviewCard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    message.textContent = error.message; message.hidden = false;
  } finally { progress.hidden = true; processButton.disabled = false; }
});

function renderReview(data) {
  const review = data.review;
  resultJson.value = JSON.stringify(review.result, null, 2);
  findings.innerHTML = review.findings.length
    ? `<h3>Masked before AI <span>${review.findings.length}</span></h3>${review.findings.map(item => `<div class="finding"><span class="tag">${escapeHtml(item.category)}</span><code>${escapeHtml(item.token)}</code><small>${escapeHtml(item.masked_value)}</small></div>`).join("")}`
    : `<div class="no-findings">No sensitive patterns detected. Visual OCR may miss handwriting or low quality scans.</div>`;
  const previews = document.querySelector("#previews");
  previews.innerHTML = review.redacted_previews.map(url => `<img src="${url}" alt="Locally redacted document page">`).join("");
  document.querySelector("#preview-wrap").hidden = !review.redacted_previews.length;
  document.querySelector("#review-state").textContent = "Needs approval";
  exportButton.disabled = true;
}

async function reviewAction(action) {
  try {
    const body = { action };
    if (action === "approve") body.result = JSON.parse(resultJson.value);
    const response = await fetch(`/api/review/${jobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not save review.");
    document.querySelector("#review-state").textContent = action === "approve" ? "Approved" : "Rejected";
    exportButton.disabled = action !== "approve";
    document.querySelector("#approve-button").disabled = action !== "approve";
    document.querySelector("#reject-button").disabled = true;
  } catch (error) { message.textContent = error instanceof SyntaxError ? "The extracted data must be valid JSON before approval." : error.message; message.hidden = false; }
}
document.querySelector("#approve-button").addEventListener("click", () => reviewAction("approve"));
document.querySelector("#reject-button").addEventListener("click", () => reviewAction("reject"));
exportButton.addEventListener("click", () => { window.location.href = `/api/export/${jobId}`; });
