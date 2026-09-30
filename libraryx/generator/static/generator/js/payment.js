'use strict';

const paymentScript = document.currentScript;
const statusUrl = paymentScript.dataset.statusUrl;
const waitingPanel = document.getElementById('payment-waiting');
const paymentForm = document.getElementById('payment-form');

async function refreshPaymentStatus() {
  try {
    const response = await fetch(statusUrl, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) return;

    const data = await response.json();
    if (data.status === 'paid' && data.download_url) {
      waitingPanel.hidden = true;
      const successPanel = document.createElement('section');
      successPanel.className = 'payment-success';
      successPanel.innerHTML = '<span class="payment-state-icon" aria-hidden="true">✓</span><h2>Paiement confirmé</h2><p>Votre flyer est prêt à être téléchargé.</p>';
      const downloadLink = document.createElement('a');
      downloadLink.className = 'payment-submit';
      downloadLink.href = data.download_url;
      downloadLink.textContent = 'Télécharger mon flyer PNG';
      successPanel.appendChild(downloadLink);
      waitingPanel.parentNode.insertBefore(successPanel, waitingPanel.nextSibling);
      return;
    }

    if (data.status === 'failed') {
      waitingPanel.hidden = true;
      if (paymentForm) paymentForm.hidden = false;
      if (!document.querySelector('.payment-error')) {
        const message = document.createElement('div');
        message.className = 'payment-error';
        message.setAttribute('role', 'alert');
        message.textContent = 'Le paiement n’a pas abouti. Vérifiez le numéro et réessayez.';
        waitingPanel.parentNode.insertBefore(message, paymentForm);
      }
      return;
    }
  } catch (_error) {
    // Keep the waiting screen in place; the next poll can recover from a temporary connection issue.
  }

  window.setTimeout(refreshPaymentStatus, 5000);
}

if (paymentForm) {
  paymentForm.addEventListener('submit', () => {
    const button = document.getElementById('pay-button');
    if (button) {
      button.disabled = true;
      button.textContent = 'Connexion à DigiPay…';
    }
  });
}

if (waitingPanel && !waitingPanel.hidden) {
  window.setTimeout(refreshPaymentStatus, 3000);
}
