// SPL Auction System — Theme Switcher & UI Scripts

(function() {
    // 1. Instant anti-flash theme initialization
    const savedTheme = localStorage.getItem('spl-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
})();

document.addEventListener('DOMContentLoaded', function() {
    // 2. Theme Toggle Switcher Handler
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', function() {
            const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('spl-theme', newTheme);
            updateThemeToggleIcon(newTheme);
        });

        // Initialize toggle button icon
        const activeTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        updateThemeToggleIcon(activeTheme);
    }

    function updateThemeToggleIcon(theme) {
        if (!themeBtn) return;
        if (theme === 'light') {
            themeBtn.innerHTML = '<i class="fa-solid fa-moon me-1"></i> Dark Mode';
            themeBtn.classList.remove('btn-outline-warning');
            themeBtn.classList.add('btn-outline-dark');
        } else {
            themeBtn.innerHTML = '<i class="fa-solid fa-sun me-1 text-warning"></i> Light Mode';
            themeBtn.classList.remove('btn-outline-dark');
            themeBtn.classList.add('btn-outline-warning');
        }
    }

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
