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
const maskInstruction = document.querySelector("#mask-instruction-text");
let selectedFile = null;
let jobId = null;
let currentDocument = null;
let finalApproved = false;
let interactionMode = "select";
let selectedMaskId = null;
let maskBusy = false;
let editorState = { manual_masks: [], disabled_automatic_mask_ids: [], automatic_mask_overrides: [], keep_pages: [] };
let editorDirty = false;
let maskHistory = [];
let recheckTimer = null;
let recheckPromise = null;
let editRevision = 0;
let interactionActive = false;
let deferredRender = null;
let recheckPending = false;
const translations = {
  "Language":"اللغة", "LOCAL PRIVACY CHECKS":"فحوصات الخصوصية المحلية", "DOCUMENT DIGITIZATION":"رقمنة المستندات",
  "From paper":"من الورق", "to useful data.":"إلى بيانات مفيدة.",
  "Upload a document, review its redactions, and export the extracted fields.":"ارفع مستندًا، وراجع الحجب، ثم صدّر البيانات المستخرجة.",
  "Workflow steps":"خطوات العمل", "Upload":"رفع", "Visual Review":"المراجعة البصرية", "Results & Export":"النتائج والتصدير",
  "Upload document":"رفع مستند", "Drop a file here":"أفلت الملف هنا", "or":"أو", "browse your device":"اختر من جهازك",
  "OCR and privacy masking run locally first":"تتم قراءة النص والحجب محليًا أولًا", "Running local OCR and privacy checks…":"جارٍ التعرف على النص وفحوصات الخصوصية محليًا…",
  "Running local OCR, PII detection, redaction, and verification…":"جارٍ التعرف الضوئي واكتشاف البيانات الحساسة وحجبها والتحقق محليًا…",
  "Document preview":"معاينة المستند", "The source stays local; masked pages are used for AI":"يبقى الملف الأصلي محليًا؛ وتُستخدم الصفحات المحجوبة للذكاء الاصطناعي",
  "Redaction controls":"أدوات الحجب", "Select / Move":"تحديد / تحريك", "Draw Mask":"رسم حجب", "Undo":"تراجع",
  "Remove Selected Mask":"إزالة الحجب المحدد", "Clear Masks":"مسح كل الحجب", "Continue to AI":"متابعة إلى الذكاء الاصطناعي",
  "Retry AI":"إعادة المحاولة", "Extraction ready":"الاستخراج جاهز", "Review and edit the extracted fields. Values stay in their source language.":"راجع الحقول المستخرجة وعدّلها. تبقى القيم بلغة المستند الأصلية.",
  "Field":"الحقل", "Value":"القيمة", "Actions":"إجراءات", "+ Add field":"+ إضافة حقل", "Export to Excel":"تصدير إلى Excel",
  "Export to Word":"تصدير إلى Word", "Export ready":"التصدير جاهز", "Your file has been downloaded.":"تم تنزيل الملف.",
  "Download again":"تنزيل مرة أخرى", "ClearDoc Prototype":"نموذج ClearDoc", "OCR, masking, and privacy verification run locally.":"تتم قراءة النص والحجب والتحقق من الخصوصية محليًا.",
  "Advanced OCR Details":"تفاصيل التعرف الضوئي المتقدمة", "Select Mask":"تحديد الحجب", "Draw a mask":"ارسم حجبًا",
  "Automatic masks are yellow; manual masks are blue.":"الحجب التلقائي أصفر واليدوي أزرق.", "Masks":"حالات الحجب",
  "Privacy check passed":"اجتاز فحص الخصوصية", "Privacy check needed":"يلزم فحص الخصوصية", "Preparing secure preview":"جارٍ إعداد المعاينة الآمنة",
  "Sensitive OCR text is protected locally before AI processing.":"تُحمى النصوص الحساسة محليًا قبل المعالجة بالذكاء الاصطناعي.",
  "The local privacy check needs attention. Review the masks; Continue to AI proceeds with your approval.":"يتطلب فحص الخصوصية المحلي مراجعة. راجع الحجب ثم تابع بموافقتك.",
  "Review the document and adjust any masks before continuing.":"راجع المستند واضبط الحجب قبل المتابعة.",
  "Review the page masks, then continue when you are ready to send the redacted document to AI.":"راجع الحجب ثم تابع لإرسال النسخة المحجوبة إلى الذكاء الاصطناعي.",
  "Your mask changes are being rechecked locally.":"جارٍ إعادة فحص تغييرات الحجب محليًا.",
  "Mask changes will be checked locally…":"سيتم فحص تغييرات الحجب محليًا…", "Editing mask locally…":"جارٍ تعديل الحجب محليًا…",
  "Rechecking OCR and privacy in the background…":"جارٍ إعادة فحص النص والخصوصية في الخلفية…",
  "Draw Mask is active. Click a mask to select it, or drag on clear page space to add one.":"وضع الرسم مفعّل. انقر على حجب لتحديده أو اسحب في مساحة فارغة لإضافة حجب.",
  "Draw Mask is active. Drag on a clear area to add a mask; clicking any existing mask selects it. Use Select / Move to reposition or resize.":"وضع الرسم مفعّل. اسحب في مساحة فارغة لإضافة حجب، أو انقر على حجب موجود لتحديده. استخدم التحديد والتحريك لتغيير موضعه أو حجمه.",
  "Select / Move is active. Click a mask to select it, drag to move, or drag its corner to resize.":"وضع التحديد والتحريك مفعّل. انقر لتحديد الحجب، واسحب لتحريكه أو اسحب زاويته لتغيير حجمه.",
  "Click to select, drag to move, and drag a corner to resize.":"انقر للتحديد واسحب للتحريك أو اسحب الزاوية لتغيير الحجم.",
  "Page":"الصفحة", "Remove page":"إزالة الصفحة", "Move page up":"تحريك الصفحة للأعلى", "Move page down":"تحريك الصفحة للأسفل",
  "Remove field":"إزالة الحقل", "Field name":"اسم الحقل", "Field value":"قيمة الحقل", "Document Type":"نوع المستند", "Summary":"الملخص",
  "Complete final approval before exporting.":"أكمل الموافقة النهائية قبل التصدير.", "Excel export failed. Please try again.":"فشل تصدير Excel. حاول مرة أخرى.",
  "Word export failed. Please try again.":"فشل تصدير Word. حاول مرة أخرى.", "Fix the highlighted field errors before export.":"أصلح أخطاء الحقول المحددة قبل التصدير.",
  "Enter a field name or remove this row.":"أدخل اسم الحقل أو أزل هذا الصف.", "This field name is duplicated.":"اسم الحقل مكرر.",
  "Clear every manual and automatic mask? Privacy verification may then fail until sensitive areas are masked again.":"هل تريد إزالة جميع حالات الحجب؟ قد يفشل فحص الخصوصية حتى تعيد حجب المناطق الحساسة.",
  "Local document processing could not be completed.":"تعذرت معالجة المستند محليًا.", "Upload failed.":"فشل رفع الملف.", "The request could not be completed.":"تعذر إكمال الطلب.",
  "The server returned an unreadable response. Please try again.":"أعاد الخادم استجابة غير مقروءة. حاول مرة أخرى.",
  "Upload or local processing failed. Please try another file.":"فشل رفع الملف أو معالجته محليًا. جرّب ملفًا آخر.",
  "Local processing failed.":"فشلت المعالجة المحلية.", "The final approval was not recorded.":"لم يتم تسجيل الموافقة النهائية.",
  "Mask changes are being checked locally. You can continue to AI after the save finishes.":"جارٍ فحص تغييرات الحجب محليًا. يمكنك المتابعة بعد اكتمال الحفظ.",
  "Review the page masks. Local checks will update in the background.":"راجع حالات الحجب. ستُحدّث الفحوصات المحلية في الخلفية.",
  "Changes saved. Local privacy checks passed.":"تم حفظ التغييرات واجتازت فحوصات الخصوصية المحلية.",
  "Changes saved. Local privacy checks need attention; review your masks before continuing.":"تم حفظ التغييرات. راجع الحجب قبل المتابعة.",
  "Rechecking OCR and privacy in the background…":"جارٍ إعادة فحص النص والخصوصية في الخلفية…",
  "Select a mask to remove.":"حدد حالة حجب لإزالتها.", "Remove file":"إزالة الملف",
  "This page cannot be removed because it is the last page.":"لا يمكن إزالة هذه الصفحة لأنها الصفحة الأخيرة.",
  "The connection interrupted the response; review the result below.":"انقطع الاتصال أثناء الاستجابة؛ راجع النتيجة أدناه.",
  "AI processing completed. The connection interrupted the response; review the result below.":"اكتمل استخراج الذكاء الاصطناعي. انقطع الاتصال أثناء الاستجابة؛ راجع النتيجة أدناه.",
  "Changing the output language means you need to approve the results again.":"تغيير لغة المخرجات يتطلب الموافقة على النتائج مرة أخرى.",
  "Choose a PDF or image to upload.":"اختر ملف PDF أو صورة لرفعها.", "Supported formats: PDF, PNG, JPG, TIFF, BMP.":"الصيغ المدعومة: PDF وPNG وJPG وTIFF وBMP.",
  "Document review not found.":"لم يتم العثور على مراجعة المستند.", "Review not found.":"لم يتم العثور على المراجعة.",
  "Manual redaction is only available before AI approval.":"يتوفر الحجب اليدوي قبل الموافقة على استخدام الذكاء الاصطناعي فقط.",
  "Manual redaction could not be applied. Please try again.":"تعذر تطبيق الحجب اليدوي. حاول مرة أخرى.",
  "Document review is no longer available.":"لم تعد مراجعة المستند متاحة.", "This document is not ready for AI approval.":"المستند غير جاهز للموافقة على استخدام الذكاء الاصطناعي.",
  "Choose Arabic or English output.":"اختر المخرجات العربية أو الإنجليزية.",
  "AI processing failed unexpectedly. Please retry.":"حدث خطأ غير متوقع أثناء معالجة الذكاء الاصطناعي. أعد المحاولة.",
  "Gemini API key is not configured.":"مفتاح Gemini API غير مهيأ.", "Gemini SDK is not installed. Install project requirements.":"حزمة Gemini غير مثبتة. ثبّت متطلبات المشروع.",
  "Gemini returned an empty response.":"أعاد Gemini استجابة فارغة.", "Gemini returned a response that could not be parsed.":"تعذر تحليل استجابة Gemini.",
  "Gemini returned data that does not match the expected extraction format.":"البيانات التي أعادها Gemini لا تطابق تنسيق الاستخراج المطلوب.",
  "Tesseract could not be started. Check TESSERACT_CMD and install its language data.":"تعذر تشغيل Tesseract. تحقق من مساره وثبّت ملفات اللغة.",
  "TESSERACT_LANG must include both eng and ara for English and Arabic recognition.":"يجب أن يتضمن إعداد Tesseract اللغتين الإنجليزية والعربية.",
  "The local OCR/privacy selections are invalid.":"اختيارات التعرف الضوئي والخصوصية المحلية غير صالحة.",
  "An automatic mask selection is invalid.":"اختيار الحجب التلقائي غير صالح.", "Manual mask coordinates are invalid.":"إحداثيات الحجب اليدوي غير صالحة.",
  "Manual mask page is invalid.":"صفحة الحجب اليدوي غير صالحة.", "Manual mask must stay within the document page.":"يجب أن يبقى الحجب اليدوي داخل حدود الصفحة.",
  "Select at least one valid document page.":"حدد صفحة صالحة واحدة على الأقل.",
  "File exceeds the configured size limit.":"حجم الملف يتجاوز الحد المسموح.", "Preview not found.":"لم يتم العثور على المعاينة.",
  "OCR diagnostics are unavailable for this document.":"تفاصيل التعرف الضوئي غير متاحة لهذا المستند.",
  "Recognized text with sensitive values tokenized":"النص المتعرف عليه بعد استبدال القيم الحساسة برموز",
  "Local privacy checks need attention. Review the masks and try again.":"يلزم مراجعة فحوصات الخصوصية المحلية. راجع الحجب ثم أعد المحاولة.",
  "Automatic masks are yellow; manual masks are blue.":"الحجب التلقائي أصفر واليدوي أزرق.",
  "Save the local mask changes before continuing to AI.":"احفظ تغييرات الحجب المحلية قبل المتابعة إلى الذكاء الاصطناعي.",
  "Extracting fields from the locally redacted pages. Multi-page documents may take longer.":"جارٍ استخراج الحقول من الصفحات المحجوبة محليًا. قد تستغرق المستندات متعددة الصفحات وقتًا أطول."
};
const attributeWords = {
  name:"الاسم", full:"كامل", first:"الأول", middle:"الأوسط", last:"الأخير", family:"العائلة",
  phone:"الهاتف", telephone:"الهاتف", mobile:"الجوال", email:"البريد_الإلكتروني", address:"العنوان",
  company:"الشركة", department:"القسم", date:"التاريخ", birth:"الميلاد", nationality:"الجنسية",
  passport:"جواز_السفر", national:"وطني", id:"الهوية", employee:"الموظف", position:"المنصب",
  job:"الوظيفة", title:"المسمى", salary:"الراتب", signature:"التوقيع", start:"بداية", end:"نهاية",
  city:"المدينة", country:"الدولة", postal:"البريدي", code:"الرمز", gender:"الجنس", age:"العمر"
};
const englishAttributeWords = {
  "الاسم":"name", "كامل":"full", "الأول":"first", "الأوسط":"middle", "الأخير":"last",
  "العائلة":"family", "الهاتف":"phone", "الجوال":"mobile", "البريد":"email", "الإلكتروني":"email",
  "العنوان":"address", "الشركة":"company", "القسم":"department", "التاريخ":"date", "الميلاد":"birth",
  "الجنسية":"nationality", "جواز":"passport", "السفر":"passport", "وطني":"national", "الهوية":"id",
  "الموظف":"employee", "المنصب":"position", "الوظيفة":"job", "المسمى":"title", "الراتب":"salary",
  "التوقيع":"signature", "بداية":"start", "نهاية":"end", "المدينة":"city", "الدولة":"country",
  "البريدي":"postal", "الرمز":"code", "الجنس":"gender", "العمر":"age"
};
const attributePhrases = {
  "full name":"الاسم الكامل", "first name":"الاسم الأول", "middle name":"الاسم الأوسط", "last name":"اسم العائلة",
  "company name":"اسم الشركة", "employee name":"اسم الموظف", "customer name":"اسم العميل",
  "employee id":"رقم الموظف", "national id":"رقم الهوية الوطنية", "passport number":"رقم جواز السفر",
  "date of birth":"تاريخ الميلاد", "job title":"المسمى الوظيفي", "start date":"تاريخ البدء",
  "postal code":"الرمز البريدي", "company representative name":"اسم ممثل الشركة",
  "الاسم الكامل":"full name", "الاسم الأول":"first name", "الاسم الأوسط":"middle name", "اسم العائلة":"last name",
  "اسم الشركة":"company name", "اسم الموظف":"employee name", "اسم العميل":"customer name",
  "رقم الموظف":"employee id", "رقم الهوية الوطنية":"national id", "رقم جواز السفر":"passport number",
  "تاريخ الميلاد":"date of birth", "المسمى الوظيفي":"job title", "تاريخ البدء":"start date",
  "الرمز البريدي":"postal code", "اسم ممثل الشركة":"company representative name"
};
function localizeAttribute(value, language) {
  const phrase = String(value).replaceAll("_", " ").replaceAll("-", " ").trim();
  const containsArabic = /[\u0600-\u06ff]/.test(phrase);
  if (language === "ar" && !containsArabic && attributePhrases[phrase.toLowerCase()]) return attributePhrases[phrase.toLowerCase()];
  if (language === "en" && containsArabic && attributePhrases[phrase]) return attributePhrases[phrase];
  const words = String(value).replace(/([a-z])([A-Z])/g, "$1 $2").split(/[_\s-]+/).filter(Boolean);
  const mapped = words.map(word => language === "ar"
    ? (attributeWords[word.toLowerCase()] || word)
    : (englishAttributeWords[word] || word));
  return mapped.join(" ").replaceAll("_", " ");
}
function t(text) { return (document.documentElement.lang === "ar" && translations[text]) || text; }
function applyLanguage(language) {
  const lang = language === "ar" ? "ar" : "en";
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach(node => { node.setAttribute("aria-label", t(node.dataset.i18nAria)); });
  document.querySelector("#interface-language").value = lang;
  localStorage.setItem("cleardoc-language", lang);
  document.title = lang === "ar" ? "ClearDoc · رقمنة المستندات" : "ClearDoc · Document digitization";
  if (currentDocument) renderLocal(currentDocument);
  if (!aiReview.hidden) {
    for (const input of fieldsBody.querySelectorAll(".field-key")) {
      if (["document_type", "نوع المستند"].includes(input.value)) input.value = lang === "ar" ? "نوع المستند" : "document_type";
      else if (["summary", "الملخص"].includes(input.value)) input.value = lang === "ar" ? "الملخص" : "summary";
      else input.value = localizeAttribute(input.value, lang);
    }
    if (finalApproved) {
      finalApproved = false;
      setResultEditable(true);
      completion.hidden = true;
      setMessage(t("Changing the output language means you need to approve the results again."), "notice");
    }
  }
}
const savedLanguage = localStorage.getItem("cleardoc-language") || "en";
document.querySelector("#interface-language").value = savedLanguage;
document.querySelector("#interface-language").addEventListener("change", event => applyLanguage(event.target.value));
applyLanguage(savedLanguage);

function setMessage(text, kind = "error") {
  message.textContent = t(text);
  message.className = `message ${kind}`;
  message.hidden = !text;
}

function setStep(active) {
  active = Math.max(0, Math.min(2, active));
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
    const error = new Error(t(data.error || "The request could not be completed."));
    error.data = data;
    throw error;
  }
  return data;
}

function chooseFile(file) {
  if (!file) return;
  selectedFile = file;
  fileRow.hidden = false;
  fileRow.innerHTML = `<span aria-hidden="true">▧</span><strong>${escapeHtml(file.name)}</strong><small>${(file.size / 1024 / 1024).toFixed(2)} MB</small><button type="button" aria-label="${t("Remove file")}">×</button>`;
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
  progress.hidden = false;
  document.querySelector("#progress-text").textContent = t("Running local OCR, PII detection, redaction, and verification…");
  setStep(0); setMessage("");
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
    document.querySelector("#upload-card").hidden = Boolean(data.redacted_previews?.length);
    localReview.hidden = false;
    localReview.scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(1);
    if (!response.ok) setMessage(data.error || "Local document processing could not be completed.");
  } catch (error) {
    setMessage(error.message || "Local processing failed.");
  } finally {
    progress.hidden = true;
    processButton.disabled = false;
  }
});

function renderLocal(data) {
  const priorScroll = previewContainer.scrollTop;
  const previewTop = previewContainer.getBoundingClientRect().top;
  const positionInPreview = figure => figure.getBoundingClientRect().top - previewTop + previewContainer.scrollTop;
  const priorFigure = [...previewContainer.querySelectorAll("figure[data-page]")].find(figure =>
    positionInPreview(figure) + figure.getBoundingClientRect().height > priorScroll);
  const priorPage = priorFigure?.dataset.page;
  const priorOffset = priorFigure ? priorScroll - positionInPreview(priorFigure) : 0;
  const passed = data.privacy_verified === true && data.metadata?.privacy_status === "PASSED";
  const badge = document.querySelector("#privacy-status");
  badge.textContent = t(passed ? "Privacy check passed" : "Privacy check needed");
  badge.className = `status-pill ${passed ? "passed" : "blocked"}`;
  const banner = document.querySelector("#privacy-banner");
  banner.textContent = t(passed ? "Sensitive OCR text is protected locally before AI processing." :
    data.error || "The local privacy check needs attention. Review the masks; Continue to AI proceeds with your approval.");
  banner.hidden = passed;
  document.querySelector("#privacy-hint").hidden = passed;
  previewContainer.replaceChildren();
  if (!editorDirty) {
    editorState = {
      manual_masks: structuredClone(data.manual_masks || []),
      disabled_automatic_mask_ids: [...(data.disabled_automatic_mask_ids || [])],
      automatic_mask_overrides: structuredClone(data.automatic_mask_overrides || []),
      keep_pages: [...(data.keep_pages || (data.page_dimensions || []).map(item => item.page))],
    };
  }
  if (!editorDirty && !localStorage.getItem("cleardoc-language")) applyLanguage(data.output_language || "en");
  editorState.output_language = document.documentElement.lang;
  const diagnostics = data.ocr_diagnostics || [];
  document.querySelector("#ocr-diagnostics").innerHTML = diagnostics.length
    ? `<ul>${diagnostics.map((page, index) => `<li>${t("Page")} ${index + 1}: ${escapeHtml(page.languages || "eng+ara")} · ${page.word_count ?? 0} ${document.documentElement.lang === "ar" ? "كلمة" : "words"} · ${page.line_count ?? 0} ${document.documentElement.lang === "ar" ? "سطرًا" : "lines"} · ${page.page_width} × ${page.page_height}px${page.pdf_render_dpi ? ` · PDF ${page.pdf_render_dpi} DPI` : ""}${page.average_confidence == null ? "" : ` · ${document.documentElement.lang === "ar" ? "متوسط الثقة" : "avg confidence"} ${page.average_confidence}%`}</li>`).join("")}</ul><h4>${t("Recognized text with sensitive values tokenized")}</h4><pre class="ocr-diagnostic-text">${escapeHtml(data.safe_ocr_text || "No OCR text available.")}</pre>`
    : t("OCR diagnostics are unavailable for this document.");
  const masks = visibleMasks();
  (data.redacted_previews || []).forEach((url, index) => {
    const page = data.page_dimensions?.[index]?.page ?? index;
    const figure = document.createElement("figure");
    const editor = document.createElement("div");
    editor.className = "mask-editor";
    figure.dataset.page = String(page);
    const dimensions = data.page_dimensions?.find(item => item.page === page);
    if (dimensions?.width && dimensions?.height) {
      editor.style.aspectRatio = `${dimensions.width} / ${dimensions.height}`;
    }
    const image = new Image();
    image.className = "mask-preview";
    if (dimensions?.width && dimensions?.height) { image.width = dimensions.width; image.height = dimensions.height; }
    image.alt = `Privacy-sanitized document page ${page + 1}`;
    const overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    overlay.classList.add("mask-overlay");
    overlay.dataset.page = String(page);
    overlay.setAttribute("role", "img");
    overlay.setAttribute("aria-label", `Privacy-sanitized page ${page + 1}; select or draw a mask`);
    overlay.setAttribute("preserveAspectRatio", "none");
    overlay.previewImage = image;
    image.onload = () => {
      overlay.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
      redrawCanvas(overlay, image, page, masks, null);
    };
    image.src = url;
    bindMaskCanvas(overlay, image, page);
    const caption = document.createElement("figcaption"); caption.textContent = `${t("Page")} ${page + 1}`;
    const controls = document.createElement("div"); controls.className = "page-controls";
    controls.innerHTML = `<button type="button" class="secondary page-up" aria-label="${t("Move page up")}">↑</button><button type="button" class="secondary page-down" aria-label="${t("Move page down")}">↓</button><button type="button" class="secondary page-remove">${t("Remove page")}</button>`;
    controls.querySelectorAll("button").forEach(button => { button.disabled = false; });
    controls.querySelector(".page-remove").disabled = editorState.keep_pages.length <= 1;
    controls.querySelector(".page-up").onclick = () => reorderPage(page, -1);
    controls.querySelector(".page-down").onclick = () => reorderPage(page, 1);
    controls.querySelector(".page-remove").onclick = () => removePage(page);
    editor.append(image, overlay);
    figure.append(editor, caption, controls); previewContainer.append(figure);
  });
  const canEdit = ["awaiting_ai_approval", "privacy_blocked", "blocked"].includes(data.status) &&
    Boolean(data.redacted_previews?.length);
  const canContinue = canEdit && !maskBusy;
  document.querySelector("#mask-count").textContent = `${editorState.manual_masks.length + visibleAutomaticMasks().length} ${t("Masks")}`;
  for (const id of ["select-mask-button", "draw-mask-button"]) {
    document.querySelector(`#${id}`).hidden = !canEdit;
    document.querySelector(`#${id}`).disabled = !canEdit;
  }
  document.querySelector("#select-mask-button").setAttribute("aria-pressed", String(interactionMode === "select"));
  document.querySelector("#draw-mask-button").setAttribute("aria-pressed", String(interactionMode === "draw"));
  document.querySelector("#undo-mask-button").disabled = !maskHistory.length || !canEdit;
  document.querySelector("#remove-mask-button").disabled = !selectedMaskId || !canEdit;
  document.querySelector("#clear-masks-button").disabled = (!editorState.manual_masks.length && !visibleAutomaticMasks().length) || !canEdit;
  document.querySelector(".mask-toolbar").hidden = !canEdit;
  document.querySelector("#mask-spinner").hidden = !maskBusy;
  maskInstruction.textContent = t(interactionActive ? "Editing mask locally…" : editorDirty ? "Mask changes will be checked locally…" : interactionMode === "draw"
    ? "Draw Mask is active. Click a mask to select it, or drag on clear page space to add one."
    : (maskBusy ? "Rechecking OCR and privacy in the background…" : "Automatic masks are yellow; manual masks are blue.")) +
    (interactionMode === "select" && !maskBusy && !editorDirty ? ` ${t("Click to select, drag to move, and drag a corner to resize.")}` : "");
  document.querySelector("#send-ai-button").disabled = !canContinue || maskBusy;
  document.querySelector("#send-ai-button").hidden = !canEdit;
  document.querySelector("#retry-button").hidden = !["rejected", "ai_failed"].includes(data.status);
  document.querySelector("#pre-ai-instruction").textContent = editorDirty
    ? t("Your mask changes are being rechecked locally.") : t("Review the page masks, then continue when you are ready to send the redacted document to AI.");
  requestAnimationFrame(() => {
    const target = priorPage == null ? null : [...previewContainer.querySelectorAll("figure[data-page]")].find(figure => figure.dataset.page === priorPage);
    previewContainer.scrollTop = target ? positionInPreview(target) + priorOffset : priorScroll;
  });
}

function visibleAutomaticMasks() {
  const disabled = new Set(editorState.disabled_automatic_mask_ids);
  const overrides = new Map(editorState.automatic_mask_overrides.map(item => [item.id, item]));
  return (currentDocument?.automatic_masks || []).filter(mask => !disabled.has(mask.id)).map(mask => ({
    ...mask, ...(overrides.get(mask.id) || {}), kind: "automatic",
  }));
}
function visibleMasks() { return [...visibleAutomaticMasks(), ...editorState.manual_masks.map(mask => ({ ...mask, kind: "manual" }))]; }
function snapshotEditor() { maskHistory.push(structuredClone(editorState)); if (maskHistory.length > 50) maskHistory.shift(); }
function markEditorChanged() {
  editRevision += 1;
  editorDirty = true;
  currentDocument = { ...currentDocument, privacy_verified: false, status: "privacy_blocked",
    requires_transmission_confirmation: false,
    metadata: { ...currentDocument.metadata, privacy_status: "BLOCKED", processing_status: "PRIVACY_REVIEW_REQUIRED" } };
  document.querySelector("#privacy-status").textContent = t("Privacy check needed");
  document.querySelector("#privacy-status").className = "status-pill blocked";
  document.querySelector("#privacy-banner").textContent = t("Mask changes are being checked locally. You can continue to AI after the save finishes.");
  document.querySelector("#privacy-banner").hidden = false;
  document.querySelector("#privacy-hint").hidden = false;
  document.querySelector("#pre-ai-instruction").textContent = t("Review the page masks. Local checks will update in the background.");
  document.querySelector("#send-ai-button").disabled = maskBusy;
  redrawAll();
  scheduleEditorRecheck();
}
function redrawAll() {
  previewContainer.querySelectorAll("svg.mask-overlay").forEach(overlay => redrawCanvas(overlay, overlay.previewImage, Number(overlay.dataset.page), visibleMasks(), null));
  document.querySelector("#mask-count").textContent = `${editorState.manual_masks.length + visibleAutomaticMasks().length} ${t("Masks")}`;
}

function redrawCanvas(canvas, image, page, masks, draft) {
  if (!image.naturalWidth || !image.naturalHeight || !image.complete) return;
  canvas.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
  canvas.replaceChildren();
  const drawRect = (mask, isDraft = false) => {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    let selectedHandle = null;
    for (const [name, value] of Object.entries({ x: mask.x, y: mask.y, width: mask.width, height: mask.height })) rect.setAttribute(name, String(value));
    if (isDraft) {
      rect.setAttribute("fill", "rgba(214,87,66,.14)");
      rect.setAttribute("stroke", "#d65742");
      rect.setAttribute("stroke-dasharray", "10 7");
    } else {
      const selected = mask.id === selectedMaskId;
      rect.setAttribute("fill", mask.kind === "automatic" ? "rgba(213,166,50,.24)" : "rgba(55,139,178,.24)");
      rect.setAttribute("stroke", selected ? "#e84f38" : (mask.kind === "automatic" ? "#d5a632" : "#378bb2"));
      rect.setAttribute("stroke-width", selected ? "5" : "3");
      if (selected) {
        selectedHandle = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        selectedHandle.setAttribute("x", String(mask.x + mask.width - 12));
        selectedHandle.setAttribute("y", String(mask.y + mask.height - 12));
        selectedHandle.setAttribute("width", "18"); selectedHandle.setAttribute("height", "18");
        selectedHandle.setAttribute("fill", "#fff"); selectedHandle.setAttribute("stroke", "#e84f38");
        selectedHandle.setAttribute("stroke-width", "3"); selectedHandle.setAttribute("pointer-events", "none");
      }
    }
    rect.setAttribute("pointer-events", "none");
    canvas.append(rect);
    if (selectedHandle) canvas.append(selectedHandle);
  };
  masks.forEach(mask => {
    if (mask.page !== page) return;
    drawRect(mask);
  });
  if (draft) drawRect(draft, true);
  canvas.classList.toggle("is-active", interactionMode === "draw");
}

function canvasPoint(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.previewImage.naturalWidth, (event.clientX - rect.left) * canvas.previewImage.naturalWidth / rect.width)),
    y: Math.max(0, Math.min(canvas.previewImage.naturalHeight, (event.clientY - rect.top) * canvas.previewImage.naturalHeight / rect.height)),
  };
}

function bindMaskCanvas(canvas, image, page) {
  let start = null;
  let draft = null;
  let moving = null;
  canvas.addEventListener("pointerdown", event => {
    if (!canvas.previewImage.naturalWidth) return;
    const point = canvasPoint(event, canvas);
    const masks = visibleMasks();
    let hit = null;
    for (let index = masks.length - 1; index >= 0; index--) {
      const mask = masks[index];
      if (mask.page === page && point.x >= mask.x && point.x <= mask.x + mask.width &&
          point.y >= mask.y && point.y <= mask.y + mask.height) { hit = mask; break; }
    }
    selectedMaskId = hit?.id || null;
    document.querySelector("#remove-mask-button").disabled = !selectedMaskId;
    redrawAll();
    if (hit && interactionMode === "draw") return;
    if (hit && interactionMode === "select") {
      moving = { mask: hit, start: point, original: { ...hit }, resize: point.x > hit.x + hit.width - 14 && point.y > hit.y + hit.height - 14 };
      event.preventDefault(); start = point; interactionActive = true; canvas.setPointerCapture(event.pointerId); return;
    }
    if (interactionMode !== "draw") return;
    event.preventDefault();
    start = point; interactionActive = true; draft = { x: point.x, y: point.y, width: 0, height: 0 };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!start) return;
    const point = canvasPoint(event, canvas);
    draft = { x: Math.min(start.x, point.x), y: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x), height: Math.abs(point.y - start.y) };
    if (moving) {
      const dx = point.x - moving.start.x, dy = point.y - moving.start.y;
      const rect = moving.resize ? { ...moving.original, width: Math.max(3, moving.original.width + dx), height: Math.max(3, moving.original.height + dy) } :
        { ...moving.original, x: moving.original.x + dx, y: moving.original.y + dy };
      draft = { ...moving.mask, ...rect };
      redrawCanvas(canvas, image, page, visibleMasks().map(item => item.id === draft.id ? draft : item), null);
    } else redrawCanvas(canvas, image, page, visibleMasks(), draft);
  });
  const finish = event => {
    if (!start) return;
    const point = canvasPoint(event, canvas);
    if (moving) {
      const dx = point.x - moving.start.x, dy = point.y - moving.start.y;
      if (Math.abs(dx) < 2 && Math.abs(dy) < 2) {
        start = null; draft = null; moving = null; interactionActive = false; redrawCanvas(canvas, image, page, visibleMasks(), null); flushDeferredRender(); return;
      }
      snapshotEditor();
      const updated = moving.resize ? { ...moving.original, width: Math.max(3, Math.round(moving.original.width + dx)), height: Math.max(3, Math.round(moving.original.height + dy)) } :
        { ...moving.original, x: Math.round(moving.original.x + dx), y: Math.round(moving.original.y + dy) };
      updateMaskRect(updated);
      start = null; draft = null; moving = null; interactionActive = false; markEditorChanged(); flushDeferredRender(); return;
    }
    const mask = { id: `manual-${crypto.randomUUID()}`, kind: "manual", page, x: Math.round(Math.min(start.x, point.x)), y: Math.round(Math.min(start.y, point.y)),
      width: Math.round(Math.abs(point.x - start.x)), height: Math.round(Math.abs(point.y - start.y)) };
    start = null; draft = null; interactionActive = false;
    if (mask.width > 2 && mask.height > 2) {
      snapshotEditor(); editorState.manual_masks.push(mask); markEditorChanged();
    }
    flushDeferredRender();
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

function updateMaskRect(mask) {
  if (mask.kind === "automatic") {
    const original = (currentDocument?.automatic_masks || []).find(item => item.id === mask.id);
    editorState.automatic_mask_overrides = editorState.automatic_mask_overrides.filter(item => item.id !== mask.id);
    if (original) editorState.automatic_mask_overrides.push({ id: mask.id, x: mask.x, y: mask.y, width: mask.width, height: mask.height });
  } else editorState.manual_masks = editorState.manual_masks.map(item => item.id === mask.id ? mask : item);
}
async function persistEditorState() {
  if (!jobId || !editorDirty) return currentDocument?.privacy_verified === true;
  if (maskBusy) {
    const result = recheckPromise ? await recheckPromise : false;
    return editorDirty ? persistEditorState() : result;
  }
  if (interactionActive) { scheduleEditorRecheck(100); return false; }
  clearTimeout(recheckTimer); recheckTimer = null;
  const revision = editRevision;
  const snapshot = structuredClone(editorState);
  const outputLanguage = document.documentElement.lang;
  recheckPending = false;
  maskBusy = true;
  document.querySelector("#mask-spinner").hidden = false;
  document.querySelector("#send-ai-button").disabled = true;
  maskInstruction.textContent = t("Rechecking OCR and privacy in the background…");
  const request = (async () => {
    let succeeded = false;
    try {
      const response = await fetch(`/api/manual-masks/${jobId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...snapshot,
        output_language: outputLanguage }),
      });
      const data = await readResponse(response);
      if (revision !== editRevision) return false;
      currentDocument = data; editorDirty = false; succeeded = true;
      setMessage(data.privacy_verified ? "Changes saved. Local privacy checks passed." : "Changes saved. Local privacy checks need attention; review your masks before continuing.", "notice");
      if (interactionActive) deferredRender = { data, revision };
      return data.privacy_verified === true;
    } catch (error) {
      if (revision === editRevision) setMessage(`${error.message} Your editor changes are retained. Continue to AI will retry the local check.`);
      return false;
    } finally {
      maskBusy = false;
      document.querySelector("#mask-spinner").hidden = true;
      if ((revision !== editRevision || recheckPending) && editorDirty) {
        recheckPending = false;
        scheduleEditorRecheck(0);
      }
      else if (succeeded && !interactionActive) renderLocal(currentDocument);
      else if (!interactionActive) redrawAll();
      else document.querySelector("#send-ai-button").disabled = true;
      if (!interactionActive) document.querySelector("#send-ai-button").disabled = editorDirty || !currentDocument?.redacted_previews?.length;
    }
  })();
  recheckPromise = request;
  try { return await request; }
  finally { if (recheckPromise === request) recheckPromise = null; }
}

function scheduleEditorRecheck(delay = 500) {
  clearTimeout(recheckTimer);
  recheckTimer = setTimeout(() => {
    recheckTimer = null;
    if (maskBusy || interactionActive) { recheckPending = true; return; }
    void persistEditorState();
  }, delay);
}

function flushDeferredRender() {
  if (interactionActive) return;
  if (deferredRender) {
    const pending = deferredRender;
    deferredRender = null;
    if (pending.revision === editRevision && !editorDirty) renderLocal(pending.data);
  }
  if (recheckPending && editorDirty && !maskBusy) { recheckPending = false; scheduleEditorRecheck(500); }
}

function setInteractionMode(mode) {
  interactionMode = mode;
  document.querySelector("#select-mask-button").setAttribute("aria-pressed", String(mode === "select"));
  document.querySelector("#draw-mask-button").setAttribute("aria-pressed", String(mode === "draw"));
  maskInstruction.textContent = t(mode === "draw"
    ? "Draw Mask is active. Drag on a clear area to add a mask; clicking any existing mask selects it. Use Select / Move to reposition or resize."
    : "Select / Move is active. Click a mask to select it, drag to move, or drag its corner to resize.");
  redrawAll();
}
document.querySelector("#select-mask-button").addEventListener("click", () => setInteractionMode("select"));
document.querySelector("#draw-mask-button").addEventListener("click", () => setInteractionMode("draw"));
document.querySelector("#undo-mask-button").addEventListener("click", () => {
  if (!maskHistory.length) return;
  editorState = maskHistory.pop(); selectedMaskId = null; markEditorChanged();
});
document.querySelector("#remove-mask-button").addEventListener("click", () => {
  if (!selectedMaskId) return;
  snapshotEditor();
  const auto = (currentDocument?.automatic_masks || []).some(mask => mask.id === selectedMaskId);
  if (auto) editorState.disabled_automatic_mask_ids.push(selectedMaskId);
  else editorState.manual_masks = editorState.manual_masks.filter(mask => mask.id !== selectedMaskId);
  editorState.automatic_mask_overrides = editorState.automatic_mask_overrides.filter(mask => mask.id !== selectedMaskId);
  selectedMaskId = null; markEditorChanged();
});
document.querySelector("#clear-masks-button").addEventListener("click", () => {
  if (!window.confirm(t("Clear every manual and automatic mask? Privacy verification may then fail until sensitive areas are masked again."))) return;
  snapshotEditor(); editorState.manual_masks = [];
  editorState.disabled_automatic_mask_ids = (currentDocument?.automatic_masks || []).map(mask => mask.id);
  editorState.automatic_mask_overrides = []; selectedMaskId = null;
  markEditorChanged();
});

function removePage(page) {
  const prompt = document.documentElement.lang === "ar"
    ? `هل تريد إزالة الصفحة ${page + 1} من هذا المستند؟`
    : `Remove page ${page + 1} from this document?`;
  if (editorState.keep_pages.length <= 1 || !window.confirm(prompt)) return;
  snapshotEditor(); editorState.keep_pages = editorState.keep_pages.filter(item => item !== page);
  editorState.manual_masks = editorState.manual_masks.filter(mask => mask.page !== page);
  editorState.automatic_mask_overrides = editorState.automatic_mask_overrides.filter(mask => {
    const original = (currentDocument?.automatic_masks || []).find(item => item.id === mask.id); return original?.page !== page;
  });
  const removedIds = (currentDocument?.automatic_masks || []).filter(mask => mask.page === page).map(mask => mask.id);
  editorState.disabled_automatic_mask_ids = editorState.disabled_automatic_mask_ids.filter(id => !removedIds.includes(id));
  markEditorChanged();
}
function reorderPage(page, direction) {
  const pages = [...editorState.keep_pages], index = pages.indexOf(page), target = index + direction;
  if (target < 0 || target >= pages.length) return;
  snapshotEditor(); [pages[index], pages[target]] = [pages[target], pages[index]]; editorState.keep_pages = pages;
  markEditorChanged();
}

async function postReview(action, result, exportFields) {
  const response = await fetch(`/api/review/${jobId}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...(result ? { result } : {}), ...(exportFields ? { export_fields: exportFields } : {}),
      ...(action === "approve" ? { output_language: document.documentElement.lang } : {}) }),
  });
  return readResponse(response);
}

document.querySelector("#retry-button").addEventListener("click", async () => {
  try {
    const data = await postReview("retry");
    currentDocument = data; renderLocal(data); setMessage(""); setStep(1);
  } catch (error) { setMessage(error.message); }
});

document.querySelector("#send-ai-button").addEventListener("click", async () => {
  if (editorDirty) {
    await persistEditorState();
    if (editorDirty) return;
  }
  if (!jobId || !currentDocument?.redacted_previews?.length || !["awaiting_ai_approval", "privacy_blocked", "blocked"].includes(currentDocument?.status)) {
    setMessage("Save the local mask changes before continuing to AI."); return;
  }
  const button = document.querySelector("#send-ai-button");
  button.disabled = true; aiProgress.hidden = false; setMessage(""); setStep(1);
  try {
    const response = await fetch(`/api/ai/${jobId}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true, output_language: document.documentElement.lang,
        include_confirmed: true }) });
    const data = await readResponse(response);
    currentDocument = data;
    localReview.hidden = true;
    setMessage("");
    renderAiReview(data);
    aiReview.hidden = false;
    aiReview.scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(2);
  } catch (error) {
    if (!error.data && jobId) {
      try {
        const latest = await readResponse(await fetch(`/api/review/${jobId}`));
        if (latest.status === "awaiting_final_approval") {
          currentDocument = latest; localReview.hidden = true; renderAiReview(latest);
          aiReview.hidden = false; setStep(2);
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
      renderLocal(currentDocument); setStep(1);
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
  const result = data.ai_result || {};
  fieldsBody.replaceChildren();
  const fields = { [document.documentElement.lang === "ar" ? "نوع المستند" : "document_type"]: result.document_type ?? "",
    [document.documentElement.lang === "ar" ? "الملخص" : "summary"]: result.summary ?? "", ...normalizeFields(result.fields) };
  Object.entries(fields).forEach(([key, value]) => addFieldRow(key, value));
  if (!Object.keys(fields).length) addFieldRow("", "");
  setResultEditable(true);
}

function setResultEditable(editable) {
  fieldsBody.querySelectorAll("input, textarea, button").forEach(control => { control.disabled = !editable; });
  document.querySelector("#add-field-button").disabled = !editable;
}

function addFieldRow(key = "", value = "") {
  const row = document.createElement("tr");
  row.innerHTML = `<td><input class="field-key" aria-label="${t("Field name")}"><small class="field-error" aria-live="polite"></small></td><td><textarea class="field-value" rows="2" aria-label="${t("Field value")}"></textarea><small class="field-error" aria-live="polite"></small></td><td><button type="button" class="remove-field" aria-label="${t("Remove field")}">×</button></td>`;
  row.querySelector(".field-key").value = key;
  row.querySelector(".field-value").value = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  row.querySelector(".remove-field").addEventListener("click", () => row.remove());
  fieldsBody.append(row);
}

document.querySelector("#add-field-button").addEventListener("click", () => addFieldRow());

function collectResult() {
  const fields = Object.create(null);
  const seenKeys = new Set();
  let documentType = "", summary = "";
  let firstInvalid = null;
  for (const error of fieldsBody.querySelectorAll(".field-error")) error.textContent = "";
  const report = (row, message, target) => {
    row.querySelectorAll(".field-error")[target].textContent = t(message);
    firstInvalid ||= row.querySelector(target === 0 ? ".field-key" : ".field-value");
  };
  for (const row of fieldsBody.rows) {
    const key = row.querySelector(".field-key").value.trim();
    const value = row.querySelector(".field-value").value;
    if (!key) { report(row, "Enter a field name or remove this row.", 0); continue; }
    if (seenKeys.has(key)) {
      report(row, "This field name is duplicated.", 0); continue;
    }
    seenKeys.add(key);
    if (key === "document_type" || key === "نوع المستند") documentType = value;
    else if (key === "summary" || key === "الملخص") summary = value;
    else fields[key] = value;
  }
  if (firstInvalid) { firstInvalid.focus(); throw new Error("Fix the highlighted field errors before export."); }
  return { document_type: documentType, summary, fields };
}

let lastExportFormat = "excel";
async function downloadApproved(format) {
  const response = await fetch(`/api/export/${jobId}?format=${format}`);
  if (!response.ok) {
    let data = {};
    try { data = await response.json(); } catch {}
    throw new Error(data.error || t(format === "word" ? "Word export failed. Please try again." : "Excel export failed. Please try again."));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `digitized-document.${format === "word" ? "docx" : "xlsx"}`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportWithApproval(button, format) {
  button.disabled = true; setMessage("");
  try {
    if (!finalApproved) {
      let result;
      try { result = collectResult(); }
      catch (error) { throw error; }
      const approved = await postReview("approve", result);
      if (approved.status !== "approved") throw new Error(t("The final approval was not recorded."));
      finalApproved = true;
      setResultEditable(false);
    }
    await downloadApproved(format);
    lastExportFormat = format;
    completion.hidden = false;
    document.querySelector("#completion-text").textContent = t("Your file has been downloaded.");
    completion.scrollIntoView({ behavior: "smooth" });
    setMessage("");
  } catch (error) {
    setMessage(finalApproved ? `${error.message} Your approval is saved; retry the download.` : error.message);
  } finally { button.disabled = false; }
}
document.querySelector("#export-excel-button").addEventListener("click", event => exportWithApproval(event.currentTarget, "excel"));
document.querySelector("#export-word-button").addEventListener("click", event => exportWithApproval(event.currentTarget, "word"));

document.querySelector("#download-again-button").addEventListener("click", async () => {
  try { await downloadApproved(lastExportFormat); setMessage(""); }
  catch (error) { setMessage(error.message); }
});
