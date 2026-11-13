(async () => {
  const task = await taskSpace('linkedin_rohit_check');
  const page = task.page('p1');

  const inputInfo = await page.evaluate(() => {
    const editor = document.querySelector('.msg-form__contenteditable, [contenteditable="true"]');
    const sendBtn = document.querySelector('.msg-form__send-button, button.msg-form__send-button');
    return {
      hasEditor: !!editor,
      editorTag: editor ? editor.tagName : null,
      editorClass: editor ? editor.className : null,
      hasSendBtn: !!sendBtn,
      sendBtnDisabled: sendBtn ? sendBtn.disabled : null,
      sendBtnText: sendBtn ? sendBtn.innerText : null
    };
  });

  console.log('[*] LinkedIn Message Form Elements:');
  console.log(JSON.stringify(inputInfo, null, 2));
})();
