/**
 * Quiniela Mundial 2026 - JavaScript
 */

/**
 * Place or update a bet for a match.
 * @param {HTMLButtonElement} button - The bet button element
 */
async function placeBet(button) {
    const form = button.closest('.bet-form');
    const matchId = form.dataset.matchId;
    const homeInput = form.querySelector('.home-input');
    const awayInput = form.querySelector('.away-input');

    const homeScore = parseInt(homeInput.value);
    const awayScore = parseInt(awayInput.value);

    // Validate
    if (isNaN(homeScore) || isNaN(awayScore)) {
        showToast('Ingresa ambos marcadores (0-99)', 'error');
        return;
    }

    if (homeScore < 0 || homeScore > 99 || awayScore < 0 || awayScore > 99) {
        showToast('Los marcadores deben estar entre 0 y 99', 'error');
        return;
    }

    // Disable button during request
    button.disabled = true;
    button.textContent = 'Guardando...';

    try {
        const formData = new FormData();
        formData.append('match_id', matchId);
        formData.append('home_score', homeScore);
        formData.append('away_score', awayScore);

        const response = await fetch('/api/bet', {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (data.success) {
            button.textContent = 'Actualizar';
            button.classList.add('has-bet');
            showToast('✅ Apuesta guardada correctamente', 'success');
        } else {
            button.textContent = button.classList.contains('has-bet') ? 'Actualizar' : 'Apostar';
            showToast('❌ ' + (data.error || 'Error al guardar'), 'error');
        }
    } catch (err) {
        button.textContent = button.classList.contains('has-bet') ? 'Actualizar' : 'Apostar';
        showToast('❌ Error de conexión', 'error');
    } finally {
        button.disabled = false;
    }
}

/**
 * Show a toast notification.
 * @param {string} message - The message to display
 * @param {'success' | 'error' | 'info'} type - The type of toast
 */
function showToast(message, type = 'info') {
    // Remove existing toast
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Auto remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Add keyboard support - Enter key to place bet
 */
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.score-input').forEach(input => {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const form = this.closest('.bet-form');
                const button = form.querySelector('.btn-bet');
                if (!button.disabled) {
                    placeBet(button);
                }
            }
        });

        // Auto-tab to next input on 2 digits
        input.addEventListener('input', function() {
            if (this.value.length >= 2) {
                const form = this.closest('.bet-form');
                const inputs = form.querySelectorAll('.score-input');
                const currentIndex = Array.from(inputs).indexOf(this);
                if (currentIndex < inputs.length - 1) {
                    inputs[currentIndex + 1].focus();
                }
            }
        });
    });
});

// Add toast styles dynamically
const toastStyles = document.createElement('style');
toastStyles.textContent = `
.toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    padding: 14px 24px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 0.95rem;
    z-index: 1000;
    opacity: 0;
    transition: all 0.3s ease;
    box-shadow: 0 10px 25px rgba(0,0,0,0.15);
    max-width: 90vw;
    white-space: nowrap;
}
.toast.show {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
}
.toast-success {
    background: #e6f7e6;
    color: #1a7d36;
    border: 2px solid #34a853;
}
.toast-error {
    background: #fde8e8;
    color: #d93025;
    border: 2px solid #ea4335;
}
.toast-info {
    background: #e8f0fe;
    color: #1a73e8;
    border: 2px solid #1a73e8;
}
@media (max-width: 480px) {
    .toast {
        white-space: normal;
        text-align: center;
    }
}
`;
document.head.appendChild(toastStyles);
