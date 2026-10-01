// SPL Auction System — Global Theme & Brightness Controller (Requirement 10)

(function() {
    // 1. Instant anti-flash theme initialization
    const savedTheme = localStorage.getItem('spl_theme') || localStorage.getItem('spl-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    if (document.body) {
        document.body.setAttribute('data-theme', savedTheme);
    }
})();

document.addEventListener('DOMContentLoaded', function() {
    // 2. Global Theme Switcher Handlers
    function getActiveTheme() {
        return document.documentElement.getAttribute('data-theme') || localStorage.getItem('spl_theme') || localStorage.getItem('spl-theme') || 'dark';
    }

    function applyGlobalTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        if (document.body) {
            document.body.setAttribute('data-theme', theme);
        }
        localStorage.setItem('spl_theme', theme);
        localStorage.setItem('spl-theme', theme);
        updateAllThemeButtons(theme);
    }

    function updateAllThemeButtons(theme) {
        const buttons = document.querySelectorAll('#theme-toggle-btn, #theme-toggle-btn-admin, .spl-theme-toggle, [data-action="toggle-theme"]');
        buttons.forEach(btn => {
            if (theme === 'light') {
                if (btn.id === 'theme-toggle-btn-admin') {
                    btn.innerHTML = '<i class="fa-solid fa-moon"></i>';
                    btn.title = 'Switch to Dark Mode';
                } else {
                    btn.innerHTML = '<i class="fa-solid fa-moon me-1"></i> Dark Mode';
                }
                btn.classList.remove('btn-outline-warning');
                btn.classList.add('btn-outline-dark');
            } else {
                if (btn.id === 'theme-toggle-btn-admin') {
                    btn.innerHTML = '<i class="fa-solid fa-sun text-warning"></i>';
                    btn.title = 'Switch to Light Mode';
                } else {
                    btn.innerHTML = '<i class="fa-solid fa-sun me-1 text-warning"></i> Light Mode';
                }
                btn.classList.remove('btn-outline-dark');
                btn.classList.add('btn-outline-warning');
            }
        });
    }

    // Attach click events to all theme toggles
    const toggleButtons = document.querySelectorAll('#theme-toggle-btn, #theme-toggle-btn-admin, .spl-theme-toggle, [data-action="toggle-theme"]');
    toggleButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const current = getActiveTheme();
            const next = current === 'dark' ? 'light' : 'dark';
            applyGlobalTheme(next);
        });
    });

    // Initialize all buttons with active theme
    updateAllThemeButtons(getActiveTheme());

    // Listen to storage changes across browser tabs/windows
    window.addEventListener('storage', function(e) {
        if ((e.key === 'spl_theme' || e.key === 'spl-theme') && e.newValue) {
            applyGlobalTheme(e.newValue);
        }
    });

    // 3. Form Loading state handler
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                const loadingText = submitBtn.getAttribute('data-loading-text') || 'Processing...';
                submitBtn.disabled = true;
                submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText}`;
            }
        });
    });
});
