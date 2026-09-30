'use strict';

/* ── DOM refs ──────────────────────────────────────────────────────── */
const form            = document.getElementById('flyer-form');
const previewBtn      = document.getElementById('preview-btn');
const downloadBtn     = document.getElementById('download-btn');
const downloadBtn2    = document.getElementById('download-btn-2');

// Photo
const photoDropZone   = document.getElementById('photo-drop-zone');
const photoInput      = document.getElementById('photo-input');
const photoPreviewImg = document.getElementById('photo-preview-img');
const photoPlaceholder= document.getElementById('photo-placeholder');
const photoChangeBtn  = document.getElementById('photo-change-btn');

// Preview pane states
const previewContainer   = document.getElementById('preview-container');
const previewIdle        = document.getElementById('preview-idle');
const previewLoading     = document.getElementById('preview-loading');
const previewImageWrapper= document.getElementById('preview-image-wrapper');
const previewImage       = document.getElementById('preview-image');
const previewError       = document.getElementById('preview-error');
const previewErrorMsg    = document.getElementById('preview-error-msg');
const previewFooter      = document.getElementById('preview-footer');

// URLs injected from window (set inline in template via data attrs)
const PREVIEW_URL  = document.getElementById('flyer-form').dataset.previewUrl  || '/preview/';
const DOWNLOAD_URL = document.getElementById('flyer-form').dataset.downloadUrl || '/download/';

/* ── Photo drag-and-drop ───────────────────────────────────────────── */
photoDropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  photoDropZone.classList.add('drag-over');
});

photoDropZone.addEventListener('dragleave', () => {
  photoDropZone.classList.remove('drag-over');
});

photoDropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  photoDropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) {
    setPhotoFile(file);
  }
});

photoInput.addEventListener('change', () => {
  if (photoInput.files[0]) {
    setPhotoFile(photoInput.files[0]);
  }
});

photoChangeBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  clearPhoto();
});

function setPhotoFile(file) {
  const reader = new FileReader();
  reader.onload = (ev) => {
    photoPreviewImg.src = ev.target.result;
    photoPreviewImg.style.display = 'block';
    photoPlaceholder.style.display = 'none';
    photoChangeBtn.style.display = 'block';
  };
  reader.readAsDataURL(file);
  // Sync to a DataTransfer so we can send the actual file
  const dt = new DataTransfer();
  dt.items.add(file);
  photoInput.files = dt.files;
}

function clearPhoto() {
  photoPreviewImg.src = '';
  photoPreviewImg.style.display = 'none';
  photoPlaceholder.style.display = 'block';
  photoChangeBtn.style.display = 'none';
  photoInput.value = '';
}

/* ── Show/hide preview states ──────────────────────────────────────── */
function showIdle() {
  previewIdle.style.display = '';
  previewLoading.style.display = 'none';
  previewImageWrapper.style.display = 'none';
  previewError.style.display = 'none';
  previewFooter.style.display = 'none';
  setDownloadEnabled(false);
}

function showLoading() {
  previewIdle.style.display = 'none';
  previewLoading.style.display = '';
  previewImageWrapper.style.display = 'none';
  previewError.style.display = 'none';
  previewFooter.style.display = 'none';
}

function showImage(src) {
  previewIdle.style.display = 'none';
  previewLoading.style.display = 'none';
  previewError.style.display = 'none';
  previewImage.src = src;
  previewImageWrapper.style.display = '';
  previewFooter.style.display = '';
  const templateSwitcherPanel = document.getElementById('template-switcher-panel');
  if (templateSwitcherPanel) {
    templateSwitcherPanel.style.display = 'block';
  }
  setDownloadEnabled(true);
}


function showError(msg) {
  previewIdle.style.display = 'none';
  previewLoading.style.display = 'none';
  previewImageWrapper.style.display = 'none';
  previewErrorMsg.textContent = msg;
  previewError.style.display = '';
  previewFooter.style.display = 'none';
  setDownloadEnabled(false);
}

function setDownloadEnabled(enabled) {
  downloadBtn.disabled  = !enabled;
  downloadBtn2.disabled = !enabled;
}

/* ── Build FormData from the form ──────────────────────────────────── */
function buildFormData() {
  const fd = new FormData(form);
  return fd;
}

/* ── CSRF helper ────────────────────────────────────────────────────── */
function getCsrf() {
  return document.querySelector('[name=csrfmiddlewaretoken]').value;
}

/* ── Preview ────────────────────────────────────────────────────────── */
previewBtn.addEventListener('click', async () => {
  if (!form.reportValidity()) {
    return;
  }
  showLoading();
  previewBtn.disabled = true;
  try {
    const fd = buildFormData();
    const resp = await fetch(PREVIEW_URL, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
      body: fd,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    showImage(url);
  } catch (err) {
    showError(err.message || 'Erreur inconnue lors de la génération.');
  } finally {
    previewBtn.disabled = false;
  }
});

/* ── Download PDF ───────────────────────────────────────────────────── */
async function triggerDownload() {
  if (!form.reportValidity()) {
    return;
  }
  downloadBtn.disabled  = true;
  downloadBtn2.disabled = true;

  try {
    const fd = buildFormData();
    const resp = await fetch(DOWNLOAD_URL, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
      body: fd,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'soutenance_flyer.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    // Delay revocation to allow the browser to initiate the download thread and resolve metadata
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 250);
  } catch (err) {
    alert('Erreur lors du téléchargement : ' + err.message);
  } finally {
    downloadBtn.disabled  = false;
    downloadBtn2.disabled = false;
  }
}

downloadBtn.addEventListener('click', triggerDownload);
downloadBtn2.addEventListener('click', triggerDownload);

/* ── Auto-preview on input change (debounced 800ms) ──────────────────── */
let debounceTimer = null;

function scheduleAutoPreview(force = false) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    // Auto-preview if forced (e.g. photo controls tapped) or if preview is currently visible
    if (force || (previewImageWrapper && previewImageWrapper.style.display !== 'none')) {
      previewBtn.click();
    }
  }, 350);
}

const SEARCH_URL   = document.getElementById('flyer-form').dataset.searchUrl   || '/api/students/search/';

/* ── Autocomplete Search logic for Student Name ─────────────────────── */
const fullNameInput        = document.getElementById('full_name');
const autocompleteResults  = document.getElementById('autocomplete-results');
let searchDebounceTimer    = null;

if (fullNameInput && autocompleteResults) {
  fullNameInput.addEventListener('input', () => {
    const query = fullNameInput.value.trim();
    clearTimeout(searchDebounceTimer);

    if (query.length < 2) {
      autocompleteResults.style.display = 'none';
      autocompleteResults.innerHTML = '';
      return;
    }

    searchDebounceTimer = setTimeout(async () => {
      try {
        const resp = await fetch(`${SEARCH_URL}?q=${encodeURIComponent(query)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const students = data.students || [];

        if (students.length === 0) {
          autocompleteResults.style.display = 'none';
          autocompleteResults.innerHTML = '';
          return;
        }

        autocompleteResults.innerHTML = students.map(s => `
          <div class="autocomplete-item" data-student='${JSON.stringify(s).replace(/'/g, "&apos;")}'>
            <div class="autocomplete-name">${escapeHtml(s.full_name)}</div>
            <div class="autocomplete-meta">${escapeHtml(s.classe || '')} · ${escapeHtml(s.filiere)}-${escapeHtml(s.niveau)}</div>
          </div>
        `).join('');

        autocompleteResults.style.display = 'block';

        autocompleteResults.querySelectorAll('.autocomplete-item').forEach(item => {
          item.addEventListener('click', () => {
            const studentData = JSON.parse(item.getAttribute('data-student'));
            selectStudent(studentData);
          });
        });
      } catch (err) {
        console.error('Error fetching autocomplete results:', err);
      }
    }, 300);
  });

  document.addEventListener('click', (e) => {
    if (!fullNameInput.contains(e.target) && !autocompleteResults.contains(e.target)) {
      autocompleteResults.style.display = 'none';
    }
  });
}

const CHECK_DUPLICATE_URL = document.getElementById('flyer-form').dataset.checkDuplicateUrl || '/api/students/check-duplicate/';

/* ── Live Duplicate Student Detection ───────────────────────────────── */
const duplicateBanner    = document.getElementById('duplicate-warning-banner');
const duplicateDetails   = document.getElementById('duplicate-details');
const duplicateLoadBtn   = document.getElementById('duplicate-load-btn');
const duplicateIgnoreBtn = document.getElementById('duplicate-ignore-btn');
let duplicateDebounceTimer = null;
let currentDuplicateStudent = null;
let ignoredDuplicateName = null;

async function checkDuplicateStudent(name) {
  if (!duplicateBanner || !name || name.length < 2) {
    if (duplicateBanner) duplicateBanner.style.display = 'none';
    currentDuplicateStudent = null;
    return;
  }

  if (ignoredDuplicateName && name.toLowerCase() === ignoredDuplicateName.toLowerCase()) {
    duplicateBanner.style.display = 'none';
    return;
  }

  try {
    const resp = await fetch(`${CHECK_DUPLICATE_URL}?name=${encodeURIComponent(name)}`);
    if (!resp.ok) return;
    const data = await resp.json();

    if (data.is_duplicate && data.matches && data.matches.length > 0) {
      const match = data.matches[0];
      currentDuplicateStudent = match;
      const typeText = match.is_exact ? "Nom identique" : "Nom similaire";
      duplicateDetails.textContent = ` ${typeText} : "${match.full_name}" (${match.classe || ''} · ${match.filiere}-${match.niveau})`;
      duplicateBanner.style.display = 'block';
    } else {
      duplicateBanner.style.display = 'none';
      currentDuplicateStudent = null;
    }
  } catch (err) {
    console.error('Error checking student duplicates:', err);
  }
}

if (fullNameInput) {
  fullNameInput.addEventListener('input', () => {
    const name = fullNameInput.value.trim();
    if (ignoredDuplicateName && name.toLowerCase() !== ignoredDuplicateName.toLowerCase()) {
      ignoredDuplicateName = null;
    }
    clearTimeout(duplicateDebounceTimer);
    duplicateDebounceTimer = setTimeout(() => {
      checkDuplicateStudent(name);
    }, 400);
  });
}

if (duplicateLoadBtn) {
  duplicateLoadBtn.addEventListener('click', () => {
    if (currentDuplicateStudent) {
      selectStudent(currentDuplicateStudent);
      duplicateBanner.style.display = 'none';
    }
  });
}

if (duplicateIgnoreBtn) {
  duplicateIgnoreBtn.addEventListener('click', () => {
    if (fullNameInput) {
      ignoredDuplicateName = fullNameInput.value.trim();
    }
    if (duplicateBanner) duplicateBanner.style.display = 'none';
  });
}

function selectStudent(s) {
  if (!s) return;
  if (fullNameInput) fullNameInput.value = s.full_name || '';

  const classeInput = document.getElementById('classe');
  if (classeInput) classeInput.value = s.classe || '';

  const filiereSelect = document.getElementById('filiere');
  if (filiereSelect && s.filiere) filiereSelect.value = s.filiere;

  const niveauSelect = document.getElementById('niveau');
  if (niveauSelect && s.niveau) niveauSelect.value = s.niveau;

  const togeCheck = document.getElementById('toge');
  if (togeCheck) togeCheck.checked = !!s.toge;

  const echarpeCheck = document.getElementById('echarpe');
  if (echarpeCheck) echarpeCheck.checked = !!s.echarpe;

  // Fill theme and supervisors if available in saved record
  const themeInput = document.getElementById('theme');
  if (themeInput && s.theme) themeInput.value = s.theme;

  const acadInput = document.getElementById('academic_supervisor');
  if (acadInput && s.academic_supervisor) acadInput.value = s.academic_supervisor;

  const profInput = document.getElementById('professional_supervisor');
  if (profInput && s.professional_supervisor) profInput.value = s.professional_supervisor;

  autocompleteResults.style.display = 'none';
  if (duplicateBanner) duplicateBanner.style.display = 'none';

  // Schedule preview update after selection
  scheduleAutoPreview();
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ── Post-Preview Template Switcher ─────────────────────────────────── */
const templateChips = document.querySelectorAll('.template-chip');
const templateChoiceInput = document.getElementById('template_choice');
const dlTemplateChoiceInput = document.getElementById('dl-template_choice');

if (templateChips.length > 0) {
  templateChips.forEach(chip => {
    chip.addEventListener('click', () => {
      templateChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const selectedTemplate = chip.dataset.template;
      const val = (selectedTemplate === 'auto') ? '' : selectedTemplate;
      if (templateChoiceInput) templateChoiceInput.value = val;
      if (dlTemplateChoiceInput) dlTemplateChoiceInput.value = val;

      // Re-trigger preview generation with the new selected template
      previewBtn.click();
    });
  });
}





