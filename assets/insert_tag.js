(tag, currentText) => {
    const textarea = document.querySelector('#main_textbox textarea');
    if (!textarea) return currentText + ' ' + tag;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const prefix = start === 0 || currentText[start - 1] === ' ' ? '' : ' ';
    const suffix = end >= currentText.length || currentText[end] === ' ' ? '' : ' ';
    return currentText.slice(0, start) + prefix + tag + suffix + currentText.slice(end);
}
