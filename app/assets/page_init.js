(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
    localStorage.setItem('view-rules', 'true');
    localStorage.setItem('void-message-2', 'true');
    localStorage.setItem('muted', '1');
    localStorage.setItem('selected-color', '{{color_id}}');
})()