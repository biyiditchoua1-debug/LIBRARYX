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
const photoCropEditor = document.getElementById('photo-crop-editor');
const photoCropCanvas = document.getElementById('photo-crop-canvas');
const photoCropInput  = document.getElementById('photo-crop');
const photoZoomInput  = document.getElementById('photo-zoom');
const photoZoomValue  = document.getElementById('photo-zoom-value');
const photoCropReset  = document.getElementById('photo-crop-reset');
const photoCropContext = photoCropCanvas.getContext('2d');
const photoCropSource = new Image();
let photoCropSourceUrl = null;
let photoCropState = { cx: 0.5, cy: 0.5, zoom: 1 };
let activeCropPointer = null;

// Preview pane states
const previewContainer   = document.getElementById('preview-container');
const previewIdle        = document.getElementById('preview-idle');
const previewLoading     = document.getElementById('preview-loading');
const previewImageWrapper= document.getElementById('preview-image-wrapper');
const previewImage       = document.getElementById('preview-image');
const previewError       = document.getElementById('preview-error');
const previewErrorMsg    = document.getElementById('preview-error-msg');
const previewFooter      = document.getElementById('preview-footer');
const previewIdleMessage = previewIdle.querySelector('p');
const DEFAULT_PREVIEW_MESSAGE = 'Remplissez le formulaire puis cliquez sur Prévisualiser.';
let activePreviewObjectUrl = null;

// URLs injected from window (set inline in template via data attrs)
const PREVIEW_URL  = document.getElementById('flyer-form').dataset.previewUrl  || '/preview/';
const PAYMENT_START_URL = document.getElementById('flyer-form').dataset.paymentStartUrl || '/payment/create/';

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
  if (photoCropSourceUrl) URL.revokeObjectURL(photoCropSourceUrl);
  photoCropSourceUrl = URL.createObjectURL(file);
  photoCropSource.onload = () => {
    photoCropState = { cx: 0.5, cy: 0.5, zoom: 1 };
    photoZoomInput.value = '1';
    drawPhotoCrop();
    photoCropEditor.style.display = 'block';
    photoPreviewImg.style.display = 'block';
    photoPlaceholder.style.display = 'none';
    photoChangeBtn.style.display = 'block';
  };
  photoCropSource.onerror = () => {
    clearPhoto();
    alert('Impossible de lire cette image. Choisissez une image JPG, PNG ou WebP.');
  };
  photoCropSource.src = photoCropSourceUrl;

  // Sync to a DataTransfer so we can send the actual file
  const dt = new DataTransfer();
  dt.items.add(file);
  photoInput.files = dt.files;
}

function getPhotoCropRect() {
  const sourceWidth = photoCropSource.naturalWidth;
  const sourceHeight = photoCropSource.naturalHeight;
  const targetRatio = photoCropCanvas.width / photoCropCanvas.height;
  const sourceRatio = sourceWidth / sourceHeight;
  const zoom = Math.min(3, Math.max(1, Number(photoCropState.zoom) || 1));

  let width = sourceRatio > targetRatio ? sourceHeight * targetRatio : sourceWidth;
  let height = sourceRatio > targetRatio ? sourceHeight : sourceWidth / targetRatio;
  width /= zoom;
  height /= zoom;

  const centerX = Math.min(sourceWidth - width / 2, Math.max(width / 2, photoCropState.cx * sourceWidth));
  const centerY = Math.min(sourceHeight - height / 2, Math.max(height / 2, photoCropState.cy * sourceHeight));
  return { x: centerX - width / 2, y: centerY - height / 2, width, height, centerX, centerY };
}

function drawPhotoCrop(updateThumbnail = true) {
  if (!photoCropSource.naturalWidth || !photoCropCanvas) return;
  const crop = getPhotoCropRect();
  photoCropState.cx = crop.centerX / photoCropSource.naturalWidth;
  photoCropState.cy = crop.centerY / photoCropSource.naturalHeight;

  photoCropContext.clearRect(0, 0, photoCropCanvas.width, photoCropCanvas.height);
  photoCropContext.drawImage(
    photoCropSource,
    crop.x, crop.y, crop.width, crop.height,
    0, 0, photoCropCanvas.width, photoCropCanvas.height
  );
  photoCropInput.value = JSON.stringify({
    cx: Number(photoCropState.cx.toFixed(6)),
    cy: Number(photoCropState.cy.toFixed(6)),
    zoom: Number(photoCropState.zoom.toFixed(2)),
  });
  photoZoomValue.textContent = `${Number(photoCropState.zoom).toFixed(1).replace('.', ',')}×`;

  if (updateThumbnail) {
    photoPreviewImg.src = photoCropCanvas.toDataURL('image/jpeg', 0.9);
  }
}

photoZoomInput.addEventListener('input', () => {
  photoCropState.zoom = Number(photoZoomInput.value);
  drawPhotoCrop();
  scheduleAutoPreview();
});

photoCropReset.addEventListener('click', () => {
  photoCropState = { cx: 0.5, cy: 0.5, zoom: 1 };
  photoZoomInput.value = '1';
  drawPhotoCrop();
  scheduleAutoPreview();
});

photoCropCanvas.addEventListener('pointerdown', (event) => {
  event.preventDefault();
  activeCropPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
  photoCropCanvas.setPointerCapture(event.pointerId);
  photoCropCanvas.classList.add('is-dragging');
});

photoCropCanvas.addEventListener('pointermove', (event) => {
  if (!activeCropPointer || activeCropPointer.id !== event.pointerId) return;
  const rect = photoCropCanvas.getBoundingClientRect();
  const crop = getPhotoCropRect();
  const deltaX = event.clientX - activeCropPointer.x;
  const deltaY = event.clientY - activeCropPointer.y;
  photoCropState.cx -= (deltaX / rect.width) * crop.width / photoCropSource.naturalWidth;
  photoCropState.cy -= (deltaY / rect.height) * crop.height / photoCropSource.naturalHeight;
  activeCropPointer.x = event.clientX;
  activeCropPointer.y = event.clientY;
  drawPhotoCrop(false);
});

function finishPhotoCropDrag(event) {
  if (!activeCropPointer || activeCropPointer.id !== event.pointerId) return;
  activeCropPointer = null;
  photoCropCanvas.classList.remove('is-dragging');
  drawPhotoCrop();
  scheduleAutoPreview();
}

photoCropCanvas.addEventListener('pointerup', finishPhotoCropDrag);
photoCropCanvas.addEventListener('pointercancel', finishPhotoCropDrag);
photoCropCanvas.addEventListener('keydown', (event) => {
  const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!directions[event.key]) return;
  event.preventDefault();
  const [horizontal, vertical] = directions[event.key];
  const crop = getPhotoCropRect();
  const step = event.shiftKey ? 0.08 : 0.02;
  photoCropState.cx += horizontal * crop.width / photoCropSource.naturalWidth * step;
  photoCropState.cy += vertical * crop.height / photoCropSource.naturalHeight * step;
  drawPhotoCrop();
  scheduleAutoPreview();
});

function clearPhoto() {
  if (photoCropSourceUrl) {
    URL.revokeObjectURL(photoCropSourceUrl);
    photoCropSourceUrl = null;
  }
  photoCropSource.onload = null;
  photoCropSource.onerror = null;
  photoCropSource.src = '';
  photoCropEditor.style.display = 'none';
  photoPreviewImg.src = '';
  photoPreviewImg.style.display = 'none';
  photoPlaceholder.style.display = 'block';
  photoChangeBtn.style.display = 'none';
  photoInput.value = '';
  photoCropState = { cx: 0.5, cy: 0.5, zoom: 1 };
  photoCropInput.value = '{"cx":0.5,"cy":0.5,"zoom":1}';
  photoZoomInput.value = '1';
  photoZoomValue.textContent = '1,0×';
  photoCropContext.clearRect(0, 0, photoCropCanvas.width, photoCropCanvas.height);
}

/* ── Show/hide preview states ──────────────────────────────────────── */
function releasePreviewImage() {
  if (activePreviewObjectUrl) {
    URL.revokeObjectURL(activePreviewObjectUrl);
    activePreviewObjectUrl = null;
  }
  previewImage.removeAttribute('src');
}

function showIdle() {
  releasePreviewImage();
  previewIdle.style.display = '';
  previewLoading.style.display = 'none';
  previewImageWrapper.style.display = 'none';
  previewError.style.display = 'none';
  previewFooter.style.display = 'none';
  setDownloadEnabled(false);
}

function showLoading() {
  releasePreviewImage();
  previewIdle.style.display = 'none';
  previewLoading.style.display = '';
  previewImageWrapper.style.display = 'none';
  previewError.style.display = 'none';
  previewFooter.style.display = 'none';
}

function showImage(src) {
  releasePreviewImage();
  activePreviewObjectUrl = src.startsWith('blob:') ? src : null;
  previewIdleMessage.textContent = DEFAULT_PREVIEW_MESSAGE;
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
  releasePreviewImage();
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

function hidePreviewForPrivacy() {
  if (!previewImageWrapper || previewImageWrapper.style.display === 'none') return;
  showIdle();
  previewIdleMessage.textContent = 'Aperçu masqué pour protéger votre création. Cliquez sur Prévisualiser pour le réafficher.';
}

window.addEventListener('blur', hidePreviewForPrivacy);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') hidePreviewForPrivacy();
});
document.addEventListener('contextmenu', (event) => {
  if (event.target.closest('#preview-image-wrapper')) event.preventDefault();
});
previewImage.addEventListener('dragstart', (event) => event.preventDefault());
window.addEventListener('keydown', (event) => {
  const key = event.key.toLowerCase();
  const commandKey = event.ctrlKey || event.metaKey;
  if (event.key === 'PrintScreen' || (commandKey && ['p', 's'].includes(key))) {
    event.preventDefault();
    hidePreviewForPrivacy();
  }
});

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

/* ── Paid flyer download ─────────────────────────────────────────────── */
async function triggerDownload() {
  if (!form.reportValidity()) {
    return;
  }
  downloadBtn.disabled  = true;
  downloadBtn2.disabled = true;

  try {
    const fd = buildFormData();
    const resp = await fetch(PAYMENT_START_URL, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() },
      body: fd,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    if (!data.checkout_url) {
      throw new Error('Impossible d’ouvrir la page de paiement. Réessayez.');
    }
    window.location.assign(data.checkout_url);
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
  resetTemplateSelection(false);

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
const filiereSelect = document.getElementById('filiere');
const niveauSelect = document.getElementById('niveau');
const autoTemplateLabel = document.getElementById('auto-template-label');

function resetTemplateSelection(refreshPreview = true) {
  if (!templateChips.length) return;
  const autoChip = document.querySelector('.template-chip[data-template="auto"]');
  templateChips.forEach(c => c.classList.toggle('active', c === autoChip));
  if (templateChoiceInput) templateChoiceInput.value = '';
  if (dlTemplateChoiceInput) dlTemplateChoiceInput.value = '';
  if (autoTemplateLabel && niveauSelect) {
    autoTemplateLabel.textContent = `Niveau ${niveauSelect.value.replace(/^N/, '')}`;
  }
  if (refreshPreview) scheduleAutoPreview();
}

if (templateChips.length > 0) {
  templateChips.forEach(chip => {
    chip.addEventListener('click', () => {
      templateChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const selectedTemplate = chip.dataset.template;
      const val = (selectedTemplate === 'auto') ? '' : selectedTemplate;
      if (templateChoiceInput) templateChoiceInput.value = val;
      if (dlTemplateChoiceInput) dlTemplateChoiceInput.value = val;

      if (selectedTemplate === 'auto') {
        if (autoTemplateLabel && niveauSelect) {
          autoTemplateLabel.textContent = `Niveau ${niveauSelect.value.replace(/^N/, '')}`;
        }
      } else {
        const [filiere, niveau] = selectedTemplate.split('-');
        if (filiereSelect) filiereSelect.value = filiere;
        if (niveauSelect) niveauSelect.value = niveau;
        if (autoTemplateLabel) autoTemplateLabel.textContent = `Niveau ${niveauSelect.value.replace(/^N/, '')}`;
      }

      // Re-trigger preview generation with the new selected template
      previewBtn.click();
    });
  });

  [filiereSelect, niveauSelect].forEach(select => {
    if (select) select.addEventListener('change', () => resetTemplateSelection());
  });
}
