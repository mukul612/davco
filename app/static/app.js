(() => {
  "use strict";

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const browseBtn = document.getElementById("browse-btn");
  const fileNameEl = document.getElementById("file-name");
  const generateBtn = document.getElementById("generate-btn");
  const formError = document.getElementById("form-error");

  const statusSection = document.getElementById("status-section");
  const statusText = document.getElementById("status-text");

  const resultsSection = document.getElementById("results-section");
  const failedSection = document.getElementById("failed-section");
  const failedText = document.getElementById("failed-text");

  const reviewBanner = document.getElementById("review-banner");
  const reviewCountText = document.getElementById("review-count-text");
  const summaryTable = document.querySelector("#summary-table tbody");
  const warningsBlock = document.getElementById("warnings-block");
  const warningsList = document.getElementById("warnings-list");

  let selectedFile = null;
  let currentJobId = null;
  let pollHandle = null;

  function resetToForm() {
    selectedFile = null;
    currentJobId = null;
    if (pollHandle) { clearTimeout(pollHandle); pollHandle = null; }
    fileInput.value = "";
    fileNameEl.hidden = true;
    document.querySelectorAll('input[name="layout_type"]').forEach((r) => (r.checked = false));
    statusSection.hidden = true;
    resultsSection.hidden = true;
    failedSection.hidden = true;
    formError.hidden = true;
    updateGenerateEnabled();
  }

  function updateGenerateEnabled() {
    const layoutChosen = !!document.querySelector('input[name="layout_type"]:checked');
    generateBtn.disabled = !(selectedFile && layoutChosen);
  }

  function setFile(file) {
    if (!file) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      showFormError("Only .pdf files are accepted.");
      return;
    }
    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileNameEl.hidden = false;
    formError.hidden = true;
    updateGenerateEnabled();
  }

  function showFormError(msg) {
    formError.textContent = msg;
    formError.hidden = false;
  }

  browseBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => setFile(e.target.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    setFile(file);
  });

  document.querySelectorAll('input[name="layout_type"]').forEach((r) =>
    r.addEventListener("change", updateGenerateEnabled)
  );

  generateBtn.addEventListener("click", startJob);
  document.getElementById("start-over-btn").addEventListener("click", resetToForm);
  document.getElementById("failed-retry-btn").addEventListener("click", resetToForm);

  async function startJob() {
    const layoutType = document.querySelector('input[name="layout_type"]:checked');
    if (!selectedFile || !layoutType) return;

    generateBtn.disabled = true;
    formError.hidden = true;
    resultsSection.hidden = true;
    failedSection.hidden = true;
    statusSection.hidden = false;
    setStatus("Uploading drawing...");

    const form = new FormData();
    form.append("file", selectedFile);
    form.append("layout_type", layoutType.value);

    try {
      const resp = await fetch("/api/jobs", { method: "POST", body: form });
      if (!resp.ok) {
        const body = await safeJson(resp);
        throw new Error((body && body.detail) || `Upload failed (HTTP ${resp.status}).`);
      }
      const data = await resp.json();
      currentJobId = data.job_id;
      pollStatus();
    } catch (err) {
      showFailed(err.message || "Upload failed.");
    }
  }

  async function safeJson(resp) {
    try { return await resp.json(); } catch { return null; }
  }

  function setStatus(text) {
    statusText.textContent = text;
  }

  async function pollStatus() {
    if (!currentJobId) return;
    try {
      const resp = await fetch(`/api/jobs/${currentJobId}`);
      if (!resp.ok) throw new Error(`Status check failed (HTTP ${resp.status}).`);
      const data = await resp.json();

      if (data.state === "failed") {
        showFailed(data.error || "Processing failed for an unknown reason.");
        return;
      }
      if (data.state === "complete") {
        showResults(data);
        return;
      }
      setStatus(data.stage || "Processing...");
      pollHandle = setTimeout(pollStatus, 1800);
    } catch (err) {
      showFailed(err.message || "Lost contact with the server while processing.");
    }
  }

  function showFailed(message) {
    statusSection.hidden = true;
    resultsSection.hidden = true;
    failedSection.hidden = false;
    failedText.textContent = message;
    generateBtn.disabled = false;
  }

  function row(label, value) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.textContent = label;
    const td2 = document.createElement("td");
    td2.textContent = value;
    tr.append(td1, td2);
    return tr;
  }

  function showResults(data) {
    statusSection.hidden = true;
    failedSection.hidden = true;
    resultsSection.hidden = false;

    const r = data.result || {};
    summaryTable.innerHTML = "";
    if (r.part_number) summaryTable.append(row("Part Number", r.part_number));
    if (r.revision) summaryTable.append(row("Revision", r.revision));
    summaryTable.append(row("Layout Type", data.layout_type === "customer" ? "Customer" : "Supplier"));
    if (data.layout_type === "customer" && r.customer) summaryTable.append(row("Customer", r.customer));
    if (r.customer_part_number) summaryTable.append(row("Customer Part Number", r.customer_part_number));
    summaryTable.append(row("Characteristics Ballooned", String(r.characteristics_count ?? 0)));

    const warnings = r.warnings || [];
    if (warnings.length > 0) {
      reviewBanner.hidden = false;
      reviewCountText.textContent = ` ${warnings.length} item${warnings.length === 1 ? "" : "s"} require${warnings.length === 1 ? "s" : ""} review.`;
      warningsBlock.hidden = false;
      warningsList.innerHTML = "";
      warnings.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = w;
        warningsList.appendChild(li);
      });
    } else {
      reviewBanner.hidden = true;
      warningsBlock.hidden = true;
    }

    const dlReview = document.getElementById("dl-review");
    dlReview.hidden = !r.has_review_log;
    if (r.has_review_log) dlReview.href = `/api/jobs/${currentJobId}/review-log`;

    document.getElementById("dl-pdf").href = `/api/jobs/${currentJobId}/ballooned-pdf`;
    document.getElementById("dl-excel").href = `/api/jobs/${currentJobId}/excel`;
    document.getElementById("dl-both").href = `/api/jobs/${currentJobId}/download-all`;

    generateBtn.disabled = false;
  }

  updateGenerateEnabled();
})();
