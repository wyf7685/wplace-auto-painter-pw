(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
    localStorage.setItem('muted', '1');
    localStorage.setItem('theme', 'custom-winter');
    localStorage.setItem('selected-color', '1');
    localStorage.setItem('show-all-colors', 'true');
    localStorage.setItem('show-paint-more-than-one-pixel-msg', 'false');
})();