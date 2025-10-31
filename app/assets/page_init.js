(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
    localStorage.setItem('view-rules', 'true');
    localStorage.setItem('void-message-2', 'true');
    localStorage.setItem('muted', '1');
    localStorage.setItem('theme', 'custom-winter');
    localStorage.setItem('halloween-2025-popup', 'true')
    localStorage.setItem('selected-color', '{{color_id}}');
    localStorage.setItem('show-all-colors', '{{show_all_colors}}');
})()